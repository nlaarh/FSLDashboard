"""Dynamic schedule generation — uses aggregate SOQL for speed (~0.6s)."""

import math
from datetime import date, timedelta
from collections import defaultdict
from sf_client import sf_query_all, sf_parallel, sanitize_soql

# Cycle times (minutes) — verified from 10K+ SA timestamps
TOW_CYCLE = 115
BATT_CYCLE = 38    # battery
LIGHT_CYCLE = 33   # light service (tire, lockout, fuel, etc.)
BATT_LIGHT_COMBINED_LABEL = 'Battery/Light'
BLOCK_MIN = 120  # 2-hour blocks

# Work type classification
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
        return 'tow'
    if lower in BATT_TYPES:
        return 'battery'
    return 'light'


def _ceil(a: float, b: float) -> int:
    if a <= 0:
        return 0
    return max(1, math.ceil(a / b))


def generate_schedule(territory_id: str, weeks: int = 4,
                      start_date: str | None = None,
                      end_date: str | None = None) -> dict:
    """Single aggregate SOQL query → schedule in ~0.6s (was 22s with individual records)."""
    territory_id = sanitize_soql(territory_id)
    if start_date:
        start_date = sanitize_soql(start_date)
    if end_date:
        end_date = sanitize_soql(end_date)

    if start_date and end_date:
        since = f"{start_date}T00:00:00Z"
        until = f"{end_date}T23:59:59Z"
    else:
        d = date.today() - timedelta(days=weeks * 7)
        since = f"{d.isoformat()}T00:00:00Z"
        until = f"{date.today().isoformat()}T23:59:59Z"

    # Two aggregate queries in parallel — both sub-second
    data = sf_parallel(
        counts=lambda: sf_query_all(f"""
            SELECT DAY_IN_WEEK(CreatedDate) dow,
                   HOUR_IN_DAY(CreatedDate) hr,
                   WorkType.Name wt,
                   COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {since}
              AND CreatedDate <= {until}
              AND Status IN ('Dispatched','Completed','Canceled','Assigned')
            GROUP BY DAY_IN_WEEK(CreatedDate), HOUR_IN_DAY(CreatedDate), WorkType.Name
        """),
        weeks=lambda: sf_query_all(f"""
            SELECT WEEK_IN_YEAR(CreatedDate) w, CALENDAR_YEAR(CreatedDate) y
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {since}
              AND CreatedDate <= {until}
              AND Status IN ('Dispatched','Completed','Canceled','Assigned')
            GROUP BY WEEK_IN_YEAR(CreatedDate), CALENDAR_YEAR(CreatedDate)
        """),
    )

    rows = data['counts']
    if not rows:
        return {'error': 'No SAs found for this territory', 'schedule': {}, 'summary': {}}

    n_weeks = max(len(data['weeks']), 1)

    # Build counts from aggregate data
    # SOQL DAY_IN_WEEK: 1=Sun, 2=Mon ... 7=Sat → our DOW: 0=Mon
    # SOQL HOUR_IN_DAY: UTC → shift to Eastern (UTC-5)
    dow_hour_counts = defaultdict(lambda: defaultdict(lambda: {'tow': 0, 'battery': 0, 'light': 0}))
    dow_counts = defaultdict(int)
    total_by_type = {'tow': 0, 'battery': 0, 'light': 0}
    total_sas = 0

    for row in rows:
        soql_dow = row.get('dow')
        utc_hour = row.get('hr')
        wt_name = row.get('wt') or ''
        count = row.get('cnt', 0)

        if soql_dow is None or utc_hour is None:
            continue

        wt = _classify_work_type(wt_name)
        if wt is None:
            continue

        soql_dow = int(soql_dow)
        utc_hour = int(utc_hour)

        # Convert UTC to Eastern (UTC-5)
        eastern_hour = (utc_hour - 5) % 24
        if utc_hour < 5:
            soql_dow = soql_dow - 1
            if soql_dow < 1:
                soql_dow = 7

        our_dow = (soql_dow - 2) % 7

        dow_hour_counts[our_dow][eastern_hour][wt] += count
        dow_counts[our_dow] += count
        total_by_type[wt] += count
        total_sas += count

    # Compute averages per DOW per 2-hour block
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
            tow_sum = sum(dow_hour_counts[dow][h]['tow'] for h in range(h1, h2))
            batt_sum = sum(dow_hour_counts[dow][h]['battery'] for h in range(h1, h2))
            light_sum = sum(dow_hour_counts[dow][h]['light'] for h in range(h1, h2))

            tow_calls = round(tow_sum / n_weeks) if tow_sum > 0 else 0
            batt_calls = round(batt_sum / n_weeks) if batt_sum > 0 else 0
            light_calls = round(light_sum / n_weeks) if light_sum > 0 else 0

            tow_drv = _ceil(tow_calls * TOW_CYCLE, BLOCK_MIN)
            batt_drv = _ceil(batt_calls * BATT_CYCLE, BLOCK_MIN)
            light_drv = _ceil(light_calls * LIGHT_CYCLE, BLOCK_MIN)
            total_drv = tow_drv + batt_drv + light_drv

            schedule[dow_name][label] = {
                'tow_calls':        tow_calls,
                'batt_light_calls': batt_calls + light_calls,
                'tow_drivers':        tow_drv,
                'batt_light_drivers': batt_drv + light_drv,
                'total_drivers':      total_drv,
                'is_peak':            12 <= h1 < 18,
            }

            if total_drv > max_total_drivers:
                max_total_drivers = total_drv
                max_block_label = label
                peak_tow = tow_drv
                peak_batt = batt_drv
                peak_light = light_drv

        daily_totals[dow_name] = {
            'total_sas':              daily_sa_total,
            'peak_total_drivers':     max_total_drivers,
            'peak_tow_drivers':       peak_tow,
            'peak_batt_light_drivers': peak_batt + peak_light,
            'peak_block':             max_block_label,
        }

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
                'tow_pct':       round(100 * total_by_type['tow'] / max(total_sas, 1), 1),
                'batt_light_pct': round(100 * (total_by_type['battery'] + total_by_type['light']) / max(total_sas, 1), 1),
            },
            'cycle_times': {
                'tow':        TOW_CYCLE,
                'batt_light': '33–38',
            },
        },
    }
