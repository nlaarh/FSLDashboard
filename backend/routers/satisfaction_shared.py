"""Shared satisfaction computation: ATA/PTA per-day+driver, driver satisfaction aggregation.

Used by both satisfaction_garage.py (monthly) and satisfaction_day.py (daily drill-down)
to avoid duplicating the same loops.
"""

from collections import defaultdict
from utils import parse_dt as _parse_dt


def _build_towbook_on_location_map(tb_on_loc_rows):
    """Build {sa_id: earliest_on_location_datetime} from SAHistory rows."""
    towbook_on_location = {}
    for r in tb_on_loc_rows:
        if r.get('NewValue') != 'On Location':
            continue
        sa_id = r.get('ServiceAppointmentId')
        ts = _parse_dt(r.get('CreatedDate'))
        if ts and (sa_id not in towbook_on_location or ts < towbook_on_location[sa_id]):
            towbook_on_location[sa_id] = ts
    return towbook_on_location


def _process_sa_ata_pta(sas, towbook_on_location, assigned_by_sa=None):
    """Process completed SAs to compute per-day and per-driver ATA/PTA metrics.

    Returns (day_ata, driver_stats) where:
      day_ata[date_str]  = {ata_sum, ata_count, pta_miss, pta_eligible}
      driver_stats[driver_id] = {driver_id, name, sa_count, ata_sum, ata_count, pta_miss, pta_eligible}
    """
    day_ata = defaultdict(lambda: {'ata_sum': 0.0, 'ata_count': 0, 'pta_miss': 0, 'pta_eligible': 0})
    driver_stats = defaultdict(lambda: {
        'driver_id': None, 'name': None,
        'sa_count': 0, 'ata_sum': 0.0, 'ata_count': 0,
        'pta_miss': 0, 'pta_eligible': 0,
    })

    for sa in sas:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        date_str = (sa.get('CreatedDate') or '')[:10]
        if not date_str:
            continue
        dm = sa.get('ERS_Dispatch_Method__c') or ''
        d = day_ata[date_str]

        driver_id, driver_name = None, None
        if assigned_by_sa:
            mapped = assigned_by_sa.get(sa.get('Id')) or {}
            driver_id = mapped.get('driver_id')
            driver_name = mapped.get('name')
        else:
            ar_records = (sa.get('ServiceResources') or {}).get('records') or []
            if ar_records:
                driver_id = ar_records[0].get('ServiceResourceId')
                sr = ar_records[0].get('ServiceResource') or {}
                driver_name = sr.get('Name')
        if driver_id and driver_name:
            ds = driver_stats[driver_id]
            ds['driver_id'] = driver_id
            ds['name'] = driver_name
            ds['sa_count'] += 1

        ata_min = None
        if dm == 'Field Services':
            created = _parse_dt(sa.get('CreatedDate'))
            actual = _parse_dt(sa.get('ActualStartTime'))
            if created and actual:
                diff = (actual - created).total_seconds() / 60
                if 0 < diff < 480:
                    ata_min = diff
                    d['ata_sum'] += diff
                    d['ata_count'] += 1
        elif dm == 'Towbook':
            on_loc = towbook_on_location.get(sa.get('Id'))
            if on_loc:
                created = _parse_dt(sa.get('CreatedDate'))
                if created:
                    diff = (on_loc - created).total_seconds() / 60
                    if 0 < diff < 480:
                        ata_min = diff
                        d['ata_sum'] += diff
                        d['ata_count'] += 1
        if ata_min is not None and driver_id:
            driver_stats[driver_id]['ata_sum'] += ata_min
            driver_stats[driver_id]['ata_count'] += 1

        pta_raw = sa.get('ERS_PTA__c')
        if pta_raw is not None:
            try:
                pta_min = float(pta_raw)
            except (TypeError, ValueError):
                pta_min = None
            if pta_min is not None and 0 < pta_min < 999:
                created = _parse_dt(sa.get('CreatedDate'))
                arrived = towbook_on_location.get(sa.get('Id')) if dm == 'Towbook' else _parse_dt(sa.get('ActualStartTime'))
                if created and arrived:
                    ata_for_pta = (arrived - created).total_seconds() / 60
                    if 0 < ata_for_pta < 480:
                        d['pta_eligible'] += 1
                        missed = ata_for_pta > pta_min
                        if missed:
                            d['pta_miss'] += 1
                        if driver_id:
                            driver_stats[driver_id]['pta_eligible'] += 1
                            if missed:
                                driver_stats[driver_id]['pta_miss'] += 1

    return day_ata, driver_stats


def _aggregate_driver_satisfaction(driver_sat_rows):
    """Aggregate per-driver satisfaction from GROUP BY query results.

    Returns dict[driver_id] = {name, total, ts_overall, n_rt, ts_rt, n_tech, ts_tech, n_info, ts_info}
    """
    _empty = lambda: {'name': None, 'total': 0,
                      'ts_overall': 0, 'ts_rt': 0, 'n_rt': 0,
                      'ts_tech': 0, 'n_tech': 0,
                      'ts_info': 0, 'n_info': 0}
    result = defaultdict(_empty)
    for r in driver_sat_rows or []:
        did = r.get('did')
        if not did:
            continue
        cnt = r.get('cnt', 0) or 0
        ds = result[did]
        ds['name'] = r.get('dname') or ds['name']
        ds['total'] += cnt
        if (r.get('sat') or '').strip().lower() == 'totally satisfied':
            ds['ts_overall'] += cnt
        for field, n_key, ts_key in [('rt_sat', 'n_rt', 'ts_rt'),
                                      ('tech_sat', 'n_tech', 'ts_tech'),
                                      ('info_sat', 'n_info', 'ts_info')]:
            val = (r.get(field) or '').strip().lower()
            if val:
                ds[n_key] += cnt
                if val == 'totally satisfied':
                    ds[ts_key] += cnt
    return result


def _pct(num, den):
    """Safe percentage: round(100 * num / den) or None."""
    return round(100 * num / den) if den else None
