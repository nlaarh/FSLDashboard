"""Satisfaction Scorecard — executive multi-horizon satisfaction view.

Zero SF queries in normal operation. Reads from already-cached monthly
satisfaction overviews (L2 SQLite) and repackages into Rolling 12, Monthly,
Weekly, and Last 7 Days. Generated nightly at 3 AM alongside other heavy jobs.

Falls back to a single lightweight SOQL query only on cold start (no cache).
"""

import logging
import time as _time
from collections import defaultdict
from datetime import date, timedelta
from fastapi import APIRouter

import cache

router = APIRouter()
log = logging.getLogger('scorecard')

CACHE_KEY = 'satisfaction_scorecard'


# ── Public endpoint ──────────────────────────────────────────────────────────

@router.get("/api/insights/satisfaction/scorecard")
def api_satisfaction_scorecard():
    """Satisfaction scorecard: Rolling 12, Monthly, Weekly, Last 7 Days.

    Fast path: reads from already-cached monthly overviews (sub-ms).
    Only falls back to SOQL on cold start with zero cached months.
    """
    # Try cache first (L1 → L2)
    result = cache.get_from_any_layer(CACHE_KEY, ttl=86400)
    if result and result.get('generated'):
        return result

    # Generate synchronously — it's just reading cached data, near-instant.
    # Only slow if SOQL fallback is needed (cold start, no cached months).
    try:
        data = generate_scorecard()
        if data.get('generated'):
            cache.put(CACHE_KEY, data, 86400)
            cache.disk_put(CACHE_KEY, data, 86400)
            return data
    except Exception as e:
        log.warning(f"Scorecard generation failed: {e}")

    return {'loading': True, 'message': 'No satisfaction data cached yet. View a few months first.'}


# ── Generation logic ─────────────────────────────────────────────────────────

def generate_scorecard() -> dict:
    """Build scorecard from cached monthly overviews. Zero SF queries.

    Falls back to a single SOQL query if cached months are missing.
    """
    today = date.today()

    # ── Collect monthly data from cached overviews (last 20 months) ──
    # We need 20 months to compute rolling 12 for the last 8 display months
    monthly_data = {}  # 'YYYY-MM' -> {pct, surveys, daily_trend}
    months_needed = _month_range(today, 20)

    for month_key in months_needed:
        cache_key = f'satisfaction_overview_{month_key}'
        data = cache.disk_get_stale(cache_key)
        if not data:
            data = cache.get_stale(cache_key)
        if data and data.get('generated') and data.get('summary'):
            monthly_data[month_key] = {
                'pct': data['summary'].get('totally_satisfied_pct'),
                'surveys': data['summary'].get('total_surveys', 0),
                'daily_trend': data.get('daily_trend', []),
            }

    # If zero months cached, fall back to SOQL
    if len(monthly_data) == 0:
        log.info("No cached months — falling back to SOQL")
        monthly_data = _fallback_soql(today)

    # ── Build the 4 sections ──
    rolling_12 = _build_rolling_12(monthly_data, today)
    monthly = _build_monthly(monthly_data, today)
    weekly = _build_weekly(monthly_data, today)
    last_7 = _build_last_7_days(monthly_data, today)

    return {
        'rolling_12': rolling_12,
        'monthly': monthly,
        'weekly': weekly,
        'last_7_days': last_7,
        'as_of': today.isoformat(),
        'cached_at': _time.strftime('%Y-%m-%d %H:%M:%S'),
        'generated': True,
    }


def _build_monthly(monthly_data: dict, today: date) -> list:
    """Last 8 months individual scores."""
    months = _month_range(today, 8)
    result = []
    for key in months:
        md = monthly_data.get(key)
        result.append({
            'month': key,
            'label': _month_label(key),
            'pct': md['pct'] if md else None,
            'surveys': md['surveys'] if md else 0,
        })
    return result


def _build_rolling_12(monthly_data: dict, today: date) -> list:
    """Rolling 12-month average for each of the last 8 months."""
    # Build sorted list of all months with data
    all_months = _month_range(today, 20)
    result = []

    # Display last 8 months
    display_months = _month_range(today, 8)
    for month_key in display_months:
        # Get the 12 months ending at this month (inclusive)
        window = _get_12_month_window(month_key, all_months)
        total_ts = 0
        total_surveys = 0
        for wm in window:
            md = monthly_data.get(wm)
            if md and md['pct'] is not None and md['surveys']:
                # Reverse-engineer counts from pct
                ts_count = round(md['pct'] * md['surveys'] / 100)
                total_ts += ts_count
                total_surveys += md['surveys']

        pct = round(100 * total_ts / total_surveys, 1) if total_surveys else None
        result.append({
            'month': month_key,
            'label': _month_label(month_key),
            'pct': pct,
            'surveys': total_surveys,
        })
    return result


