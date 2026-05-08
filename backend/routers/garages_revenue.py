"""Garage driver revenue & labor — per-driver revenue attribution from billing WOLIs.

Only meaningful for On-Platform Contractor garages (e.g. Transit Auto 076DO/076D).
Revenue = WorkOrderLineItem.Total_Amount_Invoiced__c for completed in-period calls.
Hours  = AssetHistory.ERS_Driver__c login/logout sessions across all ERS trucks.

Two endpoints:
  GET /api/garages/{territory_id}/driver-revenue            — main chart data
  GET /api/garages/{territory_id}/driver-revenue/{driver}/daily — drill-down
"""

import re
from datetime import date, timedelta, datetime, timezone
from collections import defaultdict
from itertools import groupby

from fastapi import APIRouter, Query
from sf_client import sf_query_all, sf_parallel, sanitize_soql
from utils import parse_dt, _ET
import cache

router = APIRouter()

# ── Helpers ───────────────────────────────────────────────────────────────────

_TERR_SUFFIX = re.compile(r'\s*0\d{2}D[O]?\s*$', re.IGNORECASE)

def _clean(name: str) -> str:
    """Strip territory-code suffixes like ' 076DO' from driver names."""
    return _TERR_SUFFIX.sub('', name or '').strip()


def _batch_parallel(soql_prefix: str, filter_field: str, id_list: list, batch: int = 200) -> list:
    """Run SOQL IN-batch queries in parallel using sf_parallel."""
    if not id_list:
        return []
    chunks = [id_list[i:i+batch] for i in range(0, len(id_list), batch)]
    if len(chunks) == 1:
        ids_str = "'" + "','".join(chunks[0]) + "'"
        return sf_query_all(f"{soql_prefix} WHERE {filter_field} IN ({ids_str})")
    fns = {}
    for idx, chunk in enumerate(chunks):
        ids_str = "'" + "','".join(chunk) + "'"
        fns[f'b{idx}'] = (lambda s=ids_str: sf_query_all(f"{soql_prefix} WHERE {filter_field} IN ({s})"))
    raw = sf_parallel(**fns)
    return [r for v in raw.values() for r in v]


def _process_asset_hours(ah_all: list, driver_names: set, since: str, until: str) -> dict:
    """Process pre-fetched AssetHistory rows into per-driver hour stats."""
    def _is_sf_id(v):
        return isinstance(v, str) and len(v) in (15, 18) and v[:3] in ('005', '0Hn')

    name_events = []
    for r in ah_all:
        old_v = r.get('OldValue') or ''
        new_v = r.get('NewValue') or ''
        if _is_sf_id(old_v) or _is_sf_id(new_v):
            continue
        old_c = _clean(old_v)
        new_c = _clean(new_v)
        if old_c not in driver_names and new_c not in driver_names:
            continue
        ts = parse_dt(r.get('CreatedDate'))
        if not ts:
            continue
        name_events.append({'asset': r['AssetId'], 'old': old_c, 'new': new_c, 'ts': ts})

    name_events.sort(key=lambda e: (e['asset'], e['ts']))
    open_logins = {}
    driver_sessions = defaultdict(list)

    for asset, events in groupby(name_events, key=lambda e: e['asset']):
        for ev in events:
            old_d, new_d = ev['old'], ev['new']
            if old_d and asset in open_logins and open_logins[asset][0] == old_d:
                login_ts = open_logins.pop(asset)[1]
                driver_sessions[old_d].append((login_ts, ev['ts']))
            if new_d:
                open_logins[asset] = (new_d, ev['ts'])

    MAX_H = 16.0
    result = {}
    for driver, sessions in driver_sessions.items():
        total_h = sum(
            min((lo - li).total_seconds() / 3600, MAX_H)
            for li, lo in sessions
        )
        shift_days = len(set(li.astimezone(_ET).date() for li, _ in sessions))
        by_date = defaultdict(float)
        for li, lo in sessions:
            d_key = li.astimezone(_ET).date().isoformat()
            by_date[d_key] += min((lo - li).total_seconds() / 3600, MAX_H)
        result[driver] = {
            'total_hours': round(total_h, 1),
            'shift_days':  shift_days,
            'sessions':    len(sessions),
            'by_date':     {k: round(v, 1) for k, v in by_date.items()},
        }
    return result


