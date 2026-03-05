"""Dynamic schedule generation — queries SF for real SA volumes per garage."""

import math
from datetime import datetime, timedelta
from collections import defaultdict
from sf_client import sf_query_all

# Cycle times (minutes) — verified from 10K+ SA timestamps
TOW_CYCLE = 115
BATT_CYCLE = 38
LIGHT_CYCLE = 33
BLOCK_MIN = 120  # 2-hour blocks

# Work type classification
# Tow Pick-Up = 1 tow call. Tow Drop-Off = skip (same job, don't double-count).
SKIP_TYPES = {'tow drop-off', 'personal lines - service', 'personal lines - sales',
              'commercial - sales', 'commercial - service', 'life - sales',
              'medicare drop-in', 'medicare', 'travel', 'insurance',
              'cruise – river', 'cruise – ocean', 'existing trip service',
              'aaa retail/groups', 'car/hotel', 'domestic air',
              'international air', 'international - tour', 'domestic - tour'}
BATT_TYPES = {'battery', 'jumpstart'}

DOW_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
BLOCKS = [
    (0, 2, '12-2am'), (2, 4, '2-4am'), (4, 6, '4-6am'),
    (6, 8, '6-8am'), (8, 10, '8-10am'), (10, 12, '10-12pm'),
    (12, 14, '12-2pm'), (14, 16, '2-4pm'), (16, 18, '4-6pm'),
    (18, 20, '6-8pm'), (20, 22, '8-10pm'), (22, 24, '10-12am'),
]
PERIODS = [
    {'name': '6am – 12pm (Morning)', 'blocks': [(6, 8), (8, 10), (10, 12)]},
    {'name': '12pm – 6pm (Peak)', 'blocks': [(12, 14), (14, 16), (16, 18)]},
    {'name': '6pm – 12am (Evening)', 'blocks': [(18, 20), (20, 22), (22, 24)]},
    {'name': '12am – 6am (Overnight)', 'blocks': [(0, 2), (2, 4), (4, 6)]},
]


def _classify_work_type(wt_name: str | None) -> str | None:
    if not wt_name:
        return None
    lower = wt_name.lower().strip()
    if lower in SKIP_TYPES:
        return None
    if lower == 'tow pick-up' or lower == 'tow':
        return 'tow'  # Each pick-up = 1 tow call
    if lower in BATT_TYPES:
        return 'battery'
    # Tire, Lockout, Locksmith, Winch Out, Fuel/Misc, PVS = light service
    return 'light'


def _parse_eastern(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace('+0000', '+00:00').replace('Z', '+00:00'))
        return dt - timedelta(hours=5)  # UTC → Eastern
    except Exception:
        return None


def _ceil(a: float, b: float) -> int:
    if a <= 0:
        return 0
    return max(1, math.ceil(a / b))


