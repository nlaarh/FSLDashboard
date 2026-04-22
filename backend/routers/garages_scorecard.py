"""Garage Performance Scorecard — satisfaction scores, bonus calculation, driver breakdown."""

import os
import logging
import requests as _requests
from datetime import date as _date
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from sf_client import sf_query_all, sf_parallel, sanitize_soql
from sf_batch import batch_soql_parallel
from utils import parse_dt as _parse_dt, is_fleet_territory, totally_satisfied_pct as _totally_satisfied_pct, soql_date_range
import cache

router = APIRouter()
log = logging.getLogger('garages_scorecard')


def _bonus_for_pct(pct):
    """Return (bonus_per_sa, tier_label) — reads configurable tiers from SQLite."""
    import database
    return database.bonus_for_pct(pct)


def _load_ai_settings():
    # Env var takes priority (Azure App Settings), fall back to SQLite settings
    env_key = os.environ.get('OPENAI_API_KEY', '')
    if env_key:
        return 'openai', env_key, os.environ.get('OPENAI_MODEL', '')
    try:
        import database
        cb = database.get_setting('chatbot') or {}
        return cb.get('provider', ''), cb.get('api_key', ''), cb.get('primary_model', '')
    except Exception:
        return '', '', ''


def _call_openai(api_key, model, prompt):
    """Call OpenAI for executive summary."""
    try:
        resp = _requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model or "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are a fleet operations analyst for AAA roadside assistance. Write concise, actionable executive summaries. Use plain English. Be specific about which drivers and metrics. CRITICAL: Bonuses are per-driver based on individual TECHNICIAN satisfaction score (not overall). A driver with ≥92% tech score earns a bonus even if the garage average is below 92%. Never contradict the bonus data provided. Keep it under 200 words."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 512,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning('OpenAI call failed: %s', e)
        return None


@router.get("/api/garages/{territory_id}/performance-scorecard")
def api_garage_performance_scorecard(
    territory_id: str,
    start_date: str = Query(None, description="YYYY-MM-DD"),
    end_date: str = Query(None, description="YYYY-MM-DD"),
):
    """Garage performance scorecard: 4 satisfaction scores, primary/secondary split,
    driver breakdown with bonus calculation, AI executive summary."""

    territory_id = sanitize_soql(territory_id)

    # Default date range: current month
    # Guard: when called internally (not via FastAPI), Query defaults aren't resolved
    today = _date.today()
    if not isinstance(start_date, str) or not start_date:
        start_date = today.replace(day=1).isoformat()
    if not isinstance(end_date, str) or not end_date:
        end_date = today.isoformat()

    cache_key = f'garage_perf_scorecard_{territory_id}_{start_date}_{end_date}'

    def _compute():
        return _build_scorecard(territory_id, start_date, end_date)

    # Stale-while-revalidate: serve cached data instantly, refresh in background
    # ttl=3600 (1h fresh), stale_ttl=172800 (48h max staleness)
    result = cache.stale_while_revalidate(cache_key, _compute, ttl=3600, stale_ttl=172800)
    # Strip internal drill-down data from API response (used by /driver-sas endpoint)
    if isinstance(result, dict) and '_sa_driver_map' in result:
        result = {k: v for k, v in result.items() if not k.startswith('_')}
    return result


