"""Dispatch trends — per-month endpoints and monthly generation/refresh."""

from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from utils import parse_dt as _parse_dt
from sf_client import sf_query_all, sf_parallel, sanitize_soql
from dispatch_decomposition import get_forecast
import cache

from routers.dispatch_trends import _fetch_trends_range, api_trends

router = APIRouter()


def _generate_month_trends(month: str):
    """Heavy lifting for monthly trends — runs in background thread."""
    import re, calendar, logging
    from datetime import date as _date, timedelta as _td

    _log = logging.getLogger('trends_month')
    year, mon = int(month[:4]), int(month[5:7])

    first_day = _date(year, mon, 1)
    last_day_num = calendar.monthrange(year, mon)[1]
    end_day = _date(year, mon, last_day_num) + _td(days=1)

    today = _date.today()
    is_current = (year == today.year and mon == today.month)
    if is_current:
        end_day = today  # exclude today

    cache_key = f'insights_trends_month_{month}'
    ttl = 14400 if is_current else 31536000  # 4h current, 1 year past (data never changes)

    start_utc = f"{first_day.isoformat()}T00:00:00Z"
    end_utc = f"{end_day.isoformat()}T00:00:00Z"

    days_output = _fetch_trends_range(start_utc, end_utc)

    # Garage rankings — parallel SF queries
    def _get_garage_sas():
        return sf_query_all(f"""
            SELECT Id, CreatedDate, Status, ActualStartTime,
                   ERS_Dispatch_Method__c, ServiceTerritoryId,
                   ServiceTerritory.Name, WorkType.Name
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritoryId != null
              AND RecordType.Name = 'ERS Service Appointment'
        """)

    def _get_garage_hist():
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND Field = 'Status'
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
        """)

    garage_data = sf_parallel(sas=_get_garage_sas, hist=_get_garage_hist)
    all_sas = garage_data['sas']

    towbook_on_location = {}
    for r in garage_data['hist']:
        sa_id = r.get('ServiceAppointmentId')
        if sa_id and r.get('NewValue') == 'On Location':
            ts = _parse_dt(r.get('CreatedDate'))
            if ts and (sa_id not in towbook_on_location or ts < towbook_on_location[sa_id]):
                towbook_on_location[sa_id] = ts

    garage = defaultdict(lambda: {'volume': 0, 'completed': 0, 'ata_sum': 0.0, 'ata_count': 0})
    for sa in all_sas:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        tname = (sa.get('ServiceTerritory') or {}).get('Name', '')
        if not tname:
            continue
        tl = tname.lower()
        if any(x in tl for x in ('office', 'spot', 'fleet', 'region')):
            continue
        if len(tname) <= 6 and tname[:2].isalpha() and tname[2:].isdigit():
            continue
        g = garage[tname]
        g['volume'] += 1
        if sa.get('Status') == 'Completed':
            g['completed'] += 1
        dm = sa.get('ERS_Dispatch_Method__c') or ''
        if sa.get('Status') == 'Completed':
            if dm == 'Field Services':
                created = _parse_dt(sa.get('CreatedDate'))
                actual = _parse_dt(sa.get('ActualStartTime'))
                if created and actual:
                    diff = (actual - created).total_seconds() / 60
                    if 0 < diff < 480:
                        g['ata_sum'] += diff; g['ata_count'] += 1
            elif dm == 'Towbook':
                on_loc = towbook_on_location.get(sa.get('Id'))
                if on_loc:
                    created = _parse_dt(sa.get('CreatedDate'))
                    if created:
                        diff = (on_loc - created).total_seconds() / 60
                        if 0 < diff < 480:
                            g['ata_sum'] += diff; g['ata_count'] += 1

    qualified = []
    for name, g in garage.items():
        if g['volume'] < 20:
            continue
        avg_ata = round(g['ata_sum'] / g['ata_count']) if g['ata_count'] else 999
        comp_pct = round(100 * g['completed'] / g['volume']) if g['volume'] else 0
        qualified.append({'name': name, 'ata': avg_ata, 'completion_pct': comp_pct, 'volume': g['volume']})

    top_pool = sorted([g for g in qualified if g['completion_pct'] > 85 and g['ata'] < 999], key=lambda x: x['ata'])
    bottom_pool = sorted([g for g in qualified if g['ata'] < 999], key=lambda x: (-x['ata'], x['completion_pct']))

    result = {
        'month': month,
        'days': days_output,
        'top_garages': top_pool[:3],
        'bottom_garages': bottom_pool[:3],
    }

    cache.put(cache_key, result, ttl)
    cache.disk_put(cache_key, result, ttl)
    _log.info(f"Month trends for {month}: {len(days_output)} days, {len(all_sas)} SAs")
    return result


# Track which months are currently being generated (filesystem lock for cross-worker safety)

@router.get("/api/insights/trends/month")
def api_trends_month(month: str = Query(..., description="YYYY-MM format, e.g. 2026-02")):
    """Trend data for a specific calendar month.

    Non-blocking: serves from cache only. If no cache exists, triggers
    background generation and returns {loading: true} immediately.
    """
    import re, calendar, logging
    from datetime import date as _date

    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format (e.g. 2026-02)")
    try:
        year, mon = int(month[:4]), int(month[5:7])
        if mon < 1 or mon > 12:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "Invalid month")

    today = _date.today()
    if _date(year, mon, 1) > today:
        raise HTTPException(400, "Cannot fetch future months")

    is_current = (year == today.year and mon == today.month)
    cache_key = f'insights_trends_month_{month}'
    ttl = 43200 if is_current else 604800  # 12h current, 7d past

    # 1. Memory cache
    cached = cache.get(cache_key)
    if cached:
        return cached
    # 2. Disk cache
    disk = cache.disk_get(cache_key, ttl=ttl)
    if disk:
        cache.put(cache_key, disk, ttl)
        return disk

    # 3. No cache — trigger background generation, return immediately
    import threading
    _log = logging.getLogger('trends_month')

    gen_lock = f'gen_month_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=1800):
        def _bg():
            try:
                _generate_month_trends(month)
            except Exception as e:
                _log.warning(f"Month trends generation failed for {month}: {e}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()
        _log.info(f"Month trends background generation started for {month}")

    return {'month': month, 'days': [], 'top_garages': [], 'bottom_garages': [], 'loading': True}


@router.get("/api/insights/trends/month/refresh")
def api_trends_month_refresh(month: str = Query(..., description="YYYY-MM format")):
    """Force-refresh a specific month's trends — clears cache and regenerates."""
    import re, threading, logging
    from datetime import date as _date

    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format")
    year, mon = int(month[:4]), int(month[5:7])
    today = _date.today()
    if _date(year, mon, 1) > today:
        raise HTTPException(400, "Cannot refresh future months")

    _log = logging.getLogger('trends_month')
    cache_key = f'insights_trends_month_{month}'

    # Clear memory + disk cache for this month
    cache.invalidate(cache_key)
    cache.disk_invalidate(cache_key)
    # Also clear the 30-day rolling trends since they overlap with current month
    cache.invalidate('insights_trends_30d')
    cache.disk_invalidate('insights_trends_30d')
    _log.info(f"Month {month} cache cleared, starting regeneration")

    # Trigger background regeneration
    gen_lock = f'gen_month_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=1800):
        def _bg():
            try:
                _generate_month_trends(month)
            except Exception as e:
                _log.warning(f"Month trends refresh failed for {month}: {e}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()

    return {'status': 'refreshing', 'month': month}


@router.get("/api/insights/trends/refresh")
def api_trends_force_refresh():
    """Force-refresh 30-day trends. Smart: fetches only missing days (<=7) or triggers full refresh."""
    import threading, logging as _lg
    from datetime import date as _date, timedelta as _td, timezone as _tz

    log = _lg.getLogger('trends_refresh')
    today_utc = _date.today()  # UTC date
    yesterday_utc = today_utc - _td(days=1)

    # Expected last 30 complete days (UTC dates, as stored in cache)
    expected = {(yesterday_utc - _td(days=i)).isoformat() for i in range(30)}

    current = cache.disk_get_stale('insights_trends_30d')
    cached_dates = {d['date'] for d in (current or {}).get('days', [])} if current else set()
    missing = sorted(expected - cached_dates)

    if not missing:
        return {'status': 'up_to_date', 'missing_days': 0, 'cached_through': yesterday_utc.isoformat()}

    log.info(f"Trends force-refresh: {len(missing)} missing days ({missing[0]} ... {missing[-1]})")

    if len(missing) <= 7 and current:
        # Incremental path: only fetch the missing date range
        start_utc = f"{missing[0]}T00:00:00Z"
        end_utc = f"{((_date.fromisoformat(missing[-1])) + _td(days=1)).isoformat()}T00:00:00Z"
        try:
            new_rows = _fetch_trends_range(start_utc, end_utc)
            # Merge: keep existing days not in new_rows, add new_rows
            new_dates = {r['date'] for r in new_rows}
            merged_days = [d for d in current['days'] if d['date'] not in new_dates] + new_rows
            merged_days.sort(key=lambda x: x['date'])
            # Keep last 30 days only
            merged_days = merged_days[-30:]
            merged = {**current, 'days': merged_days}
            cache.put('insights_trends_30d', merged, 86400)
            cache.disk_put('insights_trends_30d', merged, 86400)
            log.info(f"Incremental trends merge complete: added {len(new_rows)} days.")
            return {'status': 'updated', 'missing_days': len(missing), 'new_days': len(new_rows), 'data': merged}
        except Exception as e:
            log.warning(f"Incremental fetch failed, falling back to full refresh: {e}")
            # Fall through to full refresh

    # Full refresh path
    cache.disk_invalidate('insights_trends_30d')
    cache.invalidate('insights_trends_30d')

    def _bg():
        _log = _lg.getLogger('trends_refresh')
        for attempt in range(3):
            try:
                result = api_trends()  # re-uses existing _fetch via bg thread logic
                if result and not result.get('loading'):
                    _log.info("Full refresh bg complete.")
                    return
                # _fetch is still running in its own daemon thread; give it time
                import time as _t
                for _ in range(90):
                    _t.sleep(10)
                    done = cache.get('insights_trends_30d')
                    if done and not done.get('loading'):
                        _log.info("Full refresh complete (polled).")
                        return
                raise TimeoutError("Full refresh timed out after 15min")
            except Exception as e:
                _log.warning(f"Full refresh attempt {attempt+1}/3 failed: {e}")
                if attempt < 2:
                    import time as _t2; _t2.sleep(60)

    # Trigger the first api_trends call to start the bg thread
    api_trends()
    threading.Thread(target=_bg, daemon=True).start()
    return {'status': 'full_refresh_triggered', 'missing_days': len(missing), 'loading': True}


## NOTE: /api/garages/{territory_id}/decomposition is in routers/garages.py
## NOTE: /api/territory/{territory_id}/forecast is kept here (not in garages.py)

@router.get("/api/territory/{territory_id}/forecast")
def api_forecast(territory_id: str, weeks_history: int = Query(8, ge=2, le=16)):
    """16-day demand forecast using DOW patterns + weather."""
    territory_id = sanitize_soql(territory_id)
    return get_forecast(territory_id, weeks_history)
