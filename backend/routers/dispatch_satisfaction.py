"""Satisfaction score overview endpoint and generation logic."""

from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from sf_client import sf_query_all, sf_parallel
import cache

from routers.dispatch_shared import _is_real_garage
from routers.satisfaction_utils import (
    _satisfaction_insights,
    _build_executive_insight,
    _build_zone_satisfaction,
)

router = APIRouter()


# ── Satisfaction Score Overview ──────────────────────────────────────────────

@router.get("/api/insights/satisfaction/overview")
def api_satisfaction_overview(month: str = Query(..., description="YYYY-MM format, e.g. 2026-03")):
    """Satisfaction overview: summary cards, daily trend, and garage ranking for a month.

    Non-blocking: serves from cache. If no cache, triggers background generation.
    """
    import re, calendar, logging, threading
    from datetime import date as _date, timedelta

    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format (e.g. 2026-03)")
    year, mon = int(month[:4]), int(month[5:7])
    today = _date.today()
    if _date(year, mon, 1) > today:
        raise HTTPException(400, "Cannot fetch future months")

    is_current = (year == today.year and mon == today.month)
    is_previous = (today.replace(day=1) - timedelta(days=1)).month == mon and (today.replace(day=1) - timedelta(days=1)).year == year
    is_recent = is_current or is_previous  # surveys still arriving
    cache_key = f'satisfaction_overview_{month}'

    def _generate():
        # Quick check: zero surveys -> return empty immediately
        last_day_num = calendar.monthrange(year, mon)[1]
        end_day = _date(year, mon, last_day_num) + timedelta(days=1)
        if is_current:
            end_day = today
        start_utc = f"{_date(year, mon, 1).isoformat()}T00:00:00Z"
        end_utc = f"{end_day.isoformat()}T00:00:00Z"
        survey_count = sf_query_all(f"""
            SELECT COUNT(Id) cnt FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc}
              AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
        """)
        total = (survey_count[0].get('cnt', 0) or 0) if survey_count else 0
        if total == 0:
            return {
                'month': month, 'summary': {}, 'daily_trend': [],
                'all_garages': [], 'executive_insight': None,
                'zone_satisfaction': {}, 'generated': True,
            }
        return _generate_satisfaction_overview(month)

    # Recent months: auto-regenerate if data >26h old (nightly job missed)
    # Old months: never expire, serve from cache forever
    return cache.cached_query_persistent(
        cache_key, _generate,
        max_stale_hours=26 if is_recent else 0,
    )


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
        # Fleet ATA aggregates by day (lightweight — no Towbook history needed)
        fleet_ata=lambda: sf_query_all(f"""
            SELECT DAY_ONLY(CreatedDate) d,
                   AVG(ERS_PTA__c) avg_pta,
                   COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritoryId != null
              AND RecordType.Name = 'ERS Service Appointment'
              AND Status = 'Completed'
              AND WorkType.Name != 'Tow Drop-Off'
              AND ERS_Dispatch_Method__c = 'Field Services'
              AND ActualStartTime != null
            GROUP BY DAY_ONLY(CreatedDate)
        """),
    )
    daily_sat = batch1['daily_sat']
    garage_overall = batch1['garage_overall']
    garage_rt = batch1['garage_rt']
    garage_tech = batch1['garage_tech']
    sa_vol_by_day = {}
    for r in batch1['sa_volume']:
        sa_vol_by_day[r.get('d', '')] = r.get('cnt', 0) or 0

    # Build daily Fleet ATA from aggregate (no individual SA records needed)
    day_ata = {}
    for r in batch1.get('fleet_ata', []):
        d = r.get('d', '')
        if d:
            day_ata[d] = {
                'avg_pta': round(r.get('avg_pta') or 0) if r.get('avg_pta') else None,
                'cnt': r.get('cnt', 0),
            }

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

    all_trend_dates = sorted(set(list(day_buckets.keys()) + list(day_ata.keys()) + list(sa_vol_by_day.keys())))
    daily_trend = []
    for d in all_trend_dates:
        b = day_buckets.get(d, {'totally_satisfied': 0, 'satisfied': 0, 'total': 0})
        a = day_ata.get(d, {})
        ts_pct = round(100 * b['totally_satisfied'] / b['total']) if b['total'] else None
        avg_ata = a.get('avg_pta')  # Fleet avg PTA as proxy (aggregate, fast)
        pta_miss_pct = None  # PTA miss requires individual SA analysis — available per-garage
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

    # ── ATA / PTA aggregates for the executive insight (from Fleet aggregate) ──
    total_ata_count = sum(a.get('cnt', 0) for a in day_ata.values())
    avg_ata_vals = [a['avg_pta'] for a in day_ata.values() if a.get('avg_pta')]
    avg_ata = round(sum(avg_ata_vals) / len(avg_ata_vals)) if avg_ata_vals else None
    pta_miss_pct = None  # PTA miss detail available per-garage in Operations tab

    # ── Executive Insight — auto-generated VP summary ──
    executive_insight = _build_executive_insight(
        month=month, sat_pct=sat_pct, rt_pct=rt_pct, tech_pct=tech_pct,
        total_surveys=total_surveys, avg_ata=avg_ata, pta_miss_pct=pta_miss_pct,
        daily_trend=daily_trend, all_garages=all_garages,
    )

    # ── Zone -> garage satisfaction map (for geographic map visualization) ──
    from ops import _get_priority_matrix
    zone_sat = _build_zone_satisfaction(all_garages, _get_priority_matrix())

    return {
        'month': month,
        'summary': summary,
        'daily_trend': daily_trend,
        'all_garages': all_garages,
        'executive_insight': executive_insight,
        'zone_satisfaction': zone_sat,
        'generated': True,
    }
