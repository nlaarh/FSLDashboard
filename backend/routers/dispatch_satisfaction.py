"""Satisfaction score analysis endpoints."""

from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from utils import parse_dt as _parse_dt
from sf_client import sf_query_all, sf_parallel, sanitize_soql
import cache

from routers.dispatch_shared import _ET, _today_start_utc, _fmt_et, _sa_row, _is_real_garage

router = APIRouter()


# ── Satisfaction Score Analysis ──────────────────────────────────────────────

def _satisfaction_insights(sat_pct, avg_ata, pta_miss_pct, rt_sat_pct, volume):
    """Rule-based insights for satisfaction data. Returns list of insight dicts."""
    insights = []
    if volume is not None and volume < 5:
        insights.append({'type': 'caution', 'text': 'Small sample size — interpret with caution', 'icon': '⚠'})
        return insights  # Don't generate other insights on tiny samples
    if sat_pct is not None and sat_pct < 60:
        insights.append({'type': 'critical', 'text': f'Critical: {sat_pct}% satisfaction — investigate individual comments', 'icon': '🔴'})
    if avg_ata is not None and sat_pct is not None and avg_ata > 45 and sat_pct < 80:
        insights.append({'type': 'warning', 'text': f'High ATA ({avg_ata}m) likely driving low satisfaction ({sat_pct}%)', 'icon': '🕐'})
    if pta_miss_pct is not None and pta_miss_pct > 30 and sat_pct is not None and sat_pct < 80:
        insights.append({'type': 'warning', 'text': f'Broken promises damaging satisfaction — {pta_miss_pct}% PTA violations', 'icon': '💔'})
    if rt_sat_pct is not None and sat_pct is not None and rt_sat_pct < sat_pct - 10:
        insights.append({'type': 'info', 'text': f'Wait time is the pain point — response time satisfaction ({rt_sat_pct}%) trails overall ({sat_pct}%)', 'icon': '⏱'})
    elif rt_sat_pct is not None and sat_pct is not None and rt_sat_pct >= sat_pct and sat_pct < 75:
        insights.append({'type': 'info', 'text': 'Response time OK but overall low — issue may be technician quality or communication', 'icon': '🔧'})
    if sat_pct is not None and sat_pct >= 90:
        insights.append({'type': 'success', 'text': f'Excellent performance — {sat_pct}% totally satisfied', 'icon': '🌟'})
    return insights


def _build_executive_insight(month, sat_pct, rt_pct, tech_pct, total_surveys,
                              avg_ata, pta_miss_pct, daily_trend, all_garages):
    """VP monthly briefing — 5-8 lines, bottom line up front.

    Not a data dump. A concise analysis: what happened, why, who's responsible, what to do.
    """
    import calendar
    from datetime import date as _date

    year, mon = int(month[:4]), int(month[5:7])
    month_name = calendar.month_name[mon]
    target = 82

    if sat_pct is None or total_surveys == 0:
        return {'headline': f'No satisfaction data for {month_name} {year}.', 'body': [], 'actions': []}

    # Classify garages
    bad_garages = sorted(
        [g for g in all_garages if g['totally_satisfied_pct'] is not None
         and g['totally_satisfied_pct'] < target and g['surveys'] >= 5],
        key=lambda g: g['totally_satisfied_pct']
    )
    good_count = sum(1 for g in all_garages
                     if g['totally_satisfied_pct'] is not None and g['totally_satisfied_pct'] >= target)
    total_garages = len([g for g in all_garages if g['surveys'] >= 2])

    # Diagnose: wait time vs driver quality
    if rt_pct is not None and tech_pct is not None:
        if rt_pct < target and tech_pct >= target:
            diagnosis = 'wait_time'
        elif tech_pct < target and rt_pct >= target:
            diagnosis = 'technician'
        elif rt_pct < target and tech_pct < target:
            diagnosis = 'both'
        else:
            diagnosis = 'on_target'
    else:
        diagnosis = None

    # Month-over-month
    prev_month_data = _get_previous_month_sat(month)
    prev_pct = prev_month_data.get('totally_satisfied_pct') if prev_month_data else None
    prev_name = prev_month_data.get('month_name', 'last month') if prev_month_data else None

    # Worst days
    bad_days = sorted(
        [d for d in daily_trend
         if d.get('totally_satisfied_pct') is not None and d['totally_satisfied_pct'] < target
         and d.get('surveys', 0) >= 10],
        key=lambda d: d['totally_satisfied_pct']
    )

    # ── Build the briefing (5-8 lines) ──
    body = []

    # Line 1: Headline with trend context
    if sat_pct >= target:
        trend_ctx = ''
        if prev_pct is not None:
            delta = sat_pct - prev_pct
            if delta > 0:
                trend_ctx = f', up {delta} from {prev_name}'
            elif delta < 0:
                trend_ctx = f', down {abs(delta)} from {prev_name}'
        risk = ''
        if diagnosis == 'wait_time':
            risk = ' Response time is the risk.'
        elif diagnosis == 'technician':
            risk = ' Driver quality is the risk.'
        body.append(f"On target at {sat_pct}%{trend_ctx}.{risk}")
    else:
        gap = target - sat_pct
        body.append(f"{gap} {'point' if gap == 1 else 'points'} below target at {sat_pct}%.")

    # Line 2: Root cause — one sentence
    if diagnosis == 'wait_time':
        body.append(f"Technician quality is strong ({tech_pct}%), but members are unhappy with wait times — Response Time satisfaction is only {rt_pct}%.")
    elif diagnosis == 'technician':
        body.append(f"Wait times are acceptable ({rt_pct}% RT satisfaction), but driver quality is the problem — Technician satisfaction is {tech_pct}%.")
    elif diagnosis == 'both':
        body.append(f"Both wait times ({rt_pct}% RT) and driver quality ({tech_pct}% Tech) are below target.")

    # Line 3: ATA + PTA — the operational evidence
    ata_pta_parts = []
    if avg_ata and avg_ata > 45:
        ata_pta_parts.append(f"average response was {avg_ata} minutes")
    if pta_miss_pct and pta_miss_pct > 15:
        ata_pta_parts.append(f"{pta_miss_pct}% of calls missed their promised arrival time")
    if ata_pta_parts:
        body.append(f"{' and '.join(ata_pta_parts).capitalize()} — these broken promises drive the most dissatisfied surveys.")

    # Line 4: Who's responsible — specific facilities
    if bad_garages:
        bottom = bad_garages[:3]
        garage_details = []
        for g in bottom:
            name = g['name'].split(' - ')[-1].strip() if ' - ' in g['name'] else g['name']
            garage_details.append(f"{name} ({g['totally_satisfied_pct']}%)")
        body.append(f"Three facilities account for most of the damage: {', '.join(garage_details)}. The remaining {good_count} garages are performing above target.")

    # Line 5: Worst days (brief)
    if bad_days:
        day_strs = []
        for d in bad_days[:3]:
            day_num = d['date'].split('-')[-1].lstrip('0')
            day_strs.append(f"{month_name} {day_num} ({d['totally_satisfied_pct']}%)")
        body.append(f"Worst days: {', '.join(day_strs)} — click any day above to see what went wrong.")

    # ── Actions (1-2 lines) ──
    actions = []
    if bad_garages:
        names = ', '.join(g['name'].split(' - ')[-1].strip() for g in bad_garages[:3])
        if diagnosis == 'wait_time':
            actions.append(f"Capacity review at {names} — are they taking more calls than they can handle?")
        elif diagnosis == 'technician':
            actions.append(f"Driver quality review at {names} — check customer comments for patterns.")
        else:
            actions.append(f"Review operations at {names}.")

    if pta_miss_pct and pta_miss_pct > 25:
        actions.append(f"PTA promises need recalibration — {pta_miss_pct}% miss rate means we're over-promising on arrival times.")

    if not actions:
        actions.append("On track. Monitor response times to maintain margin above 82%.")

    return {
        'headline': f"{month_name} {year}: {sat_pct}% — {'on target' if sat_pct >= target else f'{target - sat_pct} below target'}.",
        'body': body,
        'actions': actions,
        'diagnosis': diagnosis,
    }