def _build_scorecard(territory_id: str, start_date: str, end_date: str) -> dict:
    """Heavy computation — called only on cache miss."""
    start_utc, end_utc = soql_date_range(start_date, end_date)

    # ── Parallel queries: surveys + SAs + territory history ──
    def _get_surveys():
        return sf_query_all(f"""
            SELECT ERS_Work_Order__c,
                   ERS_Overall_Satisfaction__c,
                   ERS_Response_Time_Satisfaction__c,
                   ERS_Technician_Satisfaction__c,
                   ERSSatisfaction_With_Being_Kept_Informed__c,
                   ERS_Driver__r.Name,
                   Off_Platform_Driver__c,
                   Survey_Driver__c,
                   Customer_Comments__c,
                   ERS_Work_Order__r.WorkOrderNumber,
                   ERS_Work_Order__r.CreatedDate
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.ServiceTerritoryId = '{territory_id}'
              AND ERS_Work_Order__r.CreatedDate >= {start_utc}
              AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
            LIMIT 15000
        """)

    def _get_sas():
        return sf_query_all(f"""
            SELECT Id, AppointmentNumber, ParentRecordId, CreatedDate, Status,
                   ActualStartTime, ERS_PTA__c,
                   WorkType.Name, ERS_Dispatch_Method__c,
                   ERS_Facility_Decline_Reason__c
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {start_utc}
              AND CreatedDate < {end_utc}
              AND RecordType.Name = 'ERS Service Appointment'
              AND WorkType.Name != 'Tow Drop-Off'
            LIMIT 15000
        """)

    def _get_territory_history():
        """First territory assignment for each SA — OldValue=null means original assignment.
        Field is 'ServiceTerritory', stores both name and ID in separate rows."""
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, OldValue, NewValue, CreatedDate
            FROM ServiceAppointmentHistory
            WHERE Field = 'ServiceTerritory'
              AND ServiceAppointment.ServiceTerritoryId = '{territory_id}'
              AND ServiceAppointment.CreatedDate >= {start_utc}
              AND ServiceAppointment.CreatedDate < {end_utc}
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
            ORDER BY ServiceAppointmentId, CreatedDate ASC
            LIMIT 15000
        """)

    def _get_towbook_on_location():
        """Real arrival for Towbook SAs — ActualStartTime is fake."""
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE Field = 'Status'
              AND ServiceAppointment.ServiceTerritoryId = '{territory_id}'
              AND ServiceAppointment.CreatedDate >= {start_utc}
              AND ServiceAppointment.CreatedDate < {end_utc}
              AND ServiceAppointment.ERS_Dispatch_Method__c = 'Towbook'
              AND ServiceAppointment.Status = 'Completed'
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
            LIMIT 15000
        """)

    def _get_woli():
        """Map WOLI → WO in one query (replaces sequential chunked batches)."""
        return sf_query_all(f"""
            SELECT Id, WorkOrderId
            FROM WorkOrderLineItem
            WHERE WorkOrder.ServiceTerritoryId = '{territory_id}'
              AND WorkOrder.CreatedDate >= {start_utc}
              AND WorkOrder.CreatedDate < {end_utc}
            LIMIT 15000
        """)

    data = sf_parallel(surveys=_get_surveys, sas=_get_sas,
                       territory_hist=_get_territory_history,
                       tb_on_loc=_get_towbook_on_location,
                       woli=_get_woli,
                       territory=lambda: sf_query_all(f"SELECT Name FROM ServiceTerritory WHERE Id = '{territory_id}' LIMIT 1"))
    surveys = data['surveys']
    sas = data['sas']
    territory_hist = data['territory_hist']
    territory_name = data['territory'][0].get('Name', '') if data['territory'] else ''
    _is_fleet = is_fleet_territory(territory_name)

    # Build Towbook real arrival map: SA Id → On Location datetime
    towbook_arrival = {}
    for r in data['tb_on_loc']:
        if r.get('NewValue') != 'On Location':
            continue
        sa_id = r.get('ServiceAppointmentId')
        ts = _parse_dt(r.get('CreatedDate'))
        if ts and (sa_id not in towbook_arrival or ts < towbook_arrival[sa_id]):
            towbook_arrival[sa_id] = ts

    # ── Map SAs to drivers for per-driver operational stats ──
    all_sa_ids = [sa['Id'] for sa in sas]
    ar_rows = batch_soql_parallel("""
        SELECT ServiceAppointmentId, ServiceResourceId, ServiceResource.Name, CreatedDate
        FROM AssignedResource
        WHERE ServiceAppointmentId IN ('{id_list}')
        ORDER BY ServiceAppointmentId, CreatedDate DESC
    """, all_sa_ids, chunk_size=200) if all_sa_ids else []
    sa_to_driver = {}  # sa_id -> driver_name
    for r in ar_rows:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id or sa_id in sa_to_driver:
            continue
        sa_to_driver[sa_id] = (r.get('ServiceResource') or {}).get('Name') or ''

    # Per-driver SA aggregation: completed, declined, ATA + detail lists
    _drv_ops = defaultdict(lambda: {'completed': 0, 'declined': 0, 'ata_vals': [],
                                     'completed_list': [], 'declined_list': []})
    for sa in sas:
        driver_name = sa_to_driver.get(sa['Id'])
        if not driver_name:
            continue
        ds = _drv_ops[driver_name]
        wt = ((sa.get('WorkType') or {}).get('Name', '') or '')
        sa_row = {
            'sa_number': sa.get('AppointmentNumber') or '',
            'date': (sa.get('CreatedDate') or '')[:10],
            'work_type': wt,
            'status': sa.get('Status') or '',
        }
        if sa.get('Status') == 'Completed':
            ds['completed'] += 1
            ds['completed_list'].append(sa_row)
        if sa.get('ERS_Facility_Decline_Reason__c'):
            ds['declined'] += 1
            ds['declined_list'].append({**sa_row, 'decline_reason': sa['ERS_Facility_Decline_Reason__c']})
        # ATA calc (same logic as _sa_stats)
        if sa.get('Status') == 'Completed':
            created = _parse_dt(sa.get('CreatedDate'))
            dm = sa.get('ERS_Dispatch_Method__c') or ''
            actual = towbook_arrival.get(sa['Id']) if dm == 'Towbook' else _parse_dt(sa.get('ActualStartTime'))
            if created and actual:
                ata = (actual - created).total_seconds() / 60
                if 0 < ata < 480:
                    ds['ata_vals'].append(ata)

    # Find SAs where this garage is NOT the original territory (secondary)
    # The first record per SA with OldValue=null is the original assignment.
    # If that NewValue != this territory_id, the SA cascaded here.
    original_territory = {}  # sa_id -> first territory ID
    for row in territory_hist:
        sa_id = row.get('ServiceAppointmentId')
        if sa_id in original_territory:
            continue  # already have the first record
        if row.get('OldValue') is None:
            nv = row.get('NewValue') or ''
            # ID rows are 15 or 18 chars starting with 0H
            if len(nv) >= 15 and nv.startswith('0H'):
                original_territory[sa_id] = nv

    reassigned_sa_ids = {sa_id for sa_id, orig_tid in original_territory.items()
                         if orig_tid != territory_id}

    total_completed = sum(1 for sa in sas if sa.get('Status') == 'Completed')

    # ── Classify SAs as primary vs secondary ──
    # Build SA lookup by ID (for territory classification)
    sa_by_id = {sa['Id']: sa for sa in sas}

    primary_sas = [sa for sa in sas if sa['Id'] not in reassigned_sa_ids]
    secondary_sas = [sa for sa in sas if sa['Id'] in reassigned_sa_ids]

    def _sa_stats(sa_list):
        total = len(sa_list)
        completed = sum(1 for sa in sa_list if sa.get('Status') == 'Completed')
        cancelled = sum(1 for sa in sa_list if 'cancel' in (sa.get('Status') or '').lower())
        declined = sum(1 for sa in sa_list if sa.get('ERS_Facility_Decline_Reason__c'))
        # ATA: Fleet = ActualStartTime, Towbook = SAHistory "On Location"
        ata_vals = []
        pta_vals = []
        for sa in sa_list:
            if sa.get('Status') != 'Completed':
                continue
            created = _parse_dt(sa.get('CreatedDate'))
            dm = sa.get('ERS_Dispatch_Method__c') or ''
            if dm == 'Towbook':
                actual = towbook_arrival.get(sa['Id'])
            else:
                actual = _parse_dt(sa.get('ActualStartTime'))
            if created and actual:
                ata = (actual - created).total_seconds() / 60
                if 0 < ata < 480:
                    ata_vals.append(ata)
            pta = sa.get('ERS_PTA__c')
            if pta and 0 < float(pta) < 999:
                pta_vals.append(float(pta))
        avg_ata = round(sum(ata_vals) / len(ata_vals)) if ata_vals else None
        avg_pta = round(sum(pta_vals) / len(pta_vals)) if pta_vals else None
        pta_hit = sum(1 for a, p in zip(ata_vals, pta_vals) if a <= p) if ata_vals and pta_vals else None
        pta_hit_pct = round(100 * pta_hit / len(ata_vals)) if pta_hit is not None and ata_vals else None
        return {
            'total_sas': total,
            'completed': completed,
            'cancelled': cancelled,
            'declined': declined,
            'avg_ata': avg_ata,
            'avg_pta': avg_pta,
            'pta_hit_pct': pta_hit_pct,
        }

    # ── Map WorkOrder → SA to classify surveys as primary/secondary ──
    # WOLI was fetched in parallel — build mapping: WO Id → SA Id
    woli_to_wo = {r['Id']: r.get('WorkOrderId') for r in data['woli']}
    wo_to_sa = {}  # WO Id → SA Id
    wo_to_sa_number = {}  # WO Id → SA AppointmentNumber
    for sa in sas:
        woli_id = sa.get('ParentRecordId')
        wo_id = woli_to_wo.get(woli_id)
        if wo_id and wo_id not in wo_to_sa:
            wo_to_sa[wo_id] = sa['Id']
            wo_to_sa_number[wo_id] = sa.get('AppointmentNumber', '')

    primary_surveys = []
    secondary_surveys = []
    for sv in surveys:
        wo_id = sv.get('ERS_Work_Order__c') or ''
        sa_id = wo_to_sa.get(wo_id)
        if sa_id and sa_id in reassigned_sa_ids:
            secondary_surveys.append(sv)
        else:
            primary_surveys.append(sv)

    # ── Garage-level scores ──
    overall_pct = _totally_satisfied_pct(surveys, 'ERS_Overall_Satisfaction__c')
    rt_pct = _totally_satisfied_pct(surveys, 'ERS_Response_Time_Satisfaction__c')
    tech_pct = _totally_satisfied_pct(surveys, 'ERS_Technician_Satisfaction__c')
    informed_pct = _totally_satisfied_pct(surveys, 'ERSSatisfaction_With_Being_Kept_Informed__c')

    # Bonus only applies to contractors — fleet drivers are internal employees
    if _is_fleet:
        bonus_per_sa, bonus_tier, total_bonus = 0, 'N/A (Fleet)', 0
    else:
        bonus_per_sa, bonus_tier = _bonus_for_pct(tech_pct)
        total_bonus = bonus_per_sa * total_completed

    # ── Primary vs Secondary scores + SA stats ──
    primary_sa_stats = _sa_stats(primary_sas)
    secondary_sa_stats = _sa_stats(secondary_sas)

    def _group_scores(survey_group, sa_stats):
        return {
            'overall_pct': _totally_satisfied_pct(survey_group, 'ERS_Overall_Satisfaction__c'),
            'response_time_pct': _totally_satisfied_pct(survey_group, 'ERS_Response_Time_Satisfaction__c'),
            'technician_pct': _totally_satisfied_pct(survey_group, 'ERS_Technician_Satisfaction__c'),
            'kept_informed_pct': _totally_satisfied_pct(survey_group, 'ERSSatisfaction_With_Being_Kept_Informed__c'),
            'survey_count': len(survey_group),
            **sa_stats,
        }

    # ── Driver breakdown ──
    driver_map = defaultdict(list)  # driver_name -> [survey rows]
    for sv in surveys:
        # Driver name: Fleet = ERS_Driver__r.Name, Towbook = Survey_Driver__c (formula)
        driver = (sv.get('ERS_Driver__r') or {}).get('Name') or sv.get('Survey_Driver__c') or 'Unknown'
        driver_map[driver].append(sv)

    drivers = []
    for name, svs in sorted(driver_map.items(), key=lambda x: len(x[1]), reverse=True):
        d_tech_pct = _totally_satisfied_pct(svs, 'ERS_Technician_Satisfaction__c')

        # Individual survey details for drill-down
        survey_details = []
        for sv in svs:
            wo = sv.get('ERS_Work_Order__r') or {}
            created = _parse_dt(wo.get('CreatedDate'))
            wo_id = sv.get('ERS_Work_Order__c') or ''
            sa_num = wo_to_sa_number.get(wo_id, '')
            survey_details.append({
                'wo_number': wo.get('WorkOrderNumber', ''),
                'sa_number': sa_num,
                'call_date': created.strftime('%Y-%m-%d') if created else '',
                'overall': sv.get('ERS_Overall_Satisfaction__c'),
                'response_time': sv.get('ERS_Response_Time_Satisfaction__c'),
                'technician': sv.get('ERS_Technician_Satisfaction__c'),
                'kept_informed': sv.get('ERSSatisfaction_With_Being_Kept_Informed__c'),
                'comment': (sv.get('Customer_Comments__c') or '').strip() or None,
            })

        ops = _drv_ops.get(name, {'completed': 0, 'declined': 0, 'ata_vals': [],
                                  'completed_list': [], 'declined_list': []})
        drivers.append({
            'name': name,
            'survey_count': len(svs),
            'completed': ops['completed'],
            'declined': ops['declined'],
            'avg_ata': round(sum(ops['ata_vals']) / len(ops['ata_vals'])) if ops['ata_vals'] else None,
            'overall_pct': _totally_satisfied_pct(svs, 'ERS_Overall_Satisfaction__c'),
            'response_time_pct': _totally_satisfied_pct(svs, 'ERS_Response_Time_Satisfaction__c'),
            'technician_pct': d_tech_pct,
            'kept_informed_pct': _totally_satisfied_pct(svs, 'ERSSatisfaction_With_Being_Kept_Informed__c'),
            'surveys': survey_details,
        })

    # Overall SA stats (all SAs combined)
    overall_sa_stats = _sa_stats(sas)

    import database as _db
    result = {
        'territory_id': territory_id,
        'start_date': start_date,
        'end_date': end_date,
        'garage_type': 'fleet' if _is_fleet else 'contractor',
        'bonus_tiers': _db.get_bonus_tiers(),
        'garage_summary': {
            'overall_pct': overall_pct,
            'response_time_pct': rt_pct,
            'technician_pct': tech_pct,
            'kept_informed_pct': informed_pct,
            'total_surveys': len(surveys),
            'total_sas': len(sas),
            'total_completed': total_completed,
            'bonus_tier': bonus_tier,
            'bonus_per_sa': bonus_per_sa,
            'total_bonus': total_bonus,
            **overall_sa_stats,
        },
        'primary_vs_secondary': {
            'overall': {
                **_group_scores(surveys, overall_sa_stats),
            },
            'primary': _group_scores(primary_surveys, primary_sa_stats),
            'secondary': _group_scores(secondary_surveys, secondary_sa_stats),
        },
        'drivers': drivers,
        'ai_summary': None,  # loaded async via separate endpoint
        # Internal: SA lists per driver for lazy drill-down endpoint (not sent to frontend)
        '_sa_driver_map': {name: {'completed_list': ops.get('completed_list', []),
                                   'declined_list': ops.get('declined_list', [])}
                           for name, ops in _drv_ops.items()},
    }

    return result