def _work_type(sa: dict) -> str:
    wt = sa.get('WorkType')
    return (wt.get('Name') if wt else None) or 'Other'


def _is_drop_off(sa: dict) -> bool:
    return 'drop' in _work_type(sa).lower()

def _is_battery(sa: dict) -> bool:
    return 'battery' in _work_type(sa).lower()


# ── Main compute ─────────────────────────────────────────────────────────────

def _compute_revenue(territory_id: str, start_date: str, end_date: str) -> dict:
    since = f"{start_date}T00:00:00Z"
    until = f"{(date.fromisoformat(end_date) + timedelta(days=1)).isoformat()}T00:00:00Z"

    # Phase 1 — SAs + ARs + trucks all in parallel
    p1 = sf_parallel(
        sas=lambda: sf_query_all(f"""
            SELECT Id, ParentRecordId, WorkType.Name
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
            AND Status = 'Completed'
            AND CreatedDate >= {since} AND CreatedDate < {until}
        """),
        ars=lambda: sf_query_all(f"""
            SELECT ServiceAppointmentId, ServiceResource.Name
            FROM AssignedResource
            WHERE ServiceAppointment.ServiceTerritoryId = '{territory_id}'
            AND ServiceAppointment.Status = 'Completed'
            AND ServiceAppointment.CreatedDate >= {since}
            AND ServiceAppointment.CreatedDate < {until}
            AND ServiceResource.IsActive = true
        """),
        trucks=lambda: sf_query_all("SELECT Id FROM Asset WHERE RecordType.Name = 'ERS Truck'"),
    )
    sas, ars, trucks = p1['sas'], p1['ars'], p1['trucks']

    if not ars:
        return {'summary': {'total_attributed': 0, 'total_battery_revenue': 0,
                            'total_drivers': 0, 'total_calls': 0,
                            'note': 'No tracked driver data found for this garage/period.'},
                'drivers': []}

    # Build SA lookup maps
    sa_to_woli         = {s['Id']: s.get('ParentRecordId') for s in sas
                          if not _is_drop_off(s) and not _is_battery(s)}
    sa_to_woli_battery = {s['Id']: s.get('ParentRecordId') for s in sas
                          if _is_battery(s) and not _is_drop_off(s)}
    sa_to_type         = {s['Id']: _work_type(s) for s in sas}

    woli_ids     = list(set(
        [v for v in sa_to_woli.values() if v] +
        [v for v in sa_to_woli_battery.values() if v]
    ))
    driver_names = set(_clean(ar['ServiceResource']['Name']) for ar in ars)
    truck_ids    = [t['Id'] for t in trucks]

    # Phase 2 — service WOLI batches + AssetHistory batches, ALL in parallel
    p2_fns: dict = {}
    for idx, chunk in enumerate([woli_ids[i:i+200] for i in range(0, len(woli_ids), 200)]):
        ids_str = "'" + "','".join(chunk) + "'"
        p2_fns[f'woli_{idx}'] = (lambda s=ids_str:
            sf_query_all(f"SELECT Id, WorkOrderId FROM WorkOrderLineItem WHERE Id IN ({s})"))
    for idx, chunk in enumerate([truck_ids[i:i+200] for i in range(0, len(truck_ids), 200)]):
        ids_str = "'" + "','".join(chunk) + "'"
        p2_fns[f'ah_{idx}'] = (lambda s=ids_str: sf_query_all(f"""
            SELECT AssetId, OldValue, NewValue, CreatedDate
            FROM AssetHistory
            WHERE AssetId IN ({s})
            AND Field = 'ERS_Driver__c'
            AND CreatedDate >= {since} AND CreatedDate < {until}
        """))

    p2 = sf_parallel(**p2_fns) if p2_fns else {}
    service_wolis = [r for k, v in p2.items() if k.startswith('woli_') for r in v]
    ah_all        = [r for k, v in p2.items() if k.startswith('ah_')   for r in v]

    woli_to_wo = {w['Id']: w['WorkOrderId'] for w in service_wolis}
    wo_ids     = list(set(woli_to_wo.values()))

    # Phase 3 — billing WOLI batches in parallel (depends on wo_ids from phase 2)
    billing_wolis = _batch_parallel(
        "SELECT WorkOrderId, Total_Amount_Invoiced__c FROM WorkOrderLineItem",
        "WorkOrderId", wo_ids,
    )
    wo_to_billing: dict[str, float] = {}
    for w in billing_wolis:
        amt = w.get('Total_Amount_Invoiced__c') or 0.0
        if amt > 0:
            wo_id = w['WorkOrderId']
            wo_to_billing[wo_id] = wo_to_billing.get(wo_id, 0.0) + amt

    # Attribute revenue to drivers
    driver_data: dict[str, dict] = defaultdict(lambda: {
        'calls': 0, 'calls_by_type': defaultdict(int),
        'revenue': 0.0, 'wo_seen': set(),
        'battery_revenue': 0.0, 'battery_wo_seen': set(),
    })
    for ar in ars:
        sa_id  = ar['ServiceAppointmentId']
        driver = _clean(ar['ServiceResource']['Name'])
        work_type = sa_to_type.get(sa_id, 'Other')
        driver_data[driver]['calls'] += 1
        driver_data[driver]['calls_by_type'][work_type] += 1

        batt_woli = sa_to_woli_battery.get(sa_id)
        if batt_woli:
            wo_id = woli_to_wo.get(batt_woli)
            if wo_id and wo_id not in driver_data[driver]['battery_wo_seen']:
                driver_data[driver]['battery_wo_seen'].add(wo_id)
                driver_data[driver]['battery_revenue'] += wo_to_billing.get(wo_id, 0.0)

        woli_id = sa_to_woli.get(sa_id)
        if woli_id:
            wo_id = woli_to_wo.get(woli_id)
            if wo_id and wo_id not in driver_data[driver]['wo_seen']:
                driver_data[driver]['wo_seen'].add(wo_id)
                driver_data[driver]['revenue'] += wo_to_billing.get(wo_id, 0.0)

    # Process AssetHistory (fetched in phase 2)
    hours_map = _process_asset_hours(ah_all, driver_names, since, until)

    # Merge and sort
    drivers = []
    for driver, d in sorted(driver_data.items(), key=lambda x: -x[1]['revenue']):
        rev = round(d['revenue'], 2)
        hrs = hours_map.get(driver, {})
        h   = hrs.get('total_hours', 0.0)
        drivers.append({
            'name':            driver,
            'calls':           d['calls'],
            'calls_by_type':   dict(d['calls_by_type']),
            'revenue':         rev,
            'battery_revenue': round(d['battery_revenue'], 2),
            'battery_calls':   d['calls_by_type'].get('Battery', 0) + d['calls_by_type'].get('Jumpstart', 0),
            'hours':           h,
            'shift_days':      hrs.get('shift_days', 0),
            'rev_per_hour':    round(rev / h, 1) if h > 0 else 0.0,
        })

    total_rev   = sum(d['revenue']         for d in drivers)
    total_batt  = sum(d['battery_revenue'] for d in drivers)
    total_calls = sum(d['calls']           for d in drivers)
    return {
        'period':  {'start': start_date, 'end': end_date},
        'summary': {
            'total_attributed':      round(total_rev, 2),
            'total_battery_revenue': round(total_batt, 2),
            'total_drivers':         len(drivers),
            'total_calls':           total_calls,
        },
        'drivers': drivers,
    }


