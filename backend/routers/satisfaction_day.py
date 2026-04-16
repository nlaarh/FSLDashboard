"""Satisfaction day-level drill-down endpoints.

Two endpoints:
  • /api/insights/satisfaction/detail/{name}/{date} — garage-scoped day detail
      Returns: daily summary, per-driver breakdown, surveys with comments.
  • /api/insights/satisfaction/day/{date}          — company-wide day analysis

Both answer "what happened that day" — surveys + operational context.
Split out from satisfaction_garage.py to keep each router under 600 lines.
"""

from collections import defaultdict
from fastapi import APIRouter, HTTPException

from utils import parse_dt as _parse_dt
from sf_client import sf_query_all, sf_parallel, sanitize_soql
import cache

from routers.dispatch_shared import _fmt_et
from routers.satisfaction_utils import _satisfaction_insights, _build_day_result
from routers.satisfaction_shared import _build_towbook_on_location_map, _process_sa_ata_pta, _pct
from routers.garages_scorecard import _load_ai_settings, _call_openai

router = APIRouter()


@router.get("/api/insights/satisfaction/detail/{name}/{date}")
def api_satisfaction_detail(name: str, date: str):
    """Day-level drill-down for a garage — explains what drove the day's score.

    Returns: daily summary (sat %, ATA, PTA miss, completed SAs), per-driver
    breakdown for the day (SAs handled, ATA, satisfaction %), individual
    surveys with comments. Intended to answer "what happened that day".
    """
    import re

    name = sanitize_soql(name)
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(400, "date must be YYYY-MM-DD format")

    cache_key = f'satisfaction_detail_{name}_{date}'
    cached = cache.get(cache_key)
    if cached:
        return cached
    disk = cache.disk_get(cache_key, ttl=3600)
    if disk:
        cache.put(cache_key, disk, 3600)
        return disk

    from datetime import date as _date, timedelta as _td
    d = _date.fromisoformat(date)
    start_utc = f"{d.isoformat()}T00:00:00Z"
    end_utc = f"{(d + _td(days=1)).isoformat()}T00:00:00Z"

    safe_name = name

    data = sf_parallel(
        surveys=lambda: sf_query_all(f"""
            SELECT Id, CreatedDate,
                   ERS_Overall_Satisfaction__c,
                   ERS_Response_Time_Satisfaction__c,
                   ERS_Technician_Satisfaction__c,
                   ERSSatisfaction_With_Being_Kept_Informed__c,
                   ERS_Work_Order_Number__c,
                   ERS_Work_Order__r.WorkOrderNumber,
                   ERS_Driver__c, ERS_Driver__r.Name,
                   Customer_Comments__c
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
        """),
        sas=lambda: sf_query_all(f"""
            SELECT Id, CreatedDate, Status, ActualStartTime,
                   ERS_Dispatch_Method__c, ERS_PTA__c, WorkType.Name,
                   (SELECT ServiceResourceId, ServiceResource.Name FROM ServiceResources)
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritory.Name = '{safe_name}'
              AND ServiceTerritoryId != null
              AND Status = 'Completed'
        """),
        tb_on_loc=lambda: sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE Field = 'Status'
              AND ServiceAppointment.CreatedDate >= {start_utc}
              AND ServiceAppointment.CreatedDate < {end_utc}
              AND ServiceAppointment.ServiceTerritory.Name = '{safe_name}'
              AND ServiceAppointment.ERS_Dispatch_Method__c = 'Towbook'
              AND ServiceAppointment.Status = 'Completed'
        """),
    )

    # ── Surveys list + day totals ──
    surveys = []
    total_surveys = 0
    totally_sat = 0
    rt_total = 0
    rt_sat = 0
    for r in data['surveys']:
        overall = r.get('ERS_Overall_Satisfaction__c') or ''
        rt = r.get('ERS_Response_Time_Satisfaction__c') or ''
        total_surveys += 1
        if overall.strip().lower() == 'totally satisfied':
            totally_sat += 1
        if rt:
            rt_total += 1
            if rt.strip().lower() == 'totally satisfied':
                rt_sat += 1
        surveys.append({
            'id': r.get('Id', ''),
            'created': _fmt_et(r.get('CreatedDate')),
            'overall': overall,
            'response_time': rt,
            'technician': r.get('ERS_Technician_Satisfaction__c') or '',
            'wo_number': r.get('ERS_Work_Order_Number__c') or '',
            'driver_name': (r.get('ERS_Driver__r') or {}).get('Name') or '',
            'comment': r.get('Customer_Comments__c') or '',
        })

    # ── ATA/PTA + per-driver stats (shared logic) ──
    tb_on_loc = _build_towbook_on_location_map(data['tb_on_loc'])
    day_ata, driver_ops = _process_sa_ata_pta(data['sas'], tb_on_loc)

    # Flatten day_ata to single-day totals (this endpoint is always one day)
    day_vals = list(day_ata.values())
    day_ata_sum = sum(v['ata_sum'] for v in day_vals)
    day_ata_count = sum(v['ata_count'] for v in day_vals)
    day_pta_miss = sum(v['pta_miss'] for v in day_vals)
    day_pta_eligible = sum(v['pta_eligible'] for v in day_vals)
    sa_completed = sum(v['sa_count'] for v in driver_ops.values())

    # Surveys per driver — all 4 satisfaction dimensions
    _empty_dsat = lambda: {'surveys': 0, 'ts_overall': 0,
                           'n_rt': 0, 'ts_rt': 0,
                           'n_tech': 0, 'ts_tech': 0,
                           'n_info': 0, 'ts_info': 0}
    driver_sat = defaultdict(_empty_dsat)
    for r in data['surveys']:
        did = r.get('ERS_Driver__c')
        if not did:
            continue
        ds = driver_sat[did]
        ds['surveys'] += 1
        if (r.get('ERS_Overall_Satisfaction__c') or '').strip().lower() == 'totally satisfied':
            ds['ts_overall'] += 1
        rt = (r.get('ERS_Response_Time_Satisfaction__c') or '').strip().lower()
        if rt:
            ds['n_rt'] += 1
            if rt == 'totally satisfied': ds['ts_rt'] += 1
        tech = (r.get('ERS_Technician_Satisfaction__c') or '').strip().lower()
        if tech:
            ds['n_tech'] += 1
            if tech == 'totally satisfied': ds['ts_tech'] += 1
        info = (r.get('ERSSatisfaction_With_Being_Kept_Informed__c') or
                r.get('kept_informed') or '').strip().lower()
        if info:
            ds['n_info'] += 1
            if info == 'totally satisfied': ds['ts_info'] += 1

    drivers_list = []
    for did in set(driver_ops.keys()) | set(driver_sat.keys()):
        ops = driver_ops.get(did, {'driver_id': did, 'name': None,
                                    'sa_count': 0, 'ata_sum': 0.0, 'ata_count': 0,
                                    'pta_miss': 0, 'pta_eligible': 0})
        sat = driver_sat.get(did, _empty_dsat())
        name = ops['name']
        if not name:
            for r in data['surveys']:
                if r.get('ERS_Driver__c') == did:
                    name = (r.get('ERS_Driver__r') or {}).get('Name')
                    break
        if not name:
            continue
        drivers_list.append({
            'driver_id': did,
            'name': name,
            'sa_count': ops['sa_count'],
            'surveys': sat['surveys'],
            'totally_satisfied_pct': _pct(sat['ts_overall'], sat['surveys']),
            'technician_pct': _pct(sat['ts_tech'], sat['n_tech']),
            'response_time_pct': _pct(sat['ts_rt'], sat['n_rt']),
            'kept_informed_pct': _pct(sat['ts_info'], sat['n_info']),
            'avg_ata': round(ops['ata_sum'] / ops['ata_count']) if ops['ata_count'] else None,
            'pta_miss_pct': _pct(ops['pta_miss'], ops['pta_eligible']),
        })
    drivers_list.sort(key=lambda x: (x['sa_count'] or 0, x['surveys'] or 0), reverse=True)

    sat_pct = round(100 * totally_sat / total_surveys) if total_surveys else None
    rt_pct = round(100 * rt_sat / rt_total) if rt_total else None
    avg_ata = round(day_ata_sum / day_ata_count) if day_ata_count else None
    pta_miss_pct = round(100 * day_pta_miss / day_pta_eligible) if day_pta_eligible else None

    summary = {
        'totally_satisfied_pct': sat_pct,
        'response_time_pct': rt_pct,
        'avg_ata': avg_ata,
        'pta_miss_pct': pta_miss_pct,
        'total_surveys': total_surveys,
        'sa_completed': sa_completed,
    }

    insights = _satisfaction_insights(sat_pct, avg_ata, pta_miss_pct, rt_pct, total_surveys)

    result = {
        'garage': name,
        'date': date,
        'summary': summary,
        'insights': insights,
        'drivers': drivers_list,
        'surveys': surveys,
    }
    cache.put(cache_key, result, 3600)
    cache.disk_put(cache_key, result, 3600)
    return result


def _generate_day_ai_summary(garage, date, summary, drivers, surveys, sa_completed):
    """Use LLM to produce a rich HTML executive narrative for the day drill-down."""
    import logging
    _log = logging.getLogger('satisfaction')

    provider, api_key, model = _load_ai_settings()
    if not api_key:
        return None

    s = summary
    total_sas = sa_completed or 0
    num_drivers = len([d for d in drivers if d.get('sa_count', 0) > 0])

    # Driver detail — workload distribution + performance
    driver_lines = []
    for d in sorted(drivers, key=lambda x: x.get('sa_count', 0), reverse=True)[:15]:
        sa_share = round(100 * d['sa_count'] / total_sas) if total_sas else 0
        driver_lines.append(
            f"  {d['name']}: {d['sa_count']} SAs ({sa_share}% of load), "
            f"ATA={d.get('avg_ata') or '?'}m, PTA miss={d.get('pta_miss_pct') or '?'}%, "
            f"Sat={d.get('totally_satisfied_pct') or '?'}% ({d.get('surveys', 0)} surveys)"
        )

    # ATA outliers
    ata_outliers = [d for d in drivers if d.get('avg_ata') and d['avg_ata'] > 60]
    ata_fast = [d for d in drivers if d.get('avg_ata') and d['avg_ata'] <= 30 and d.get('sa_count', 0) >= 3]

    # Customer comments — all with sentiment
    comment_lines = []
    for sv in surveys:
        if sv.get('comment'):
            overall = sv.get('overall', '?')
            driver = sv.get('driver_name') or 'Unknown'
            comment_lines.append(f"  [{overall}] [{driver}] \"{sv['comment'][:250]}\"")

    # Capacity signal
    avg_sas_per_driver = round(total_sas / num_drivers, 1) if num_drivers else 0
    heavy = [d for d in drivers if total_sas > 0 and d.get('sa_count', 0) > total_sas * 0.25]

    prompt = f"""You are an expert fleet operations analyst for AAA roadside assistance.
Analyze this day's data for garage "{garage}" on {date} and produce a ROOT CAUSE analysis.

Go DEEPER than restating numbers. Investigate:
- Was capacity the issue? ({num_drivers} drivers handled {total_sas} SAs = {avg_sas_per_driver} avg each)
- Were assignments balanced or was one driver overloaded?
- Did slow drivers (high ATA) get too many calls while fast drivers sat idle?
- Are PTA misses concentrated on specific drivers or spread evenly?
- What are customers actually complaining about in their own words?
- Is the scheduler/optimizer helping or hurting? (look at load distribution)

DATA:
Overall: {s.get('totally_satisfied_pct') or '?'}% sat | {s.get('response_time_pct') or '?'}% RT | ATA {s.get('avg_ata') or '?'}m | PTA miss {s.get('pta_miss_pct') or '?'}% | {total_sas} SAs | {s.get('total_surveys', 0)} surveys

DRIVER BREAKDOWN (sorted by workload):
{chr(10).join(driver_lines) if driver_lines else 'No driver data'}

ATA OUTLIERS (>60m): {', '.join(f"{d['name']}={d['avg_ata']}m" for d in ata_outliers) or 'None'}
FAST DRIVERS (≤30m, 3+ SAs): {', '.join(f"{d['name']}={d['avg_ata']}m" for d in ata_fast) or 'None'}
HEAVY LOAD (>25% of SAs): {', '.join(f"{d['name']}={d['sa_count']}/{total_sas}" for d in heavy) or 'Balanced'}

CUSTOMER VOICE ({len(comment_lines)} comments):
{chr(10).join(comment_lines[:10]) if comment_lines else 'No comments'}

OUTPUT FORMAT: Return ONLY raw HTML (no markdown, no ```html fences). Use these sections:
<h3>What Happened</h3> — 2-3 sentences, headline assessment vs 82% target
<h3>Root Cause Analysis</h3> — WHY the score is what it is. Capacity? Driver quality? Assignment balance? Be specific with names.
<h3>Customer Voice</h3> — Themes from actual comments. Quote key phrases.
<h3>Action Items</h3> — 2-3 specific, actionable recommendations with driver names where relevant.

Use <span style="color:#ef4444"> for bad metrics, <span style="color:#22c55e"> for good ones, <strong> for emphasis.
Be concise — under 300 words total. No fluff."""

    try:
        text = _call_openai(api_key, model, prompt)
        return text
    except Exception as e:
        _log.warning('AI day summary failed: %s', e)
        return None


@router.get("/api/insights/satisfaction/detail/{name}/{date}/ai-summary")
def api_satisfaction_detail_ai(name: str, date: str):
    """Async AI executive summary for a garage day — called separately so the page loads fast."""
    import re

    name = sanitize_soql(name)
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(400, "date must be YYYY-MM-DD format")

    ai_cache_key = f'satisfaction_detail_ai_{name}_{date}'
    cached = cache.get(ai_cache_key)
    if cached:
        return cached
    disk = cache.disk_get(ai_cache_key, ttl=7200)
    if disk:
        cache.put(ai_cache_key, disk, 7200)
        return disk

    # Get the underlying detail data — try cache first, otherwise call the endpoint directly
    detail_key = f'satisfaction_detail_{name}_{date}'
    detail = cache.get(detail_key) or cache.disk_get(detail_key, ttl=3600)
    if not detail or not detail.get('summary'):
        # Cache miss — fetch synchronously (this runs in parallel with the main call)
        try:
            detail = api_satisfaction_detail(name, date)
        except Exception:
            pass
    if not detail or not detail.get('summary'):
        return {'ai_summary': None}

    ai_summary = _generate_day_ai_summary(
        name, date, detail['summary'], detail.get('drivers', []),
        detail.get('surveys', []), detail['summary'].get('sa_completed', 0))

    result = {'ai_summary': ai_summary}
    cache.put(ai_cache_key, result, 7200)
    cache.disk_put(ai_cache_key, result, 7200)
    return result


@router.get("/api/insights/satisfaction/day/{date}")
def api_satisfaction_day(date: str):
    """Full day analysis: what drove the satisfaction score on this date.

    Pulls surveys by garage, SA performance (ATA, cancelled, completed),
    and individual problem surveys with comments. Synchronous — data is small
    (single day).
    """
    import re
    from datetime import date as _date, timedelta as _td

    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(400, "date must be YYYY-MM-DD format")

    cache_key = f'satisfaction_day_{date}'
    cached = cache.get(cache_key)
    if cached:
        return cached
    disk = cache.disk_get(cache_key, ttl=7200)
    if disk:
        cache.put(cache_key, disk, 7200)
        return disk

    d = _date.fromisoformat(date)
    start_utc = f"{d.isoformat()}T00:00:00Z"
    end_utc = f"{(d + _td(days=1)).isoformat()}T00:00:00Z"

    data = sf_parallel(
        surveys=lambda: sf_query_all(f"""
            SELECT Id, CreatedDate,
                   ERS_Overall_Satisfaction__c,
                   ERS_Response_Time_Satisfaction__c,
                   ERS_Technician_Satisfaction__c,
                   ERS_Work_Order_Number__c,
                   ERS_Work_Order__r.Id,
                   ERS_Work_Order__r.ServiceTerritory.Name,
                   Customer_Comments__c
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
        """),
        sas=lambda: sf_query_all(f"""
            SELECT Id, CreatedDate, Status, ActualStartTime,
                   ERS_Dispatch_Method__c, ERS_PTA__c,
                   ServiceTerritory.Name, WorkType.Name,
                   ERS_Cancellation_Reason__c,
                   AppointmentNumber, ParentRecordId
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritoryId != null
              AND RecordType.Name = 'ERS Service Appointment'
        """),
        woli=lambda: sf_query_all(f"""
            SELECT Id, WorkOrderId
            FROM WorkOrderLineItem
            WHERE WorkOrder.CreatedDate >= {start_utc} AND WorkOrder.CreatedDate < {end_utc}
              AND WorkOrder.ServiceTerritoryId != null
        """),
        tb_on_loc=lambda: sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE Field = 'Status'
              AND ServiceAppointment.CreatedDate >= {start_utc}
              AND ServiceAppointment.CreatedDate < {end_utc}
              AND ServiceAppointment.ERS_Dispatch_Method__c = 'Towbook'
              AND ServiceAppointment.Status = 'Completed'
              AND ServiceAppointment.ServiceTerritoryId != null
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
        """),
    )
    surveys = data['surveys']
    sas = data['sas']

    woli_to_wo = {r['Id']: r.get('WorkOrderId') for r in data['woli']}
    wo_to_sa = {}
    for sa in sas:
        woli_id = sa.get('ParentRecordId')
        wo_id = woli_to_wo.get(woli_id)
        if wo_id and wo_id not in wo_to_sa:
            wo_to_sa[wo_id] = {
                'sa_number': sa.get('AppointmentNumber', ''),
                'call_date': (sa.get('CreatedDate') or '')[:10],
                'status': sa.get('Status', ''),
                'driver': '',
            }

    towbook_on_loc = {}
    for r in data.get('tb_on_loc', []):
        if r.get('NewValue') != 'On Location':
            continue
        sa_id = r.get('ServiceAppointmentId')
        ts = _parse_dt(r.get('CreatedDate'))
        if ts and (sa_id not in towbook_on_loc or ts < towbook_on_loc[sa_id]):
            towbook_on_loc[sa_id] = ts

    return _build_day_result(date, cache_key, surveys, sas, wo_to_sa, towbook_on_loc)