def generate_schedule(territory_id: str, weeks: int = 4,
                      start_date: str | None = None,
                      end_date: str | None = None) -> dict:
    """Query SF for real SA data and compute the schedule dynamically.

    If start_date/end_date are provided, queries that exact window.
    Otherwise falls back to LAST_N_DAYS from today.
    """

    # 1. Query SAs for this territory
    if start_date and end_date:
        date_filter = f"CreatedDate >= {start_date}T00:00:00Z AND CreatedDate <= {end_date}T23:59:59Z"
    else:
        date_filter = f"CreatedDate = LAST_N_DAYS:{weeks * 7}"

    sas = sf_query_all(f"""
        SELECT Id, CreatedDate, WorkType.Name
        FROM ServiceAppointment
        WHERE ServiceTerritoryId = '{territory_id}'
          AND {date_filter}
          AND Status IN ('Dispatched', 'Completed', 'Canceled', 'Assigned')
        ORDER BY CreatedDate ASC
    """)

    if not sas:
        return {'error': 'No SAs found for this territory', 'schedule': {}, 'summary': {}}

    # 2. Classify each SA by DOW + hour + work type
    # Structure: dow_hour_type[dow_index][hour] = {'tow': n, 'battery': n, 'light': n}
    dow_hour_counts = defaultdict(lambda: defaultdict(lambda: {'tow': 0, 'battery': 0, 'light': 0}))
    dow_counts = defaultdict(int)
    weeks_seen = set()
    total_by_type = {'tow': 0, 'battery': 0, 'light': 0}

    for sa in sas:
        et = _parse_eastern(sa.get('CreatedDate'))
        if not et:
            continue
        wt = _classify_work_type((sa.get('WorkType') or {}).get('Name'))
        if wt is None:
            continue

        dow = et.weekday()  # 0=Mon
        hour = et.hour
        week_key = et.isocalendar()[:2]
        weeks_seen.add(week_key)

        # For tow, each tow = 2 SAs (pick-up + drop-off), but we already excluded
        # pick-up/drop-off above, so the remaining "Tow" SAs are the actual calls
        dow_hour_counts[dow][hour][wt] += 1
        dow_counts[dow] += 1
        total_by_type[wt] += 1

    n_weeks = max(len(weeks_seen), 1)

    # 3. Compute averages per DOW per 2-hour block
    schedule = {}
    daily_totals = {}

    for dow in range(7):
        dow_name = DOW_NAMES[dow]
        schedule[dow_name] = {}
        max_total_drivers = 0
        max_block_label = ''
        daily_sa_total = round(dow_counts[dow] / n_weeks)
        peak_tow = peak_batt = peak_light = 0

        for h1, h2, label in BLOCKS:
            tow_sum = sum(dow_hour_counts[dow][h][('tow')] for h in range(h1, h2))
            batt_sum = sum(dow_hour_counts[dow][h][('battery')] for h in range(h1, h2))
            light_sum = sum(dow_hour_counts[dow][h][('light')] for h in range(h1, h2))

            # Average over weeks
            tow_calls = round(tow_sum / n_weeks) if tow_sum > 0 else 0
            batt_calls = round(batt_sum / n_weeks) if batt_sum > 0 else 0
            light_calls = round(light_sum / n_weeks) if light_sum > 0 else 0

            # Driver calculation: drivers = ceil(calls × cycle / block_min)
            tow_drv = _ceil(tow_calls * TOW_CYCLE, BLOCK_MIN)
            batt_drv = _ceil(batt_calls * BATT_CYCLE, BLOCK_MIN)
            light_drv = _ceil(light_calls * LIGHT_CYCLE, BLOCK_MIN)
            total_drv = tow_drv + batt_drv + light_drv

            schedule[dow_name][label] = {
                'tow_calls': tow_calls,
                'batt_calls': batt_calls,
                'light_calls': light_calls,
                'tow_drivers': tow_drv,
                'batt_drivers': batt_drv,
                'light_drivers': light_drv,
                'total_drivers': total_drv,
                'is_peak': 12 <= h1 < 18,
            }

            if total_drv > max_total_drivers:
                max_total_drivers = total_drv
                max_block_label = label
                peak_tow = tow_drv
                peak_batt = batt_drv
                peak_light = light_drv

        daily_totals[dow_name] = {
            'total_sas': daily_sa_total,
            'peak_total_drivers': max_total_drivers,
            'peak_tow_drivers': peak_tow,
            'peak_batt_drivers': peak_batt,
            'peak_light_drivers': peak_light,
            'peak_block': max_block_label,
        }

    total_sas = len(sas)
    weekly_avg = round(total_sas / n_weeks)

    return {
        'schedule': schedule,
        'daily_totals': daily_totals,
        'periods': PERIODS,
        'blocks': [(h1, h2, lbl) for h1, h2, lbl in BLOCKS],
        'summary': {
            'total_sas_queried': total_sas,
            'weeks_analyzed': n_weeks,
            'data_start': start_date,
            'data_end': end_date,
            'weekly_average': weekly_avg,
            'daily_average': round(weekly_avg / 7),
            'type_split': {
                'tow_pct': round(100 * total_by_type['tow'] / max(total_sas, 1), 1),
                'battery_pct': round(100 * total_by_type['battery'] / max(total_sas, 1), 1),
                'light_pct': round(100 * total_by_type['light'] / max(total_sas, 1), 1),
            },
            'cycle_times': {
                'tow': TOW_CYCLE,
                'battery': BATT_CYCLE,
                'light': LIGHT_CYCLE,
            },
        },
    }