def _build_zone_satisfaction(all_garages, matrix):
    """Map each zone to its primary garage's satisfaction score.

    Returns: {zone_territory_id: {garage_name, sat_pct, surveys, avg_ata, tier}}
    The frontend uses zone_territory_id to match against GeoJSON feature territory_id.
    """
    # Build garage satisfaction lookup: garage_name → data
    garage_by_name = {g['name']: g for g in all_garages}

    # Build garage ID → name from the priority matrix + garage list
    # We need to resolve spotted_territory_id → garage name
    # The garage list has (id, name) — fetch it from ops garages cache
    garage_id_to_name = {}
    try:
        from ops import get_ops_garages
        ops_garages = get_ops_garages()
        for g in ops_garages:
            garage_id_to_name[g['id']] = g['name']
    except Exception:
        pass

    # For each zone (parent_territory_id), find rank-1 garage
    zone_sat = {}
    rank_lookup = matrix.get('rank_lookup', {})
    by_parent = {}
    for (parent_id, spotted_id), rank in rank_lookup.items():
        if rank == 1:  # Primary garage
            by_parent[parent_id] = spotted_id

    for zone_id, garage_id in by_parent.items():
        garage_name = garage_id_to_name.get(garage_id, '')
        g = garage_by_name.get(garage_name)
        if g:
            zone_sat[zone_id] = {
                'garage_name': garage_name,
                'sat_pct': g.get('totally_satisfied_pct'),
                'surveys': g.get('surveys', 0),
                'avg_ata': g.get('avg_ata'),
                'tier': g.get('tier'),
            }
        else:
            zone_sat[zone_id] = {
                'garage_name': garage_name,
                'sat_pct': None,
                'surveys': 0,
                'avg_ata': None,
                'tier': None,
            }

    return zone_sat


def _get_previous_month_sat(current_month):
    """Get previous month's satisfaction % from disk cache (no extra SF query)."""
    import calendar
    year, mon = int(current_month[:4]), int(current_month[5:7])
    if mon == 1:
        prev_year, prev_mon = year - 1, 12
    else:
        prev_year, prev_mon = year, mon - 1
    prev_key = f'satisfaction_overview_{prev_year}-{prev_mon:02d}'
    prev_data = cache.disk_get_stale(prev_key)
    if prev_data and prev_data.get('summary', {}).get('totally_satisfied_pct') is not None:
        return {
            'totally_satisfied_pct': prev_data['summary']['totally_satisfied_pct'],
            'month_name': calendar.month_name[prev_mon],
        }
    return None


# Satisfaction generation uses filesystem locks (cross-worker safe)


