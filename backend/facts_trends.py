"""The 30-day trends from the daily facts (flag `daily_facts`).

Same output shape, field names and rounding as routers/dispatch_trends.py `_fetch`. Differences, on purpose:
  - It returns the last 30 COMPLETE UTC days. The Salesforce path cuts its window at Eastern midnight, so its first and
    last dates are partial days; those two edge points are the only dates that differ.
  - Reassignments come from the day's stored count instead of 166k history rows.
The survey share per day is still read live (one grouped query, 31 rows) because surveys arrive days late.
Returns None, never an error, when the flag is off, the 30 days are not all covered, or the database says no: the caller
then runs today's Salesforce path.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import facts_store
from feature_flags import is_on

log = logging.getLogger('facts_trends')
DAYS = 30


def fetch_satisfaction() -> list:
    """Overall satisfaction counts by day: the same grouped query the Salesforce path runs."""
    from sf_client import sf_query_all
    return sf_query_all("""
        SELECT DAY_ONLY(CreatedDate) d,
               ERS_Overall_Satisfaction__c sat,
               COUNT(Id) cnt
        FROM Survey_Result__c
        WHERE CreatedDate = LAST_N_DAYS:31
          AND CreatedDate < TODAY
          AND ERS_Overall_Satisfaction__c != null
        GROUP BY DAY_ONLY(CreatedDate), ERS_Overall_Satisfaction__c
    """)


def trends_or_none(now: datetime | None = None, fetch_sat=fetch_satisfaction) -> dict | None:
    if not is_on('daily_facts'):
        return None
    now = now or datetime.now(timezone.utc)
    last = (now - timedelta(days=1)).date()
    first = last - timedelta(days=DAYS - 1)
    try:
        if not facts_store.covered(first.isoformat(), last.isoformat(), now):
            return None
        garage_days = facts_store.read_garage_days(first.isoformat(), last.isoformat())
        day_meta = facts_store.day_rows([first.isoformat(), last.isoformat()])
    except Exception as e:
        log.warning('trends facts unavailable, using Salesforce: %s', e)
        return None
    return build_trends(garage_days, {d: m['reassignments'] for d, m in day_meta.items()}, fetch_sat())


def build_trends(garage_days: list, reassign_by_day: dict, satisfaction_rows: list) -> dict:
    sat_by_day = defaultdict(lambda: {'totally_satisfied': 0, 'total': 0})
    for r in satisfaction_rows:
        date_str = r.get('d', '')
        sat_val = (r.get('sat') or '').strip()
        cnt = r.get('cnt', 0) or 0
        if date_str and sat_val:
            sat_by_day[date_str]['total'] += cnt
            if sat_val.lower() == 'totally satisfied':
                sat_by_day[date_str]['totally_satisfied'] += cnt

    daily = defaultdict(lambda: defaultdict(float))
    garage = defaultdict(lambda: {'volume': 0, 'completed': 0, 'ata_sum': 0.0, 'ata_count': 0})
    for g in garage_days:
        d = daily[g['day']]
        for k in ('t_volume', 't_completed', 't_auto', 't_fleet_sum', 't_fleet_n', 't_sla_hits', 't_tb_sum', 't_tb_n'):
            d[k] += g[k]
        tname = g['territory_name']
        if not tname:
            continue
        tl = tname.lower()
        if any(x in tl for x in ('office', 'spot', 'fleet', 'region')):
            continue                                                      # not a garage: offices, spot, fleet aggregates
        if len(tname) <= 6 and tname[:2].isalpha() and tname[2:].isdigit():
            continue                                                      # grid zone such as WR006
        t = garage[tname]
        t['volume'] += g['t_volume']
        t['completed'] += g['t_completed']
        t['ata_sum'] += g['t_fleet_sum'] + g['t_tb_sum']
        t['ata_count'] += g['t_fleet_n'] + g['t_tb_n']

    days_output = []
    for date_str in sorted(daily):
        d = daily[date_str]
        vol, comp = int(d['t_volume']), int(d['t_completed'])
        sat_info = sat_by_day.get(date_str, {})
        days_output.append({
            'date': date_str,
            'volume': vol,
            'completed': comp,
            'completion_pct': round(100 * comp / vol) if vol else 0,
            'auto_pct': round(100 * d['t_auto'] / vol) if vol else None,
            'sla_pct': round(100 * d['t_sla_hits'] / d['t_fleet_n']) if d['t_fleet_n'] else None,
            'fleet_ata': round(d['t_fleet_sum'] / d['t_fleet_n']) if d['t_fleet_n'] else None,
            'towbook_ata': round(d['t_tb_sum'] / d['t_tb_n']) if d['t_tb_n'] else None,
            'reassignments': reassign_by_day.get(date_str, 0),
            'closest_pct': None,
            'satisfaction_pct': round(100 * sat_info['totally_satisfied'] / sat_info['total']) if sat_info.get('total') else None,
        })

    qualified = []
    for name, g in garage.items():
        if g['volume'] < 20:
            continue                                                      # minimum 20 calls to qualify
        qualified.append({'name': name,
                          'ata': round(g['ata_sum'] / g['ata_count']) if g['ata_count'] else 999,
                          'completion_pct': round(100 * g['completed'] / g['volume']) if g['volume'] else 0,
                          'volume': g['volume']})
    top_pool = sorted((g for g in qualified if g['completion_pct'] > 85 and g['ata'] < 999), key=lambda x: x['ata'])
    bottom_pool = sorted((g for g in qualified if g['ata'] < 999), key=lambda x: (-x['ata'], x['completion_pct']))
    return {'days': days_output, 'top_garages': top_pool[:3], 'bottom_garages': bottom_pool[:3]}
