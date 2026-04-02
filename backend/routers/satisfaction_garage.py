"""Satisfaction garage-level and day-level detail endpoints."""

from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from utils import parse_dt as _parse_dt
from sf_client import sf_query_all, sf_parallel, sanitize_soql
import cache

from routers.dispatch_shared import _fmt_et, _is_real_garage
from routers.satisfaction_utils import _satisfaction_insights, _build_day_result

router = APIRouter()


@router.get("/api/insights/satisfaction/garage/{name}")
def api_satisfaction_garage(name: str, month: str = Query(..., description="YYYY-MM")):
    """Garage-level satisfaction detail: daily satisfaction + ATA correlation + insights."""
    import re, calendar, logging, threading
    from datetime import date as _date, timedelta as _td

    name = sanitize_soql(name)
    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format")
    year, mon = int(month[:4]), int(month[5:7])
    today = _date.today()
    if _date(year, mon, 1) > today:
        raise HTTPException(400, "Cannot fetch future months")

    is_current = (year == today.year and mon == today.month)
    cache_key = f'satisfaction_garage_{name}_{month}'
    ttl = 7200 if is_current else 31536000  # 2h current, 1yr past

    cached = cache.get(cache_key)
    if cached:
        return cached
    disk = cache.disk_get(cache_key, ttl=ttl)
    if disk:
        cache.put(cache_key, disk, ttl)
        return disk

    _log = logging.getLogger('satisfaction')
    gen_lock = f'gen_sat_garage_{name}_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=1800):
        def _bg():
            try:
                result = _generate_satisfaction_garage(name, month)
                cache.put(cache_key, result, ttl)
                cache.disk_put(cache_key, result, ttl)
                _log.info(f"Satisfaction garage detail for {name} {month} generated.")
            except Exception as e:
                _log.warning(f"Satisfaction garage generation failed for {name} {month}: {e}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()

    return {'garage': name, 'month': month, 'summary': {}, 'daily': [], 'insights': [], 'loading': True}


def _generate_satisfaction_garage(name: str, month: str):
    """Generate garage-level satisfaction detail with ATA correlation."""
    import calendar, time as _time
    from datetime import date as _date, timedelta as _td

    year, mon = int(month[:4]), int(month[5:7])
    first_day = _date(year, mon, 1)
    last_day_num = calendar.monthrange(year, mon)[1]
    end_day = _date(year, mon, last_day_num) + _td(days=1)

    today = _date.today()
    is_current = (year == today.year and mon == today.month)
    if is_current:
        end_day = today

    start_utc = f"{first_day.isoformat()}T00:00:00Z"
    end_utc = f"{end_day.isoformat()}T00:00:00Z"

    safe_name = name  # already sanitized by sanitize_soql at router level

    # Query 1: Daily satisfaction for this garage
    sat_rows = sf_query_all(f"""
        SELECT DAY_ONLY(CreatedDate) d,
               ERS_Overall_Satisfaction__c sat,
               ERS_Response_Time_Satisfaction__c rt_sat,
               COUNT(Id) cnt
        FROM Survey_Result__c
        WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
          AND ERS_Overall_Satisfaction__c != null
          AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
        GROUP BY DAY_ONLY(CreatedDate), ERS_Overall_Satisfaction__c, ERS_Response_Time_Satisfaction__c
    """)
    _time.sleep(0.5)

    # Query 2: Completed SAs for ATA calculation (reuse existing pattern)
    sas = sf_query_all(f"""
        SELECT Id, CreatedDate, Status, ActualStartTime,
               ERS_Dispatch_Method__c, ERS_PTA__c, WorkType.Name
        FROM ServiceAppointment
        WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
          AND ServiceTerritory.Name = '{safe_name}'
          AND ServiceTerritoryId != null
          AND Status = 'Completed'
    """)
    _time.sleep(0.5)

    # Query 3: Towbook on-location times
    sa_ids = [sa.get('Id') for sa in sas if (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook']
    towbook_on_location = {}
    if sa_ids:
        # Batch in chunks of 200
        for i in range(0, len(sa_ids), 200):
            chunk = sa_ids[i:i+200]
            id_list = "','".join(chunk)
            hist_rows = sf_query_all(f"""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId IN ('{id_list}')
                  AND Field = 'Status'
            """)
            for r in hist_rows:
                if r.get('NewValue') != 'On Location':
                    continue
                sa_id = r.get('ServiceAppointmentId')
                ts = _parse_dt(r.get('CreatedDate'))
                if ts and (sa_id not in towbook_on_location or ts < towbook_on_location[sa_id]):
                    towbook_on_location[sa_id] = ts
            if i + 200 < len(sa_ids):
                _time.sleep(0.3)

    # ── Build daily satisfaction buckets ──
    day_sat = defaultdict(lambda: {'totally_satisfied': 0, 'total': 0, 'rt_ts': 0, 'rt_total': 0})
    for r in sat_rows:
        d = r.get('d', '')
        sat_val = (r.get('sat') or '').strip().lower()
        rt_val = (r.get('rt_sat') or '').strip().lower()
        cnt = r.get('cnt', 0) or 0
        if d and sat_val:
            day_sat[d]['total'] += cnt
            if sat_val == 'totally satisfied':
                day_sat[d]['totally_satisfied'] += cnt
            if rt_val:
                day_sat[d]['rt_total'] += cnt
                if rt_val == 'totally satisfied':
                    day_sat[d]['rt_ts'] += cnt

    # ── Build daily ATA/PTA buckets ──
    day_ata = defaultdict(lambda: {'ata_sum': 0.0, 'ata_count': 0, 'pta_miss': 0, 'pta_eligible': 0})
    for sa in sas:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        date_str = (sa.get('CreatedDate') or '')[:10]
        if not date_str:
            continue
        dm = sa.get('ERS_Dispatch_Method__c') or ''
        d = day_ata[date_str]

        # ATA calculation
        if dm == 'Field Services':
            created = _parse_dt(sa.get('CreatedDate'))
            actual = _parse_dt(sa.get('ActualStartTime'))
            if created and actual:
                diff = (actual - created).total_seconds() / 60
                if 0 < diff < 480:
                    d['ata_sum'] += diff
                    d['ata_count'] += 1
        elif dm == 'Towbook':
            on_loc = towbook_on_location.get(sa.get('Id'))
            if on_loc:
                created = _parse_dt(sa.get('CreatedDate'))
                if created:
                    diff = (on_loc - created).total_seconds() / 60
                    if 0 < diff < 480:
                        d['ata_sum'] += diff
                        d['ata_count'] += 1

        # PTA miss: ERS_PTA__c is minutes promised, compare with actual ATA minutes
        pta_raw = sa.get('ERS_PTA__c')
        if pta_raw is not None:
            pta_min = float(pta_raw)
            if 0 < pta_min < 999:
                created = _parse_dt(sa.get('CreatedDate'))
                if dm == 'Towbook':
                    arrived = towbook_on_location.get(sa.get('Id'))
                else:
                    arrived = _parse_dt(sa.get('ActualStartTime'))
                if created and arrived:
                    ata_min = (arrived - created).total_seconds() / 60
                    if 0 < ata_min < 480:
                        d['pta_eligible'] += 1
                        if ata_min > pta_min:
                            d['pta_miss'] += 1

    # ── Merge and generate output ──
    all_dates = sorted(set(list(day_sat.keys()) + list(day_ata.keys())))
    daily = []
    for d in all_dates:
        s = day_sat.get(d, {'totally_satisfied': 0, 'total': 0, 'rt_ts': 0, 'rt_total': 0})
        a = day_ata.get(d, {'ata_sum': 0, 'ata_count': 0, 'pta_miss': 0, 'pta_eligible': 0})

        sat_pct = round(100 * s['totally_satisfied'] / s['total']) if s['total'] else None
        rt_pct = round(100 * s['rt_ts'] / s['rt_total']) if s['rt_total'] else None
        avg_ata = round(a['ata_sum'] / a['ata_count']) if a['ata_count'] else None
        pta_miss_pct = round(100 * a['pta_miss'] / a['pta_eligible']) if a['pta_eligible'] else None

        insights = _satisfaction_insights(sat_pct, avg_ata, pta_miss_pct, rt_pct, s['total'])

        daily.append({
            'date': d,
            'totally_satisfied_pct': sat_pct,
            'response_time_pct': rt_pct,
            'surveys': s['total'],
            'avg_ata': avg_ata,
            'pta_miss_pct': pta_miss_pct,
            'insights': insights,
        })

    # Summary
    total_surveys = sum(day_sat[d]['total'] for d in day_sat)
    total_ts = sum(day_sat[d]['totally_satisfied'] for d in day_sat)
    total_rt = sum(day_sat[d]['rt_total'] for d in day_sat)
    total_rt_ts = sum(day_sat[d]['rt_ts'] for d in day_sat)
    total_ata_sum = sum(day_ata[d]['ata_sum'] for d in day_ata)
    total_ata_count = sum(day_ata[d]['ata_count'] for d in day_ata)

    summary = {
        'totally_satisfied_pct': round(100 * total_ts / total_surveys) if total_surveys else None,
        'response_time_pct': round(100 * total_rt_ts / total_rt) if total_rt else None,
        'avg_ata': round(total_ata_sum / total_ata_count) if total_ata_count else None,
        'total_surveys': total_surveys,
    }

    # Top-level insights for the garage
    garage_insights = _satisfaction_insights(
        summary['totally_satisfied_pct'],
        summary['avg_ata'],
        None,  # PTA miss aggregated would need full recalc
        summary['response_time_pct'],
        total_surveys,
    )

    return {
        'garage': name,
        'month': month,
        'summary': summary,
        'daily': daily,
        'insights': garage_insights,
    }


@router.get("/api/insights/satisfaction/detail/{name}/{date}")
def api_satisfaction_detail(name: str, date: str):
    """Individual survey cards for a garage on a specific date."""
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

    # Build date range for the day
    from datetime import date as _date, timedelta as _td
    d = _date.fromisoformat(date)
    start_utc = f"{d.isoformat()}T00:00:00Z"
    end_utc = f"{(d + _td(days=1)).isoformat()}T00:00:00Z"

    safe_name = name  # already sanitized by sanitize_soql at router level

    rows = sf_query_all(f"""
        SELECT Id, CreatedDate,
               ERS_Overall_Satisfaction__c,
               ERS_Response_Time_Satisfaction__c,
               ERS_Technician_Satisfaction__c,
               ERS_Work_Order_Number__c,
               ERS_Work_Order__r.WorkOrderNumber,
               Customer_Comments__c
        FROM Survey_Result__c
        WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
          AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
    """)

    surveys = []
    for r in rows:
        surveys.append({
            'id': r.get('Id', ''),
            'created': _fmt_et(r.get('CreatedDate')),
            'overall': r.get('ERS_Overall_Satisfaction__c') or '',
            'response_time': r.get('ERS_Response_Time_Satisfaction__c') or '',
            'technician': r.get('ERS_Technician_Satisfaction__c') or '',
            'wo_number': r.get('ERS_Work_Order_Number__c') or '',
            'comment': r.get('Customer_Comments__c') or '',
        })

    result = {'garage': name, 'date': date, 'surveys': surveys}
    cache.put(cache_key, result, 3600)
    cache.disk_put(cache_key, result, 3600)
    return result


@router.get("/api/insights/satisfaction/day/{date}")
def api_satisfaction_day(date: str):
    """Full day analysis: what drove the satisfaction score on this date.

    Pulls surveys by garage, SA performance (ATA, cancelled, completed),
    and individual problem surveys with comments. Synchronous — data is small
    (single day).
    """
    import re, time as _time
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

    # ── All queries in parallel — no sequential batches ──
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
        # WOLI mapping — single cross-object query (no chunking)
        woli=lambda: sf_query_all(f"""
            SELECT Id, WorkOrderId
            FROM WorkOrderLineItem
            WHERE WorkOrder.CreatedDate >= {start_utc} AND WorkOrder.CreatedDate < {end_utc}
              AND WorkOrder.ServiceTerritoryId != null
        """),
        # Towbook on-location — single cross-object query
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

    # Build WOLI -> WO mapping, then WO -> SA
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
                'driver': '',  # enriched below if needed
            }

    # Build Towbook on-location map
    towbook_on_loc = {}
    for r in data.get('tb_on_loc', []):
        if r.get('NewValue') != 'On Location':
            continue
        sa_id = r.get('ServiceAppointmentId')
        ts = _parse_dt(r.get('CreatedDate'))
        if ts and (sa_id not in towbook_on_loc or ts < towbook_on_loc[sa_id]):
            towbook_on_loc[sa_id] = ts

    return _build_day_result(date, cache_key, surveys, sas, wo_to_sa, towbook_on_loc)