@router.get("/api/insights/satisfaction/overview")
def api_satisfaction_overview(month: str = Query(..., description="YYYY-MM format, e.g. 2026-03")):
    """Satisfaction overview: summary cards, daily trend, and garage ranking for a month.

    Non-blocking: serves from cache. If no cache, triggers background generation.
    """
    import re, calendar, logging, threading
    from datetime import date as _date

    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format (e.g. 2026-03)")
    year, mon = int(month[:4]), int(month[5:7])
    today = _date.today()
    if _date(year, mon, 1) > today:
        raise HTTPException(400, "Cannot fetch future months")

    is_current = (year == today.year and mon == today.month)
    cache_key = f'satisfaction_overview_{month}'
    ttl = 43200 if is_current else 31536000  # 12h current, 1yr past

    cached = cache.get(cache_key)
    if cached:
        return cached
    disk = cache.disk_get(cache_key, ttl=ttl)
    if disk:
        cache.put(cache_key, disk, ttl)
        return disk

    _log = logging.getLogger('satisfaction')
    gen_lock = f'gen_sat_overview_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=1800):
        def _bg():
            try:
                result = _generate_satisfaction_overview(month)
                cache.put(cache_key, result, ttl)
                cache.disk_put(cache_key, result, ttl)
                _log.info(f"Satisfaction overview for {month} generated.")
            except Exception as e:
                import traceback
                _log.warning(f"Satisfaction overview generation failed for {month}: {e}\n{traceback.format_exc()}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()
        _log.info(f"Satisfaction overview background generation started for {month}")

    return {'month': month, 'summary': {}, 'daily_trend': [], 'all_garages': [], 'loading': True}


@router.get("/api/insights/satisfaction/refresh")
def api_satisfaction_refresh(month: str = Query(..., description="YYYY-MM format")):
    """Force-refresh satisfaction overview for a month. Clears cache and regenerates."""
    import re, threading, logging
    from datetime import date as _date

    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format")

    _log = logging.getLogger('satisfaction')
    cache_key = f'satisfaction_overview_{month}'

    # Clear both L1 and L2 cache
    cache.invalidate(cache_key)
    cache.disk_invalidate(cache_key)

    # Trigger background regeneration
    gen_lock = f'gen_sat_overview_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=1800):
        year, mon = int(month[:4]), int(month[5:7])
        today = _date.today()
        is_current = (year == today.year and mon == today.month)
        ttl = 43200 if is_current else 31536000

        def _bg():
            try:
                result = _generate_satisfaction_overview(month)
                cache.put(cache_key, result, ttl)
                cache.disk_put(cache_key, result, ttl)
                _log.info(f"Satisfaction refresh complete for {month}")
            except Exception as e:
                _log.warning(f"Satisfaction refresh failed for {month}: {e}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()

    return {'status': 'refreshing', 'month': month}


def _generate_satisfaction_overview(month: str):
    """Heavy lifting for satisfaction overview — runs in background thread."""
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

    # ── Attribution: by CALL DATE (ERS_Work_Order__r.CreatedDate) not survey date ──
    # A survey submitted March 7 about a Feb 28 call is attributed to Feb 28.
    # This aligns satisfaction with same-day ATA/PTA for accurate correlation.

    # ── Batch 1: All 4 survey queries in parallel (same object, different GROUP BYs) ──
    batch1 = sf_parallel(
        daily_sat=lambda: sf_query_all(f"""
            SELECT DAY_ONLY(ERS_Work_Order__r.CreatedDate) d,
                   ERS_Overall_Satisfaction__c sat,
                   COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
            GROUP BY DAY_ONLY(ERS_Work_Order__r.CreatedDate), ERS_Overall_Satisfaction__c
        """),
        garage_overall=lambda: sf_query_all(f"""
            SELECT ERS_Work_Order__r.ServiceTerritory.Name tname,
                   ERS_Overall_Satisfaction__c sat,
                   COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
              AND ERS_Work_Order__r.ServiceTerritoryId != null
            GROUP BY ERS_Work_Order__r.ServiceTerritory.Name, ERS_Overall_Satisfaction__c
            ORDER BY ERS_Work_Order__r.ServiceTerritory.Name
        """),
        garage_rt=lambda: sf_query_all(f"""
            SELECT ERS_Work_Order__r.ServiceTerritory.Name tname,
                   ERS_Response_Time_Satisfaction__c sat,
                   COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Response_Time_Satisfaction__c != null
              AND ERS_Work_Order__r.ServiceTerritoryId != null
            GROUP BY ERS_Work_Order__r.ServiceTerritory.Name, ERS_Response_Time_Satisfaction__c
            ORDER BY ERS_Work_Order__r.ServiceTerritory.Name
        """),
        garage_tech=lambda: sf_query_all(f"""
            SELECT ERS_Work_Order__r.ServiceTerritory.Name tname,
                   ERS_Technician_Satisfaction__c sat,
                   COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Technician_Satisfaction__c != null
              AND ERS_Work_Order__r.ServiceTerritoryId != null
            GROUP BY ERS_Work_Order__r.ServiceTerritory.Name, ERS_Technician_Satisfaction__c
            ORDER BY ERS_Work_Order__r.ServiceTerritory.Name
        """),
        sa_volume=lambda: sf_query_all(f"""
            SELECT DAY_ONLY(CreatedDate) d, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritoryId != null
              AND RecordType.Name = 'ERS Service Appointment'
            GROUP BY DAY_ONLY(CreatedDate)
        """),
        completed=lambda: sf_query_all(f"""
            SELECT Id, CreatedDate, Status, ActualStartTime,
                   ERS_Dispatch_Method__c, ERS_PTA__c, WorkType.Name
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritoryId != null
              AND RecordType.Name = 'ERS Service Appointment'
              AND Status = 'Completed'
              AND WorkType.Name != 'Tow Drop-Off'
        """),
    )
    daily_sat = batch1['daily_sat']
    garage_overall = batch1['garage_overall']
    garage_rt = batch1['garage_rt']
    garage_tech = batch1['garage_tech']
    sa_vol_by_day = {}
    for r in batch1['sa_volume']:
        sa_vol_by_day[r.get('d', '')] = r.get('cnt', 0) or 0
    completed_sas = batch1['completed']

    # Query 7: Towbook on-location times for accurate ATA
    # Instead of 141 sequential ID-chunk queries, use cross-object filter by week in parallel.
    # Each weekly query returns all Towbook Status history — filter 'On Location' in Python.
    towbook_on_location = {}
    has_towbook = any((sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook' for sa in completed_sas)
    if has_towbook:
        # Build weekly date ranges for the month
        from datetime import timedelta as _td2
        week_ranges = []
        ws = first_day
        while ws < end_day:
            we = min(ws + _td2(days=7), end_day)
            week_ranges.append((
                f"{ws.isoformat()}T00:00:00Z",
                f"{we.isoformat()}T00:00:00Z",
            ))
            ws = we

        def _make_week_fn(w_start, w_end):
            return lambda: sf_query_all(f"""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE Field = 'Status'
                  AND ServiceAppointment.CreatedDate >= {w_start}
                  AND ServiceAppointment.CreatedDate < {w_end}
                  AND ServiceAppointment.ERS_Dispatch_Method__c = 'Towbook'
                  AND ServiceAppointment.Status = 'Completed'
                  AND ServiceAppointment.ServiceTerritoryId != null
                  AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
                  AND ServiceAppointment.WorkType.Name != 'Tow Drop-Off'
            """)

        # Run all weeks in parallel (typically 4-5 queries)
        parallel_args = {f'w{i}': _make_week_fn(s, e) for i, (s, e) in enumerate(week_ranges)}
        week_results = sf_parallel(**parallel_args)
        for key, hist_rows in week_results.items():
            for r in hist_rows:
                if r.get('NewValue') != 'On Location':
                    continue
                sa_id = r.get('ServiceAppointmentId')
                ts = _parse_dt(r.get('CreatedDate'))
                if ts and (sa_id not in towbook_on_location or ts < towbook_on_location[sa_id]):
                    towbook_on_location[sa_id] = ts

    # ── Build daily ATA/PTA buckets ──
    day_ata = defaultdict(lambda: {'ata_sum': 0.0, 'ata_count': 0, 'pta_miss': 0, 'pta_eligible': 0})
    for sa in completed_sas:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        date_str = (sa.get('CreatedDate') or '')[:10]
        if not date_str:
            continue
        dm = sa.get('ERS_Dispatch_Method__c') or ''
        bucket = day_ata[date_str]

        # ATA calculation (same logic as garage-level)
        if dm == 'Field Services':
            created = _parse_dt(sa.get('CreatedDate'))
            actual = _parse_dt(sa.get('ActualStartTime'))
            if created and actual:
                diff = (actual - created).total_seconds() / 60
                if 0 < diff < 480:
                    bucket['ata_sum'] += diff
                    bucket['ata_count'] += 1
        elif dm == 'Towbook':
            on_loc = towbook_on_location.get(sa.get('Id'))
            if on_loc:
                created = _parse_dt(sa.get('CreatedDate'))
                if created:
                    diff = (on_loc - created).total_seconds() / 60
                    if 0 < diff < 480:
                        bucket['ata_sum'] += diff
                        bucket['ata_count'] += 1

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
                        bucket['pta_eligible'] += 1
                        if ata_min > pta_min:
                            bucket['pta_miss'] += 1

    # ── Assemble daily trend ──
    day_buckets = defaultdict(lambda: {'totally_satisfied': 0, 'satisfied': 0, 'total': 0})
    for r in daily_sat:
        d = r.get('d', '')
        sat_val = (r.get('sat') or '').strip().lower()
        cnt = r.get('cnt', 0) or 0
        if d and sat_val:
            day_buckets[d]['total'] += cnt
            if sat_val == 'totally satisfied':
                day_buckets[d]['totally_satisfied'] += cnt
            elif sat_val == 'satisfied':
                day_buckets[d]['satisfied'] += cnt

    # Days within last 7 days have incomplete survey data (surveys still arriving)
    incomplete_cutoff = (today - _td(days=7)).isoformat()

    all_trend_dates = sorted(set(list(day_buckets.keys()) + list(day_ata.keys())))
    daily_trend = []
    for d in all_trend_dates:
        b = day_buckets.get(d, {'totally_satisfied': 0, 'satisfied': 0, 'total': 0})
        a = day_ata.get(d, {'ata_sum': 0, 'ata_count': 0, 'pta_miss': 0, 'pta_eligible': 0})
        ts_pct = round(100 * b['totally_satisfied'] / b['total']) if b['total'] else None
        avg_ata = round(a['ata_sum'] / a['ata_count']) if a['ata_count'] else None
        pta_miss_pct = round(100 * a['pta_miss'] / a['pta_eligible']) if a['pta_eligible'] else None
        daily_trend.append({
            'date': d,
            'totally_satisfied_pct': ts_pct,
            'surveys': b['total'],
            'sa_volume': sa_vol_by_day.get(d, 0),
            'avg_ata': avg_ata,
            'pta_miss_pct': pta_miss_pct,
            'incomplete': d > incomplete_cutoff,  # surveys still arriving for recent days
        })

    # ── Assemble garage data ──
    def _agg_satisfaction(rows, field_name='sat'):
        """Aggregate satisfaction rows into {garage: {totally_satisfied, total, pct}}."""
        garages = defaultdict(lambda: {'totally_satisfied': 0, 'total': 0})
        for r in rows:
            tname = (r.get('tname') or
                     ((r.get('ERS_Work_Order__r') or {}).get('ServiceTerritory') or {}).get('Name', ''))
            if not _is_real_garage(tname):
                continue
            sat_val = (r.get(field_name) or '').strip().lower()
            cnt = r.get('cnt', 0) or 0
            if tname and sat_val:
                garages[tname]['total'] += cnt
                if sat_val == 'totally satisfied':
                    garages[tname]['totally_satisfied'] += cnt
        return garages

    overall = _agg_satisfaction(garage_overall)
    rt = _agg_satisfaction(garage_rt)
    tech = _agg_satisfaction(garage_tech)

    all_garages = []
    for name, o in overall.items():
        if o['total'] < 1:
            continue
        ts_pct = round(100 * o['totally_satisfied'] / o['total'])
        rt_info = rt.get(name, {'totally_satisfied': 0, 'total': 0})
        rt_pct = round(100 * rt_info['totally_satisfied'] / rt_info['total']) if rt_info['total'] else None
        tech_info = tech.get(name, {'totally_satisfied': 0, 'total': 0})
        tech_pct = round(100 * tech_info['totally_satisfied'] / tech_info['total']) if tech_info['total'] else None

        insights = _satisfaction_insights(ts_pct, None, None, rt_pct, o['total'])

        all_garages.append({
            'name': name,
            'totally_satisfied_pct': ts_pct,
            'response_time_pct': rt_pct,
            'technician_pct': tech_pct,
            'surveys': o['total'],
            'insights': insights,
        })

    all_garages.sort(key=lambda g: g['totally_satisfied_pct'], reverse=True)

    # Summary cards
    total_surveys = sum(b['total'] for b in day_buckets.values())
    total_ts = sum(b['totally_satisfied'] for b in day_buckets.values())

    # Overall response time & technician (flatten from garage-level)
    rt_total = sum(g['total'] for g in rt.values())
    rt_ts = sum(g['totally_satisfied'] for g in rt.values())
    tech_total = sum(g['total'] for g in tech.values())
    tech_ts = sum(g['totally_satisfied'] for g in tech.values())

    sat_pct = round(100 * total_ts / total_surveys) if total_surveys else None
    rt_pct = round(100 * rt_ts / rt_total) if rt_total else None
    tech_pct = round(100 * tech_ts / tech_total) if tech_total else None

    summary = {
        'totally_satisfied_pct': sat_pct,
        'response_time_pct': rt_pct,
        'technician_pct': tech_pct,
        'total_surveys': total_surveys,
    }

    # ── ATA / PTA aggregates for the executive insight ──
    total_ata_sum = sum(day_ata[d]['ata_sum'] for d in day_ata)
    total_ata_count = sum(day_ata[d]['ata_count'] for d in day_ata)
    total_pta_miss = sum(day_ata[d]['pta_miss'] for d in day_ata)
    total_pta_eligible = sum(day_ata[d]['pta_eligible'] for d in day_ata)
    avg_ata = round(total_ata_sum / total_ata_count) if total_ata_count else None
    pta_miss_pct = round(100 * total_pta_miss / total_pta_eligible) if total_pta_eligible else None

    # ── Executive Insight — auto-generated VP summary ──
    executive_insight = _build_executive_insight(
        month=month, sat_pct=sat_pct, rt_pct=rt_pct, tech_pct=tech_pct,
        total_surveys=total_surveys, avg_ata=avg_ata, pta_miss_pct=pta_miss_pct,
        daily_trend=daily_trend, all_garages=all_garages,
    )

    # ── Zone → garage satisfaction map (for geographic map visualization) ──
    from ops import _get_priority_matrix
    zone_sat = _build_zone_satisfaction(all_garages, _get_priority_matrix())

    return {
        'month': month,
        'summary': summary,
        'daily_trend': daily_trend,
        'all_garages': all_garages,
        'executive_insight': executive_insight,
        'zone_satisfaction': zone_sat,
    }


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

    # ── Query 1: All surveys for calls on this day (by call date, not survey date) ──
    surveys = sf_query_all(f"""
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
    """)
    _time.sleep(0.3)

    # ── Enrich surveys with SA details (Survey → WO → WOLI → SA) ──
    wo_ids = list(set(
        (sv.get('ERS_Work_Order__r') or {}).get('Id', '')
        for sv in surveys if (sv.get('ERS_Work_Order__r') or {}).get('Id')
    ))
    wo_to_sa = {}  # WO Id → SA details
    if wo_ids:
        # Step 1: WO IDs → WOLI IDs (batch 200)
        woli_to_wo = {}
        for i in range(0, len(wo_ids), 200):
            chunk = wo_ids[i:i+200]
            id_list = "','".join(chunk)
            wolis = sf_query_all(f"""
                SELECT Id, WorkOrderId
                FROM WorkOrderLineItem
                WHERE WorkOrderId IN ('{id_list}')
            """)
            for w in wolis:
                woli_to_wo[w['Id']] = w.get('WorkOrderId', '')
        _time.sleep(0.3)

        # Step 2: WOLI IDs → SAs
        woli_ids = list(woli_to_wo.keys())
        if woli_ids:
            for i in range(0, len(woli_ids), 200):
                chunk = woli_ids[i:i+200]
                id_list = "','".join(chunk)
                sa_rows = sf_query_all(f"""
                    SELECT Id, AppointmentNumber, CreatedDate, Status, ParentRecordId,
                           ERS_Assigned_Resource__r.Name,
                           ActualStartTime, ERS_Dispatch_Method__c
                    FROM ServiceAppointment
                    WHERE ParentRecordId IN ('{id_list}')
                      AND RecordType.Name = 'ERS Service Appointment'
                """)
                for sa in sa_rows:
                    woli_id = sa.get('ParentRecordId', '')
                    wo_id = woli_to_wo.get(woli_id, '')
                    if wo_id and wo_id not in wo_to_sa:
                        driver = (sa.get('ERS_Assigned_Resource__r') or {}).get('Name', '')
                        wo_to_sa[wo_id] = {
                            'sa_number': sa.get('AppointmentNumber', ''),
                            'call_date': (sa.get('CreatedDate') or '')[:10],
                            'status': sa.get('Status', ''),
                            'driver': driver,
                        }
            _time.sleep(0.3)

    # ── Query 2: All SAs created this day (performance picture) ──
    sas = sf_query_all(f"""
        SELECT Id, CreatedDate, Status, ActualStartTime,
               ERS_Dispatch_Method__c, ERS_PTA__c,
               ServiceTerritory.Name, WorkType.Name,
               ERS_Cancellation_Reason__c,
               AppointmentNumber
        FROM ServiceAppointment
        WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
          AND ServiceTerritoryId != null
          AND RecordType.Name = 'ERS Service Appointment'
    """)
    _time.sleep(0.3)

    # ── Query 3: Towbook on-location (for correct ATA) ──
    towbook_ids = [sa.get('Id') for sa in sas
                   if sa.get('Status') == 'Completed'
                   and (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook']
    towbook_on_loc = {}
    if towbook_ids:
        for i in range(0, len(towbook_ids), 200):
            chunk = towbook_ids[i:i+200]
            id_list = "','".join(chunk)
            hist = sf_query_all(f"""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId IN ('{id_list}')
                  AND Field = 'Status'
            """)
            for r in hist:
                if r.get('NewValue') != 'On Location':
                    continue
                sa_id = r.get('ServiceAppointmentId')
                ts = _parse_dt(r.get('CreatedDate'))
                if ts and (sa_id not in towbook_on_loc or ts < towbook_on_loc[sa_id]):
                    towbook_on_loc[sa_id] = ts

    # ── Aggregate surveys by garage ──
    garage_surveys = defaultdict(lambda: {
        'totally_satisfied': 0, 'satisfied': 0, 'dissatisfied': 0,
        'totally_dissatisfied': 0, 'neither': 0, 'total': 0,
    })
    total_ts, total_s, total_d, total_td, total_n = 0, 0, 0, 0, 0
    problem_surveys = []  # dissatisfied/totally dissatisfied with details

    for sv in surveys:
        garage = ((sv.get('ERS_Work_Order__r') or {}).get('ServiceTerritory') or {}).get('Name', '') or 'Unknown'
        sat_val = (sv.get('ERS_Overall_Satisfaction__c') or '').strip().lower()
        g = garage_surveys[garage]
        g['total'] += 1

        if sat_val == 'totally satisfied':
            g['totally_satisfied'] += 1
            total_ts += 1
        elif sat_val == 'satisfied':
            g['satisfied'] += 1
            total_s += 1
        elif sat_val == 'dissatisfied':
            g['dissatisfied'] += 1
            total_d += 1
        elif sat_val == 'totally dissatisfied':
            g['totally_dissatisfied'] += 1
            total_td += 1
        else:
            g['neither'] += 1
            total_n += 1

        # Collect problem surveys (dissatisfied or worse, OR has negative comment)
        if sat_val in ('dissatisfied', 'totally dissatisfied', 'neither satisfied nor dissatisfied'):
            wo_id = (sv.get('ERS_Work_Order__r') or {}).get('Id', '')
            sa_info = wo_to_sa.get(wo_id, {})
            problem_surveys.append({
                'garage': garage,
                'overall': sv.get('ERS_Overall_Satisfaction__c') or '',
                'response_time': sv.get('ERS_Response_Time_Satisfaction__c') or '',
                'technician': sv.get('ERS_Technician_Satisfaction__c') or '',
                'wo_number': sv.get('ERS_Work_Order_Number__c') or '',
                'comment': sv.get('Customer_Comments__c') or '',
                'sa_number': sa_info.get('sa_number', ''),
                'call_date': sa_info.get('call_date', ''),
                'driver': sa_info.get('driver', ''),
            })

    # ── Aggregate SAs by garage ──
    garage_ops = defaultdict(lambda: {
        'total': 0, 'completed': 0, 'cancelled': 0,
        'ata_sum': 0.0, 'ata_count': 0,
        'sla_hits': 0, 'sla_eligible': 0,
        'ata_under_30': 0, 'ata_30_45': 0, 'ata_45_60': 0, 'ata_over_60': 0,
    })
    cancel_reasons = defaultdict(int)
    long_ata_sas = []  # SAs with ATA > 60min

    for sa in sas:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        garage = (sa.get('ServiceTerritory') or {}).get('Name', '') or 'Unknown'
        g = garage_ops[garage]
        g['total'] += 1

        status = sa.get('Status') or ''
        if status == 'Completed':
            g['completed'] += 1
        if 'Cancel' in status:
            g['cancelled'] += 1
            reason = sa.get('ERS_Cancellation_Reason__c') or 'Unknown'
            cancel_reasons[reason] += 1

        # ATA calculation
        if status == 'Completed':
            dm = sa.get('ERS_Dispatch_Method__c') or ''
            created = _parse_dt(sa.get('CreatedDate'))
            arrival = None
            if dm == 'Field Services':
                arrival = _parse_dt(sa.get('ActualStartTime'))
            elif dm == 'Towbook':
                arrival = towbook_on_loc.get(sa.get('Id'))
            else:
                arrival = _parse_dt(sa.get('ActualStartTime'))

            if created and arrival:
                diff = (arrival - created).total_seconds() / 60
                if 0 < diff < 480:
                    g['ata_sum'] += diff
                    g['ata_count'] += 1
                    g['sla_eligible'] += 1
                    if diff <= 45:
                        g['sla_hits'] += 1
                    if diff < 30:
                        g['ata_under_30'] += 1
                    elif diff <= 45:
                        g['ata_30_45'] += 1
                    elif diff <= 60:
                        g['ata_45_60'] += 1
                    else:
                        g['ata_over_60'] += 1
                    if diff > 60:
                        long_ata_sas.append({
                            'number': sa.get('AppointmentNumber', ''),
                            'garage': garage,
                            'ata_min': round(diff),
                            'work_type': wt,
                            'dispatch_method': dm,
                        })

    # ── Build garage breakdown (with lat/lon from ops garages cache) ──
    from ops import get_ops_garages
    garage_locations = {}
    try:
        for g in get_ops_garages():
            if g.get('lat') and g.get('lon'):
                garage_locations[g['name']] = {'lat': g['lat'], 'lon': g['lon']}
    except Exception:
        pass

    all_garage_names = sorted(set(list(garage_surveys.keys()) + list(garage_ops.keys())))
    garage_breakdown = []
    for name in all_garage_names:
        if not _is_real_garage(name):
            continue
        sv = garage_surveys.get(name, {'totally_satisfied': 0, 'total': 0})
        ops = garage_ops.get(name, {'total': 0, 'completed': 0, 'cancelled': 0, 'ata_sum': 0, 'ata_count': 0, 'sla_hits': 0, 'sla_eligible': 0})
        ts_pct = round(100 * sv['totally_satisfied'] / sv['total']) if sv['total'] else None
        avg_ata = round(ops['ata_sum'] / ops['ata_count']) if ops['ata_count'] else None
        sla = round(100 * ops['sla_hits'] / ops['sla_eligible']) if ops['sla_eligible'] else None
        # Tier: Excellent >=90, OK >=82, Below >=60, Critical <60
        tier = ('excellent' if ts_pct is not None and ts_pct >= 90 else
                'ok' if ts_pct is not None and ts_pct >= 82 else
                'below' if ts_pct is not None and ts_pct >= 60 else
                'critical' if ts_pct is not None else None)
        loc = garage_locations.get(name, {})
        garage_breakdown.append({
            'name': name,
            'totally_satisfied_pct': ts_pct,
            'surveys': sv['total'],
            'dissatisfied': sv.get('dissatisfied', 0) + sv.get('totally_dissatisfied', 0),
            'sa_total': ops['total'],
            'sa_completed': ops['completed'],
            'sa_cancelled': ops['cancelled'],
            'avg_ata': avg_ata,
            'sla_pct': sla,
            'tier': tier,
            'lat': loc.get('lat'),
            'lon': loc.get('lon'),
        })
    # Sort: garages with low satisfaction first, then by volume
    garage_breakdown.sort(key=lambda g: (
        g['totally_satisfied_pct'] if g['totally_satisfied_pct'] is not None else 999,
        -(g['surveys'] or 0),
    ))

    # ── Summary stats ──
    total_surveys = sum(1 for _ in surveys)
    total_sas = sum(g['total'] for g in garage_ops.values())
    total_completed = sum(g['completed'] for g in garage_ops.values())
    total_cancelled = sum(g['cancelled'] for g in garage_ops.values())
    total_ata_sum = sum(g['ata_sum'] for g in garage_ops.values())
    total_ata_count = sum(g['ata_count'] for g in garage_ops.values())

    ts_pct = round(100 * total_ts / total_surveys) if total_surveys else None
    avg_ata = round(total_ata_sum / total_ata_count) if total_ata_count else None
    comp_pct = round(100 * total_completed / total_sas) if total_sas else None
    total_sla_hits = sum(g['sla_hits'] for g in garage_ops.values())
    total_sla_eligible = sum(g['sla_eligible'] for g in garage_ops.values())
    sla_pct = round(100 * total_sla_hits / total_sla_eligible) if total_sla_eligible else None
    total_ata_under_30 = sum(g['ata_under_30'] for g in garage_ops.values())
    total_ata_30_45 = sum(g['ata_30_45'] for g in garage_ops.values())
    total_ata_45_60 = sum(g['ata_45_60'] for g in garage_ops.values())
    total_ata_over_60 = sum(g['ata_over_60'] for g in garage_ops.values())

    # ── VP Briefing — Bottom Line Up Front ──
    # Analyze comments for themes, diagnose per-garage, write a real briefing
    insights = []
    target = 82
    dissat_count = total_d + total_td
    comments_with_text = [s for s in problem_surveys if s.get('comment')]

    # 1. Classify struggling garages
    struggling = [g for g in garage_breakdown
                  if g['totally_satisfied_pct'] is not None and g['totally_satisfied_pct'] < 70 and g['surveys'] >= 2]
    good_garages = [g for g in garage_breakdown
                    if g['totally_satisfied_pct'] is not None and g['totally_satisfied_pct'] >= 82 and g['surveys'] >= 2]

    # 2. Analyze comment themes
    theme_wait = 0      # long wait, hours, took forever
    theme_noshow = 0    # never showed, no one came, never received
    theme_comm = 0      # no communication, no update, no callback
    theme_quality = 0   # rude, unprofessional, wrong truck, refused
    theme_cancel = 0    # cancelled, gave up

    for sv in comments_with_text:
        c = (sv.get('comment') or '').lower()
        if any(w in c for w in ['hour', 'wait', 'took', 'long time', 'forever', 'stranded']):
            theme_wait += 1
        if any(w in c for w in ['never showed', 'no one came', 'never received', 'nobody', 'never got']):
            theme_noshow += 1
        if any(w in c for w in ['no communication', 'no update', 'no call', 'no follow', 'no notification', 'no status']):
            theme_comm += 1
        if any(w in c for w in ['rude', 'unprofessional', 'refused', 'wrong truck', 'condescend', 'smug', 'attitude']):
            theme_quality += 1
        if any(w in c for w in ['cancel', 'gave up', 'could not wait']):
            theme_cancel += 1

    # 3. Build garage-specific diagnoses
    garage_diagnoses = []
    for g in struggling[:3]:
        name = g['name'].split(' - ')[-1].strip() if ' - ' in g['name'] else g['name']
        ata = g.get('avg_ata')
        total = g.get('sa_total', 0)
        cancelled = g.get('sa_cancelled', 0)
        dissat = g.get('dissatisfied', 0)

        if ata and ata > 90:
            garage_diagnoses.append(f"{name} had {ata}-minute average wait times across {total} calls — severely overwhelmed")
        elif ata and ata > 60:
            garage_diagnoses.append(f"{name} averaged {ata}m response on {total} calls with {dissat} dissatisfied surveys")
        elif cancelled > 2:
            garage_diagnoses.append(f"{name} had {cancelled} cancellations out of {total} calls — members gave up waiting")
        elif dissat > 0:
            garage_diagnoses.append(f"{name} had {dissat} dissatisfied out of {g['surveys']} surveys ({g['totally_satisfied_pct']}%)")

    # 4. Build the briefing
    if ts_pct is not None and ts_pct < target:
        # ── BELOW TARGET ──
        gap = target - ts_pct

        # Headline
        pts = 'point' if gap == 1 else 'points'
        headline = f"{gap} {pts} below target. "
        if theme_wait > theme_quality and theme_wait > 0:
            headline += "Long wait times are the primary driver of dissatisfaction."
        elif theme_quality > theme_wait and theme_quality > 0:
            headline += "Driver quality and professionalism issues are driving dissatisfaction."
        elif theme_noshow > 0:
            headline += "Members reported service no-shows — calls dispatched but drivers never arrived."
        else:
            headline += f"{dissat_count} members reported dissatisfaction."

        insights.append({'type': 'critical', 'text': headline})

        # Garage details
        if garage_diagnoses:
            insights.append({
                'type': 'warning',
                'text': f"Facilities that drove the score down: {'. '.join(garage_diagnoses)}.",
            })

        # Comment themes
        themes = []
        if theme_wait > 0:
            themes.append(f"{theme_wait} members complained about long wait times")
        if theme_noshow > 0:
            themes.append(f"{theme_noshow} reported service never arrived")
        if theme_comm > 0:
            themes.append(f"{theme_comm} cited lack of communication or status updates")
        if theme_quality > 0:
            themes.append(f"{theme_quality} reported driver quality or professionalism issues")
        if themes:
            insights.append({
                'type': 'info',
                'text': f"Common themes from member feedback: {'; '.join(themes)}.",
            })

        # Network context
        if good_garages:
            insights.append({
                'type': 'info',
                'text': f"The problem was concentrated — {len(good_garages)} of {len(garage_breakdown)} garages met target. "
                        f"Corrective action should focus on the {len(struggling)} underperforming facilities.",
            })

    else:
        # ── MET TARGET ──
        # Even when meeting target, provide real analysis
        risks = []
        if struggling:
            garage_strs = [f"{g['name'].split(' - ')[-1].strip()} ({g['totally_satisfied_pct']}%)"
                           for g in struggling[:3]]
            risks.append(f"weak spots at {', '.join(garage_strs)}")
        if avg_ata and avg_ata > 50:
            risks.append(f"average response time at {avg_ata} minutes (above 45m SLA)")

        if risks and dissat_count > 0:
            insights.append({
                'type': 'warning' if len(risks) > 1 else 'success',
                'text': f"On target at {ts_pct}%, but with {', '.join(risks)}. "
                        f"The rest of the network ({len(good_garages)} garages) is performing well enough to compensate.",
            })

            # Garage details for struggling facilities
            if garage_diagnoses:
                insights.append({
                    'type': 'warning',
                    'text': f"Facilities needing attention: {'. '.join(garage_diagnoses)}.",
                })

            # Comment themes even when meeting target
            themes = []
            if theme_wait > 0:
                themes.append(f"{theme_wait} complained about wait times")
            if theme_quality > 0:
                themes.append(f"{theme_quality} reported driver quality issues")
            if theme_noshow > 0:
                themes.append(f"{theme_noshow} reported no-shows")
            if theme_comm > 0:
                themes.append(f"{theme_comm} cited poor communication")
            if themes:
                insights.append({
                    'type': 'info',
                    'text': f"From the {dissat_count} dissatisfied members: {'; '.join(themes)}. "
                            f"Address these to build margin above the 82% target.",
                })
        elif ts_pct and ts_pct >= 90:
            insights.append({
                'type': 'success',
                'text': f"Strong day — {ts_pct}% across {total_surveys} surveys with {avg_ata}m average response. "
                        f"Both speed and driver quality performing well across the network.",
            })
        else:
            insights.append({
                'type': 'success',
                'text': f"Steady performance at {ts_pct}%. No major issues identified.",
            })

    # Sort long ATA SAs by worst first
    long_ata_sas.sort(key=lambda x: -x['ata_min'])

    # Top cancel reasons
    top_cancels = sorted(cancel_reasons.items(), key=lambda x: -x[1])[:5]

    result = {
        'date': date,
        'summary': {
            'totally_satisfied_pct': ts_pct,
            'total_surveys': total_surveys,
            'dissatisfied_count': total_d + total_td,
            'neither_count': total_n,
            'satisfied_count': total_s,
            'totally_satisfied_count': total_ts,
            'avg_ata': avg_ata,
            'sla_pct': sla_pct,
            'sla_hits': total_sla_hits,
            'sla_eligible': total_sla_eligible,
            'ata_under_30': total_ata_under_30,
            'ata_30_45': total_ata_30_45,
            'ata_45_60': total_ata_45_60,
            'ata_over_60': total_ata_over_60,
            'total_sas': total_sas,
            'completed': total_completed,
            'completion_pct': comp_pct,
            'cancelled': total_cancelled,
        },
        'insights': insights,
        'garage_breakdown': garage_breakdown,
        'problem_surveys': problem_surveys[:30],  # cap at 30
        'long_ata_sas': long_ata_sas[:20],  # cap at 20
        'cancel_reasons': [{'reason': r, 'count': c} for r, c in top_cancels],
    }

    cache.put(cache_key, result, 7200)
    cache.disk_put(cache_key, result, 7200)
    return result
