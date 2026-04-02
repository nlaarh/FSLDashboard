"""Garage Performance Scorecard — satisfaction scores, bonus calculation, driver breakdown."""

import os
import logging
import requests as _requests
from datetime import date as _date
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from sf_client import sf_query_all, sf_parallel, sanitize_soql
from utils import parse_dt as _parse_dt, is_fleet_territory
import cache

router = APIRouter()
log = logging.getLogger('garages_scorecard')

_SETTINGS_FILE = os.path.expanduser('~/.fslapp/settings.json')

def _bonus_for_pct(pct):
    """Return (bonus_per_sa, tier_label) — reads configurable tiers from SQLite."""
    import database
    return database.bonus_for_pct(pct)


def _totally_satisfied_pct(rows, field):
    """Calculate Totally Satisfied % from a list of survey rows."""
    total = sum(1 for r in rows if r.get(field))
    if total == 0:
        return None
    ts = sum(1 for r in rows if (r.get(field) or '').lower() == 'totally satisfied')
    return round(100 * ts / total)


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
    today = _date.today()
    if not start_date:
        start_date = today.replace(day=1).isoformat()
    if not end_date:
        end_date = today.isoformat()

    cache_key = f'garage_perf_scorecard_{territory_id}_{start_date}_{end_date}'

    def _compute():
        return _build_scorecard(territory_id, start_date, end_date)

    return cache.cached_query_persistent(cache_key, _compute, max_stale_hours=26)


def _build_scorecard(territory_id: str, start_date: str, end_date: str) -> dict:
    """Heavy computation — called only on cache miss."""
    start_utc = f"{start_date}T00:00:00Z"
    end_utc = f"{end_date}T23:59:59Z"

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
        """)

    def _get_woli():
        """Map WOLI → WO in one query (replaces sequential chunked batches)."""
        return sf_query_all(f"""
            SELECT Id, WorkOrderId
            FROM WorkOrderLineItem
            WHERE WorkOrder.ServiceTerritoryId = '{territory_id}'
              AND WorkOrder.CreatedDate >= {start_utc}
              AND WorkOrder.CreatedDate < {end_utc}
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

        drivers.append({
            'name': name,
            'survey_count': len(svs),
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

    cache_key = f'garage_ai_summary_v2_{territory_id}_{start_date}_{end_date}'
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

    # Build prompt
    driver_lines = []
    for d in drivers[:15]:  # top 15 drivers
        driver_lines.append(
            f"  {d['name']}: {d['survey_count']} surveys, "
            f"Overall={d['overall_pct']}%, Tech={d['technician_pct']}%, "
            f"ResponseTime={d['response_time_pct']}%, Informed={d['kept_informed_pct']}%"
        )

    prompt = f"""Analyze this garage performance scorecard for {start_date} to {end_date}:

GARAGE SCORES (Totally Satisfied %):
- Overall: {gs['overall_pct']}% ({gs['total_surveys']} surveys, {gs['total_completed']} completed SAs)
- Response Time: {gs['response_time_pct']}%
- Technician: {gs['technician_pct']}%
- Kept Informed: {gs['kept_informed_pct']}%

GARAGE-LEVEL BONUS:
- Bonus is based on the GARAGE's overall Technician satisfaction score (not per-driver).
- Tiers: ≥98% = $4/SA, ≥96% = $3/SA, ≥94% = $2/SA, ≥92% = $1/SA, <92% = $0.
- This garage: Tech {gs['technician_pct']}% → {gs['bonus_tier']} tier → ${gs['bonus_per_sa']}/SA × {gs['total_completed']} completed SAs = ${gs['total_bonus']} total bonus.

PRIMARY vs SECONDARY:
- Primary (first assigned): {ps_p.get('total_sas',0)} SAs, {ps_p.get('completed',0)} completed, {ps_p.get('declined',0)} declined, ATA={ps_p.get('avg_ata','N/A')}m, PTA hit={ps_p.get('pta_hit_pct','N/A')}%, {ps_p.get('survey_count',0)} surveys, Tech={ps_p.get('technician_pct')}%
- Secondary (reassigned here): {ps_s.get('total_sas',0)} SAs, {ps_s.get('completed',0)} completed, {ps_s.get('declined',0)} declined, ATA={ps_s.get('avg_ata','N/A')}m, PTA hit={ps_s.get('pta_hit_pct','N/A')}%, {ps_s.get('survey_count',0)} surveys, Tech={ps_s.get('technician_pct')}%

DRIVER BREAKDOWN:
{chr(10).join(driver_lines)}

Write a 3-4 paragraph executive summary:
1. Overall performance assessment — cite the 4 satisfaction scores. Note which are strong and which need improvement.
2. Bonus analysis — state the garage-level bonus calculation. Which drivers have the highest/lowest tech scores?
3. Which drivers are underperforming (tech score <92%) and dragging the garage average down? Name them with scores.
4. Specific action items to improve — focus on the weakest satisfaction categories (response time, kept informed, etc.)."""

    provider, api_key, model = _load_ai_settings()
    if not api_key:
        return {'summary': 'AI not configured. Go to Admin → AI Assistant to set up.'}

    summary = _call_openai(api_key, model, prompt)
    result = {'summary': summary or 'Failed to generate summary.'}
    cache.put(cache_key, result, ttl=7200)
    return result