def _build_weekly(monthly_data: dict, today: date) -> list:
    """Last 5 complete weeks (Sun–Sat)."""
    # Collect all daily_trend entries from recent months
    daily = _collect_daily_data(monthly_data, days_back=45)

    # Find last complete Saturday
    # weekday(): Mon=0, Sun=6. We want Sun-Sat weeks.
    last_sat = today - timedelta(days=1)
    while last_sat.weekday() != 5:  # 5 = Saturday
        last_sat -= timedelta(days=1)

    result = []
    for w in range(5):
        week_end = last_sat - timedelta(weeks=w)
        week_start = week_end - timedelta(days=6)  # Sunday

        total_ts = 0
        total_surveys = 0
        for d_str, d_data in daily.items():
            try:
                d = date.fromisoformat(d_str)
            except (ValueError, TypeError):
                continue
            if week_start <= d <= week_end:
                total_surveys += d_data['surveys']
                total_ts += d_data['ts']

        pct = round(100 * total_ts / total_surveys, 1) if total_surveys else None
        result.append({
            'start': week_start.isoformat(),
            'end': week_end.isoformat(),
            'label': f"{week_start.strftime('%-m/%-d')} - {week_end.strftime('%-m/%-d')}",
            'pct': pct,
            'surveys': total_surveys,
        })

    result.reverse()  # oldest first
    return result


def _build_last_7_days(monthly_data: dict, today: date) -> list:
    """Daily scores for the last 7 complete days."""
    daily = _collect_daily_data(monthly_data, days_back=10)

    result = []
    for i in range(7, 0, -1):
        d = today - timedelta(days=i)
        d_str = d.isoformat()
        d_data = daily.get(d_str)
        if d_data and d_data['surveys'] > 0:
            pct = round(100 * d_data['ts'] / d_data['surveys'], 1)
        else:
            pct = None
        result.append({
            'date': d_str,
            'label': d.strftime('%-d-%b'),
            'pct': pct,
            'surveys': d_data['surveys'] if d_data else 0,
        })
    return result


# ── Helpers ──────────────────────────────────────────────────────────────────

def _collect_daily_data(monthly_data: dict, days_back: int) -> dict:
    """Extract daily ts/total counts from cached daily_trend arrays."""
    daily = {}  # 'YYYY-MM-DD' -> {ts: int, surveys: int}
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()

    for _month_key, md in monthly_data.items():
        for entry in md.get('daily_trend', []):
            d = entry.get('date', '')
            if d < cutoff:
                continue
            surveys = entry.get('surveys', 0) or 0
            pct = entry.get('totally_satisfied_pct')
            if surveys > 0 and pct is not None:
                ts = round(pct * surveys / 100)
                daily[d] = {'ts': ts, 'surveys': surveys}
            elif surveys > 0:
                daily[d] = {'ts': 0, 'surveys': surveys}
    return daily


def _month_range(today: date, count: int) -> list:
    """Return list of 'YYYY-MM' strings for last `count` months, oldest first."""
    months = []
    y, m = today.year, today.month
    for _ in range(count):
        months.append(f"{y}-{m:02d}")
        m -= 1
        if m < 1:
            m = 12
            y -= 1
    months.reverse()
    return months


def _get_12_month_window(target_month: str, all_months: list) -> list:
    """Return the 12 months ending at target_month (inclusive)."""
    try:
        idx = all_months.index(target_month)
    except ValueError:
        return [target_month]
    start = max(0, idx - 11)
    return all_months[start:idx + 1]


def _month_label(key: str) -> str:
    """'2026-03' -> 'March'."""
    from datetime import datetime
    try:
        return datetime.strptime(key, '%Y-%m').strftime('%B')
    except ValueError:
        return key


# ── SOQL fallback (cold start only) ─────────────────────────────────────────

def _fallback_soql(today: date) -> dict:
    """Single SOQL query fallback when cached months don't exist yet."""
    from sf_client import sf_query_all

    start = today - timedelta(days=610)  # ~20 months
    start_utc = f"{start.isoformat()}T00:00:00Z"
    end_utc = f"{(today + timedelta(days=1)).isoformat()}T00:00:00Z"

    log.info(f"Scorecard SOQL fallback: {start_utc} to {end_utc}")
    rows = sf_query_all(f"""
        SELECT DAY_ONLY(ERS_Work_Order__r.CreatedDate) d,
               ERS_Overall_Satisfaction__c sat,
               COUNT(Id) cnt
        FROM Survey_Result__c
        WHERE ERS_Work_Order__r.CreatedDate >= {start_utc}
          AND ERS_Work_Order__r.CreatedDate < {end_utc}
          AND ERS_Overall_Satisfaction__c != null
        GROUP BY DAY_ONLY(ERS_Work_Order__r.CreatedDate),
                 ERS_Overall_Satisfaction__c
    """)

    # Aggregate into daily buckets
    day_buckets = defaultdict(lambda: {'ts': 0, 'total': 0})
    for r in rows:
        d = r.get('d', '')
        sat_val = (r.get('sat') or '').strip().lower()
        cnt = r.get('cnt', 0) or 0
        if d and sat_val:
            day_buckets[d]['total'] += cnt
            if sat_val == 'totally satisfied':
                day_buckets[d]['ts'] += cnt

    # Repackage into monthly_data format
    monthly_data = {}
    month_agg = defaultdict(lambda: {'ts': 0, 'total': 0, 'trend': []})
    for d_str, b in sorted(day_buckets.items()):
        month_key = d_str[:7]
        month_agg[month_key]['ts'] += b['ts']
        month_agg[month_key]['total'] += b['total']
        pct = round(100 * b['ts'] / b['total']) if b['total'] else None
        month_agg[month_key]['trend'].append({
            'date': d_str,
            'totally_satisfied_pct': pct,
            'surveys': b['total'],
        })

    for mk, ma in month_agg.items():
        pct = round(100 * ma['ts'] / ma['total']) if ma['total'] else None
        monthly_data[mk] = {
            'pct': pct,
            'surveys': ma['total'],
            'daily_trend': ma['trend'],
        }

    return monthly_data