# ── Daily drill-down compute ──────────────────────────────────────────────────

def _compute_driver_daily(territory_id: str, driver_name: str,
                          start_date: str, end_date: str) -> dict:
    since = f"{start_date}T00:00:00Z"
    until = f"{(date.fromisoformat(end_date) + timedelta(days=1)).isoformat()}T00:00:00Z"
    safe_name = sanitize_soql(driver_name)

    # Get SAs via ARs for this driver (LIKE match handles territory suffix)
    raw = sf_parallel(
        ars=lambda: sf_query_all(f"""
            SELECT ServiceAppointmentId, ServiceAppointment.CreatedDate,
                   ServiceAppointment.WorkType.Name, ServiceAppointment.ParentRecordId
            FROM AssignedResource
            WHERE ServiceAppointment.ServiceTerritoryId = '{territory_id}'
            AND ServiceAppointment.Status = 'Completed'
            AND ServiceAppointment.CreatedDate >= {since}
            AND ServiceAppointment.CreatedDate < {until}
            AND ServiceResource.Name LIKE '{safe_name}%'
            AND ServiceResource.IsActive = true
        """),
        trucks=lambda: sf_query_all("SELECT Id FROM Asset WHERE RecordType.Name = 'ERS Truck'"),
    )
    trucks = raw['trucks']
    ars = raw['ars']

    # Revenue lookup — main excludes drop-off AND battery; battery tracked separately
    woli_ids_main    = set()
    woli_ids_battery = set()
    sa_day_map = {}   # sa_id -> {date, work_type, woli_id, batt_woli_id}
    for ar in ars:
        sa = ar.get('ServiceAppointment') or {}
        sa_id    = ar['ServiceAppointmentId']
        wt_name  = (sa.get('WorkType') or {}).get('Name') or 'Other'
        sa_dt    = parse_dt(sa.get('CreatedDate'))
        day      = sa_dt.astimezone(_ET).date().isoformat() if sa_dt else 'unknown'
        is_drop  = 'drop' in wt_name.lower()
        is_batt  = 'battery' in wt_name.lower()
        woli_id      = sa.get('ParentRecordId') if (not is_drop and not is_batt) else None
        batt_woli_id = sa.get('ParentRecordId') if (is_batt and not is_drop)    else None
        sa_day_map[sa_id] = {'date': day, 'work_type': wt_name,
                             'woli_id': woli_id, 'batt_woli_id': batt_woli_id}
        if woli_id:
            woli_ids_main.add(woli_id)
        if batt_woli_id:
            woli_ids_battery.add(batt_woli_id)

    woli_ids  = list(woli_ids_main | woli_ids_battery)
    truck_ids = [t['Id'] for t in trucks]

    # Phase 2 — service WOLI batches + AssetHistory batches, ALL in parallel
    p2_fns: dict = {}
    for idx, chunk in enumerate([woli_ids[i:i+200] for i in range(0, len(woli_ids), 200)]):
        ids_str = "'" + "','".join(chunk) + "'"
        p2_fns[f'woli_{idx}'] = (lambda s=ids_str:
            sf_query_all(f"SELECT Id, WorkOrderId FROM WorkOrderLineItem WHERE Id IN ({s})"))
    for idx, chunk in enumerate([truck_ids[i:i+200] for i in range(0, len(truck_ids), 200)]):
        ids_str = "'" + "','".join(chunk) + "'"
        p2_fns[f'ah_{idx}'] = (lambda s=ids_str: sf_query_all(f"""
            SELECT AssetId, OldValue, NewValue, CreatedDate
            FROM AssetHistory
            WHERE AssetId IN ({s})
            AND Field = 'ERS_Driver__c'
            AND CreatedDate >= {since} AND CreatedDate < {until}
        """))

    p2 = sf_parallel(**p2_fns) if p2_fns else {}
    service_wolis = [r for k, v in p2.items() if k.startswith('woli_') for r in v]
    ah_all        = [r for k, v in p2.items() if k.startswith('ah_')   for r in v]

    woli_to_wo = {w['Id']: w['WorkOrderId'] for w in service_wolis}
    wo_ids     = list(set(woli_to_wo.values()))

    # Phase 3 — billing WOLI batches in parallel
    billing_wolis = _batch_parallel(
        "SELECT WorkOrderId, Total_Amount_Invoiced__c FROM WorkOrderLineItem",
        "WorkOrderId", wo_ids,
    )
    wo_to_billing: dict[str, float] = {}
    for w in billing_wolis:
        amt = w.get('Total_Amount_Invoiced__c') or 0.0
        if amt > 0:
            wo = w['WorkOrderId']
            wo_to_billing[wo] = wo_to_billing.get(wo, 0.0) + amt

    # Aggregate by day
    day_data: dict[str, dict] = defaultdict(lambda: {
        'calls_by_type': defaultdict(int),
        'revenue': 0.0, 'wo_seen': set(),
        'battery_revenue': 0.0, 'battery_wo_seen': set(),
    })
    for sa_id, info in sa_day_map.items():
        d = info['date']
        day_data[d]['calls_by_type'][info['work_type']] += 1
        woli_id = info['woli_id']
        if woli_id:
            wo_id = woli_to_wo.get(woli_id)
            if wo_id and wo_id not in day_data[d]['wo_seen']:
                day_data[d]['wo_seen'].add(wo_id)
                day_data[d]['revenue'] += wo_to_billing.get(wo_id, 0.0)
        batt_woli_id = info.get('batt_woli_id')
        if batt_woli_id:
            wo_id = woli_to_wo.get(batt_woli_id)
            if wo_id and wo_id not in day_data[d]['battery_wo_seen']:
                day_data[d]['battery_wo_seen'].add(wo_id)
                day_data[d]['battery_revenue'] += wo_to_billing.get(wo_id, 0.0)

    # Process AssetHistory (fetched in phase 2, filter to this one driver)
    hours_data    = _process_asset_hours(ah_all, {driver_name}, since, until)
    hours_by_date = hours_data.get(driver_name, {}).get('by_date', {})

    # Build sorted daily rows
    all_dates = sorted(set(day_data.keys()) | set(hours_by_date.keys()))
    rows = []
    for d in all_dates:
        dd = day_data.get(d, {})
        rows.append({
            'date':            d,
            'calls_by_type':   dict(dd.get('calls_by_type', {})),
            'total_calls':     sum(dd.get('calls_by_type', {}).values()),
            'revenue':         round(dd.get('revenue', 0.0), 2),
            'battery_revenue': round(dd.get('battery_revenue', 0.0), 2),
            'hours':           round(hours_by_date.get(d, 0.0), 1),
        })

    # Work-type summary (battery uses batt_woli_id for revenue; others use woli_id)
    type_totals: dict[str, dict] = defaultdict(lambda: {'count': 0, 'revenue': 0.0})
    wo_seen_global: set = set()
    for sa_id, info in sa_day_map.items():
        wt = info['work_type']
        type_totals[wt]['count'] += 1
        woli_id = info.get('batt_woli_id') if 'battery' in wt.lower() else info['woli_id']
        if woli_id:
            wo_id = woli_to_wo.get(woli_id)
            if wo_id and wo_id not in wo_seen_global:
                wo_seen_global.add(wo_id)
                type_totals[wt]['revenue'] += wo_to_billing.get(wo_id, 0.0)

    type_summary = sorted([
        {
            'type':         wt,
            'count':        d['count'],
            'revenue':      round(d['revenue'], 2),
            'avg_per_call': round(d['revenue'] / d['count'], 2) if d['count'] > 0 else 0.0,
        }
        for wt, d in type_totals.items()
    ], key=lambda x: -x['count'])

    return {
        'driver': driver_name,
        'period': {'start': start_date, 'end': end_date},
        'days':         rows,
        'type_summary': type_summary,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/garages/{territory_id}/driver-revenue")
def get_driver_revenue(
    territory_id: str,
    start_date: str = Query(...),
    end_date:   str = Query(...),
    bust: bool = Query(False),
):
    tid  = sanitize_soql(territory_id)
    sd   = sanitize_soql(start_date)
    ed   = sanitize_soql(end_date)
    key  = f"driver_rev_{tid}_{sd}_{ed}"
    if bust:
        cache.invalidate(key)
        cache.disk_invalidate(key)
    return cache.cached_query_persistent(key, lambda: _compute_revenue(tid, sd, ed), max_stale_hours=26)


@router.get("/api/garages/{territory_id}/driver-revenue/{driver_name}/daily")
def get_driver_daily(
    territory_id: str,
    driver_name:  str,
    start_date: str = Query(...),
    end_date:   str = Query(...),
):
    tid    = sanitize_soql(territory_id)
    driver = sanitize_soql(driver_name)
    sd     = sanitize_soql(start_date)
    ed     = sanitize_soql(end_date)
    key    = f"driver_daily_{tid}_{driver}_{sd}_{ed}"
    return cache.cached_query_persistent(
        key, lambda: _compute_driver_daily(tid, driver, sd, ed), max_stale_hours=26
    )