@router.get("/api/garages/{territory_id}/performance-scorecard/ai-summary")
def api_garage_ai_summary(
    territory_id: str,
    start_date: str = Query(None),
    end_date: str = Query(None),
):
    """Generate AI executive summary for garage performance."""
    territory_id = sanitize_soql(territory_id)
    today = _date.today()
    if not start_date:
        start_date = today.replace(day=1).isoformat()
    if not end_date:
        end_date = today.isoformat()

    cache_key = f'garage_ai_summary_v3_{territory_id}_{start_date}_{end_date}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Get the scorecard data first
    scorecard = api_garage_performance_scorecard(territory_id, start_date, end_date)
    gs = scorecard['garage_summary']
    drivers = scorecard['drivers']
    ps_p = scorecard['primary_vs_secondary']['primary']
    ps_s = scorecard['primary_vs_secondary']['secondary']

    if not drivers:
        return {'summary': 'No survey data available for this period.'}

    garage_type = scorecard.get('garage_type', 'contractor')
    is_fleet = garage_type == 'fleet'
    total_declined = gs.get('declined', 0)
    decline_rate = round(100 * total_declined / max(gs.get('total_sas', 1), 1), 1)

    # Build driver lines with operational + satisfaction data
    driver_lines = []
    drivers_with_declines = []
    for d in drivers[:15]:
        parts = [f"  {d['name']}: {d.get('completed', 0)} completed, {d.get('declined', 0)} declined"]
        if d.get('avg_ata') is not None:
            parts.append(f"ATA={d['avg_ata']}m")
        parts.append(f"{d['survey_count']} surveys, Overall={d['overall_pct']}%, Tech={d['technician_pct']}%")
        driver_lines.append(', '.join(parts))
        if (d.get('declined') or 0) > 0:
            drivers_with_declines.append(d)

    # Decline section
    decline_section = f"\nDECLINE ANALYSIS:\n- Total declined: {total_declined} ({decline_rate}% of {gs.get('total_sas', 0)} SAs)\n"
    if is_fleet:
        decline_section += "- This is a FLEET garage (on-platform). Declines are tracked per DRIVER.\n"
        if drivers_with_declines:
            decline_section += "- Drivers with declines:\n"
            for d in sorted(drivers_with_declines, key=lambda x: -(x.get('declined') or 0)):
                d_rate = round(100 * d['declined'] / max(d.get('completed', 0) + d['declined'], 1), 1)
                decline_section += f"    {d['name']}: {d['declined']} declined out of {d.get('completed',0) + d['declined']} ({d_rate}%)\n"
        else:
            decline_section += "- No individual driver declines recorded.\n"
    else:
        decline_section += "- This is a TOWBOOK/contractor garage (off-platform). Declines are FACILITY-level, not individual driver decisions.\n"
        if total_declined > 0:
            decline_section += f"- The facility declined {total_declined} calls — investigate capacity, hours of operation, or dispatch routing issues.\n"

    prompt = f"""Analyze this garage performance scorecard for {start_date} to {end_date}:

GARAGE TYPE: {'Fleet (on-platform)' if is_fleet else 'Contractor/Towbook (off-platform)'}

GARAGE SCORES (Totally Satisfied %):
- Overall: {gs['overall_pct']}% ({gs['total_surveys']} surveys, {gs['total_completed']} completed SAs)
- Response Time: {gs['response_time_pct']}%
- Technician: {gs['technician_pct']}%
- Kept Informed: {gs['kept_informed_pct']}%

GARAGE-LEVEL BONUS:
- Bonus is based on the GARAGE's overall Technician satisfaction score (not per-driver).
- Tiers: ≥98% = $4/SA, ≥96% = $3/SA, ≥94% = $2/SA, ≥92% = $1/SA, <92% = $0.
- This garage: Tech {gs['technician_pct']}% → {gs['bonus_tier']} tier → ${gs['bonus_per_sa']}/SA × {gs['total_completed']} completed SAs = ${gs['total_bonus']} total bonus.
{decline_section}
PRIMARY vs SECONDARY:
- Primary (first assigned): {ps_p.get('total_sas',0)} SAs, {ps_p.get('completed',0)} completed, {ps_p.get('declined',0)} declined, ATA={ps_p.get('avg_ata','N/A')}m, PTA hit={ps_p.get('pta_hit_pct','N/A')}%, {ps_p.get('survey_count',0)} surveys, Tech={ps_p.get('technician_pct')}%
- Secondary (reassigned here): {ps_s.get('total_sas',0)} SAs, {ps_s.get('completed',0)} completed, {ps_s.get('declined',0)} declined, ATA={ps_s.get('avg_ata','N/A')}m, PTA hit={ps_s.get('pta_hit_pct','N/A')}%, {ps_s.get('survey_count',0)} surveys, Tech={ps_s.get('technician_pct')}%

DRIVER BREAKDOWN:
{chr(10).join(driver_lines)}

Write a 3-4 paragraph executive summary:
1. Overall performance — cite the 4 satisfaction scores and operational stats (completed, ATA). Note strengths and weaknesses.
2. Decline analysis — state the decline rate ({decline_rate}%). {'Name the specific DRIVERS declining the most calls and their decline rates.' if is_fleet else 'This is a facility-level decline pattern — recommend investigating capacity or hours.'} Are declines concentrated on primary or secondary calls?
3. Bonus analysis — state the garage-level bonus calculation. Which drivers have the highest/lowest tech scores and are dragging the average?
4. Specific action items — focus on the weakest areas (high ATA, high declines, low satisfaction categories)."""

    provider, api_key, model = _load_ai_settings()
    if not api_key:
        return {'summary': 'AI not configured. Go to Admin → AI Assistant to set up.'}

    summary = _call_openai(api_key, model, prompt)
    result = {'summary': summary or 'Failed to generate summary.'}
    cache.put(cache_key, result, ttl=7200)
    return result


@router.get("/api/garages/{territory_id}/driver-sas")
def api_driver_sas(
    territory_id: str,
    driver_name: str = Query(...),
    sa_type: str = Query('completed', description="completed or declined"),
    start_date: str = Query(None),
    end_date: str = Query(None),
):
    """Lazy-fetch SA list for a driver drill-down. Fast: reads from cached scorecard."""
    territory_id = sanitize_soql(territory_id)
    today = _date.today()
    if not start_date:
        start_date = today.replace(day=1).isoformat()
    if not end_date:
        end_date = today.isoformat()

    cache_key = f'garage_perf_scorecard_{territory_id}_{start_date}_{end_date}'
    scorecard = cache.get(cache_key) or cache.disk_get(cache_key, ttl=172800)
    if not scorecard:
        # Compute fresh if not cached
        scorecard = _build_scorecard(territory_id, start_date, end_date)

    # Find the driver's ops data from _drv_ops (stored during build)
    # Rebuild from the SA data in the scorecard — fast, no SF query
    sas = scorecard.get('_sa_driver_map', {}).get(driver_name, {})
    return {'driver': driver_name, 'type': sa_type, 'items': sas.get(f'{sa_type}_list', [])}
