"""Reporting garage summary from the daily facts (flag `daily_facts`).

Same rows, same rounding, same field names as routers/reporting.py `_compute_bulk_report`; only where the appointment
numbers come from changes (our facts table instead of 26 pages of appointments and up to 375 history chunks).
Surveys are still read live (one small query). Returns None, never an error, when the flag is off, the range is not fully
covered by facts, or the database says no: the caller then takes today's Salesforce path.
Known difference: the Salesforce path ends a range at 23:59:59Z and so drops an appointment created in the last second
of the last day; the facts keep it.
"""

import logging
from collections import defaultdict

import facts_store
from feature_flags import is_on
from utils import is_fleet_territory, totally_satisfied_pct as _sat_pct

log = logging.getLogger('facts_reporting')


def rows_or_none(territory_ids: list, start_date: str, end_date: str, fetch_surveys) -> list | None:
    """Reporting rows from the facts, or None to use Salesforce. `fetch_surveys()` returns the live survey rows."""
    if not is_on('daily_facts'):
        return None
    try:
        if not facts_store.covered(start_date, end_date):
            return None
        days = facts_store.read_garage_days(start_date, end_date)
    except Exception as e:
        log.warning('reporting facts unavailable, using Salesforce: %s', e)
        return None
    surveys = fetch_surveys()
    territory_surveys = defaultdict(list)
    for sv in surveys:
        tid = (sv.get('ERS_Work_Order__r') or {}).get('ServiceTerritoryId')
        if tid:
            territory_surveys[tid].append(sv)
    return build_rows(days, set(territory_ids), territory_surveys)


def _pct(num, den, nd=1):
    return round(100 * num / den, nd) if den else None


def build_rows(days: list, requested: set, territory_surveys: dict) -> list:
    """One reporting row per requested garage that had appointments, from garage-day facts."""
    agg = {}
    for d in days:                                          # days arrive oldest first
        if d['territory_id'] not in requested or not d['r_total']:
            continue
        a = agg.setdefault(d['territory_id'], defaultdict(int, ata=[], pta=[], pts=[]))
        a['name'] = d['territory_name']
        for k in ('r_total', 'r_completed', 'r_declined', 'r_cancelled', 'r_first_total', 'r_first_accepted',
                  'r_second_total', 'r_second_accepted', 'r_accepted', 'r_accepted_completed'):
            a[k] += d[k]
        a['ata'] += d['ata']
        a['pta'] += d['pta']
        a['pts'] += d['pts']
    rows = []
    for tid, a in agg.items():
        name, total = a['name'], a['r_total']
        is_fleet = is_fleet_territory(name)
        ata, pta, pts = a['ata'], a['pta'], a['pts']
        n_ata, n_pts = len(ata), len(pts)
        on_time = sum(1 for x in pts if x <= 0)
        surveys = territory_surveys.get(tid, [])
        tech_pct = _sat_pct(surveys, 'ERS_Technician_Satisfaction__c')
        n_completed = a['r_completed']
        if is_fleet:
            bonus_tier, bonus_per_sa, total_bonus = 'N/A (Fleet)', 0, 0
        else:
            from repositories import accounting
            bonus_per_sa, bonus_tier = accounting.bonus_for_pct(tech_pct)
            total_bonus = bonus_per_sa * n_completed
        rows.append({
            'garage_id': tid,
            'garage_name': name,
            'garage_type': 'fleet' if is_fleet else 'contractor',
            'total_sas': total,
            'completed': n_completed,
            'completion_pct': round(100 * n_completed / total, 1),
            'declined': a['r_declined'],
            'cancelled': a['r_cancelled'],
            'decline_rate': round(100 * a['r_declined'] / total, 1),
            'first_call_pct': _pct(a['r_first_accepted'], a['r_first_total']),
            'second_call_pct': _pct(a['r_second_accepted'], a['r_second_total']),
            'accepted_completion_pct': _pct(a['r_accepted_completed'], a['r_accepted']),
            'avg_ata': round(sum(ata) / n_ata) if ata else None,
            'median_ata': round(sorted(ata)[n_ata // 2]) if ata else None,
            'under_45_pct': round(100 * sum(1 for t in ata if t < 45) / n_ata, 1) if ata else None,
            'over_120_pct': round(100 * sum(1 for t in ata if t > 120) / n_ata, 1) if ata else None,
            'avg_pta': round(sum(pta) / len(pta)) if pta else None,
            'pta_hit_pct': round(100 * on_time / n_pts, 1) if pts else None,
            'pta_on_time_pct': round(100 * on_time / n_pts, 1) if pts else None,
            'pta_avg_delta': round(sum(pts) / n_pts, 1) if pts else None,
            'total_surveys': len(surveys),
            'overall_pct': _sat_pct(surveys, 'ERS_Overall_Satisfaction__c'),
            'response_time_pct': _sat_pct(surveys, 'ERS_Response_Time_Satisfaction__c'),
            'technician_pct': tech_pct,
            'kept_informed_pct': _sat_pct(surveys, 'ERSSatisfaction_With_Being_Kept_Informed__c'),
            'bonus_tier': bonus_tier,
            'bonus_per_sa': bonus_per_sa,
            'total_bonus': total_bonus,
        })
    return sorted(rows, key=lambda r: r.get('garage_name', ''))
