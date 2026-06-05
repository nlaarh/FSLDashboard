"""Garage driver revenue & labor — per-driver revenue attribution from billing WOLIs.

Only meaningful for On-Platform Contractor garages (e.g. Transit Auto 076DO/076D).
Revenue = sum of WOLI cost fields (Basic + Plus + Premier + RV + Other) on billing WOLIs
          (PricebookEntryId != null). Populated immediately on call completion, before
          invoicing — more complete than Total_Amount_Invoiced__c which requires billing cycle.
Hours  = AssetHistory.ERS_Driver__c login/logout sessions across all ERS trucks.

Two endpoints:
  GET /api/garages/{territory_id}/driver-revenue            — main chart data
  GET /api/garages/{territory_id}/driver-revenue/{driver}/daily — drill-down
"""

import re
from datetime import date, timedelta, datetime, timezone
from collections import defaultdict
from itertools import groupby
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, Query, Request
from sf_client import sf_query_all, sf_parallel, sanitize_soql
from utils import parse_dt, _ET
import cache
from permissions import require_feature

router = APIRouter()

_SF_BASE = 'https://aaawcny.lightning.force.com'

# ── Helpers ───────────────────────────────────────────────────────────────────

_TERR_SUFFIX = re.compile(r'\s*0\d{2}D[O]?\s*$', re.IGNORECASE)

def _clean(name: str) -> str:
    """Strip territory-code suffixes like ' 076DO' from driver names."""
    return _TERR_SUFFIX.sub('', name or '').strip()


def _get_trucks() -> list[str]:
    """Return ERS truck IDs, cached for 6 hours (list rarely changes)."""
    _KEY = 'ers_truck_ids'
    cached = cache.get(_KEY)
    if cached is not None:
        return cached
    rows = sf_query_all("SELECT Id FROM Asset WHERE RecordType.Name = 'ERS Truck'")
    ids  = [r['Id'] for r in rows]
    cache.put(_KEY, ids, ttl=6 * 3600)
    return ids


def _sf_submit_batches(pool: ThreadPoolExecutor, soql_prefix: str,
                       id_list: list, batch: int = 200) -> list:
    """Submit batched IN-clause queries to the pool; return list of futures."""
    futures = []
    for i in range(0, len(id_list), batch):
        chunk   = id_list[i:i + batch]
        ids_str = "'" + "','".join(chunk) + "'"
        futures.append(pool.submit(sf_query_all,
                                   f"{soql_prefix} WHERE Id IN ({ids_str})"))
    return futures


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
    # Extend AH window ±1 day so sessions spanning the period boundary are captured
    ah_since = f"{(date.fromisoformat(start_date) - timedelta(days=1)).isoformat()}T00:00:00Z"
    ah_until = f"{(date.fromisoformat(end_date) + timedelta(days=2)).isoformat()}T00:00:00Z"

    # Phase 1 — ONE merged AR+SA query (trucks served from cache)
    # Merging SA fields into AR query eliminates a separate SF round-trip.
    truck_ids = _get_trucks()   # cached 6h — never blocks after first call
    ars = sf_query_all(f"""
        SELECT ServiceAppointmentId, ServiceResource.Name,
               ServiceAppointment.ParentRecordId,
               ServiceAppointment.WorkType.Name,
               ServiceAppointment.CreatedDate
        FROM AssignedResource
        WHERE ServiceAppointment.ServiceTerritoryId = '{territory_id}'
        AND ServiceAppointment.Status = 'Completed'
        AND ServiceAppointment.CreatedDate >= {since}
        AND ServiceAppointment.CreatedDate < {until}
        AND ServiceResource.IsActive = true
    """)

    if not ars:
        return {'summary': {'total_attributed': 0, 'total_battery_revenue': 0,
                            'total_member_collected': 0,
                            'total_drivers': 0, 'total_calls': 0,
                            'note': 'No tracked driver data found for this garage/period.'},
                'drivers': []}

    # Build SA lookup maps from the merged AR rows
    def _sa_of(ar: dict) -> dict:
        return ar.get('ServiceAppointment') or {}

    def _wt_of(ar: dict) -> str:
        return (_sa_of(ar).get('WorkType') or {}).get('Name') or 'Other'

    sa_to_woli:         dict[str, str]   = {}
    sa_to_woli_battery: dict[str, str]   = {}
    sa_to_type:         dict[str, str]   = {}
    sa_to_date:         dict[str, str]   = {}

    for ar in ars:
        sa_id  = ar['ServiceAppointmentId']
        sa     = _sa_of(ar)
        wt     = _wt_of(ar)
        is_drop = 'drop' in wt.lower()
        is_batt = 'battery' in wt.lower()
        woli_id = sa.get('ParentRecordId')
        if woli_id and not is_drop and not is_batt:
            sa_to_woli[sa_id] = woli_id
        if woli_id and is_batt and not is_drop:
            sa_to_woli_battery[sa_id] = woli_id
        sa_to_type[sa_id] = wt
        sa_dt = parse_dt(sa.get('CreatedDate'))
        sa_to_date[sa_id] = (
            sa_dt.astimezone(_ET).date().isoformat() if sa_dt
            else datetime.now(timezone.utc).astimezone(_ET).date().isoformat()
        )

    woli_ids     = list(set(list(sa_to_woli.values()) + list(sa_to_woli_battery.values())))
    driver_names = set(_clean(ar['ServiceResource']['Name']) for ar in ars)

    # Phase 2 + 3 OVERLAPPED — key optimisation:
    # Submit WOLI batches AND AssetHistory batches simultaneously.
    # The moment WOLI batches finish we have WO IDs and immediately fire Phase 3
    # (billing + member) WITHOUT waiting for AssetHistory to complete.
    # AssetHistory and Phase 3 then run concurrently.
    with ThreadPoolExecutor(max_workers=24) as pool:

        # Submit WOLI batches
        woli_futs = []
        for i in range(0, max(len(woli_ids), 1), 200):
            chunk   = woli_ids[i:i + 200]
            ids_str = "'" + "','".join(chunk) + "'"
            woli_futs.append(pool.submit(
                sf_query_all,
                f"SELECT Id, WorkOrderId FROM WorkOrderLineItem WHERE Id IN ({ids_str})"
            ))

        # Submit AssetHistory batches
        ah_futs = []
        for i in range(0, max(len(truck_ids), 1), 200):
            chunk   = truck_ids[i:i + 200]
            ids_str = "'" + "','".join(chunk) + "'"
            ah_futs.append(pool.submit(
                sf_query_all,
                f"""SELECT AssetId, OldValue, NewValue, CreatedDate
                    FROM AssetHistory
                    WHERE AssetId IN ({ids_str})
                    AND Field = 'ERS_Driver__c'
                    AND CreatedDate >= {ah_since} AND CreatedDate < {ah_until}"""
            ))

        # Collect WOLI results (needed to build WO ID list for Phase 3)
        service_wolis: list = []
        for f in woli_futs:
            service_wolis.extend(f.result())
        woli_to_wo = {w['Id']: w['WorkOrderId'] for w in service_wolis}
        wo_ids     = list(set(woli_to_wo.values()))

        # Phase 3 fires NOW — AssetHistory is still running in other threads
        billing_fut = member_fut = None
        if wo_ids:
            billing_fut = pool.submit(lambda ids=wo_ids: _batch_parallel(
                "SELECT WorkOrderId, PricebookEntryId, Basic_Cost__c, Plus_Cost__c, "
                "Premier_Cost__c, RV_Cost__c, Other_Cost__c FROM WorkOrderLineItem",
                "WorkOrderId", ids,
            ))
            member_fut = pool.submit(lambda ids=wo_ids: _batch_parallel(
                "SELECT Id, WorkOrderNumber, Est_Tow_Over_Mileage_Cost_to_Member1__c "
                "FROM WorkOrder",
                "Id", ids,
            ))

        # Collect AssetHistory (likely finishes while Phase 3 is running)
        ah_all: list = []
        for f in ah_futs:
            ah_all.extend(f.result())

        # Collect Phase 3 (likely done by now)
        billing_wolis = billing_fut.result() if billing_fut else []
        member_wos    = member_fut.result()   if member_fut  else []

    wo_member: dict[str, float] = {
        w['Id']: (w.get('Est_Tow_Over_Mileage_Cost_to_Member1__c') or 0.0)
        for w in member_wos
    }
    wo_number_map: dict[str, str] = {
        w['Id']: (w.get('WorkOrderNumber') or w['Id'])
        for w in member_wos
    }
    wo_to_billing: dict[str, float] = {}
    for w in billing_wolis:
        if not w.get('PricebookEntryId'):  # skip service WOLIs (work-type descriptors, always $0)
            continue
        amt = (
            (w.get('Basic_Cost__c')   or 0.0) +
            (w.get('Plus_Cost__c')    or 0.0) +
            (w.get('Premier_Cost__c') or 0.0) +
            (w.get('RV_Cost__c')      or 0.0) +
            (w.get('Other_Cost__c')   or 0.0)
        )
        if amt > 0:
            wo_id = w['WorkOrderId']
            wo_to_billing[wo_id] = wo_to_billing.get(wo_id, 0.0) + amt

    # Attribute revenue to drivers
    driver_data: dict[str, dict] = defaultdict(lambda: {
        'calls': 0, 'calls_by_type': defaultdict(int),
        'revenue': 0.0, 'wo_seen': set(),
        'battery_revenue': 0.0, 'battery_wo_seen': set(),
        'member_collected': 0.0,
        'member_aaa_billed': 0.0,
        'member_wo_details': [],
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
                mc_amt = wo_member.get(wo_id, 0.0)
                driver_data[driver]['member_collected'] += mc_amt
                if mc_amt > 0:
                    aaa_for_wo = wo_to_billing.get(wo_id, 0.0)
                    driver_data[driver]['member_aaa_billed'] += aaa_for_wo
                    driver_data[driver]['member_wo_details'].append({
                        'wo_id':      wo_id,
                        'wo_number':  wo_number_map.get(wo_id, wo_id),
                        'date':       sa_to_date.get(sa_id, ''),
                        'aaa_billed': round(aaa_for_wo, 2),
                        'amount':     round(mc_amt, 2),
                        'sf_url':     f'{_SF_BASE}/{wo_id}',
                    })

    # Process AssetHistory (fetched in phase 2)
    hours_map = _process_asset_hours(ah_all, driver_names, ah_since, ah_until)

    # Merge and sort
    drivers = []
    for driver, d in sorted(driver_data.items(), key=lambda x: -x[1]['revenue']):
        rev = round(d['revenue'], 2)
        mc  = round(d['member_collected'], 2)
        hrs = hours_map.get(driver, {})
        h   = hrs.get('total_hours', 0.0)
        drivers.append({
            'name':              driver,
            'calls':             d['calls'],
            'calls_by_type':     dict(d['calls_by_type']),
            'revenue':           rev,
            'battery_revenue':   round(d['battery_revenue'], 2),
            'battery_calls':     d['calls_by_type'].get('Battery', 0) + d['calls_by_type'].get('Jumpstart', 0),
            'member_collected':  mc,
            'member_aaa_billed': round(d['member_aaa_billed'], 2),
            'total_revenue':     round(rev + mc, 2),
            'work_orders':       len(d['wo_seen']) + len(d['battery_wo_seen']),
            'hours':             h,
            'shift_days':        hrs.get('shift_days', 0),
            'rev_per_hour':      round(rev / h, 1) if h > 0 else 0.0,
            'member_wo_details': sorted(d['member_wo_details'], key=lambda x: x['date']),
        })

    total_rev    = sum(d['revenue']          for d in drivers)
    total_batt   = sum(d['battery_revenue']  for d in drivers)
    total_mc     = sum(d['member_collected'] for d in drivers)
    total_calls  = sum(d['calls']            for d in drivers)
    return {
        'period':  {'start': start_date, 'end': end_date},
        'summary': {
            'total_attributed':        round(total_rev, 2),
            'total_battery_revenue':   round(total_batt, 2),
            'total_member_collected':  round(total_mc, 2),
            'total_drivers':           len(drivers),
            'total_calls':             total_calls,
        },
        'drivers': drivers,
    }


# ── Daily drill-down compute ──────────────────────────────────────────────────

def _compute_driver_daily(territory_id: str, driver_name: str,
                          start_date: str, end_date: str) -> dict:
    since = f"{start_date}T00:00:00Z"
    until = f"{(date.fromisoformat(end_date) + timedelta(days=1)).isoformat()}T00:00:00Z"
    ah_since = f"{(date.fromisoformat(start_date) - timedelta(days=1)).isoformat()}T00:00:00Z"
    ah_until = f"{(date.fromisoformat(end_date) + timedelta(days=2)).isoformat()}T00:00:00Z"
    safe_name = sanitize_soql(driver_name)

    # Phase 1 — single AR+SA query; trucks from cache
    truck_ids = _get_trucks()
    ars = sf_query_all(f"""
        SELECT ServiceAppointmentId, ServiceAppointment.CreatedDate,
               ServiceAppointment.WorkType.Name, ServiceAppointment.ParentRecordId
        FROM AssignedResource
        WHERE ServiceAppointment.ServiceTerritoryId = '{territory_id}'
        AND ServiceAppointment.Status = 'Completed'
        AND ServiceAppointment.CreatedDate >= {since}
        AND ServiceAppointment.CreatedDate < {until}
        AND ServiceResource.Name LIKE '{safe_name}%'
        AND ServiceResource.IsActive = true
    """)

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

    woli_ids = list(woli_ids_main | woli_ids_battery)

    # Phase 2+3 overlapped (same pattern as _compute_revenue)
    with ThreadPoolExecutor(max_workers=24) as pool:

        woli_futs = []
        for i in range(0, max(len(woli_ids), 1), 200):
            chunk   = woli_ids[i:i + 200]
            ids_str = "'" + "','".join(chunk) + "'"
            woli_futs.append(pool.submit(
                sf_query_all,
                f"SELECT Id, WorkOrderId FROM WorkOrderLineItem WHERE Id IN ({ids_str})"
            ))

        ah_futs = []
        for i in range(0, max(len(truck_ids), 1), 200):
            chunk   = truck_ids[i:i + 200]
            ids_str = "'" + "','".join(chunk) + "'"
            ah_futs.append(pool.submit(
                sf_query_all,
                f"""SELECT AssetId, OldValue, NewValue, CreatedDate
                    FROM AssetHistory
                    WHERE AssetId IN ({ids_str})
                    AND Field = 'ERS_Driver__c'
                    AND CreatedDate >= {ah_since} AND CreatedDate < {ah_until}"""
            ))

        service_wolis: list = []
        for f in woli_futs:
            service_wolis.extend(f.result())
        woli_to_wo = {w['Id']: w['WorkOrderId'] for w in service_wolis}
        wo_ids     = list(set(woli_to_wo.values()))

        # Phase 3 fires immediately while AssetHistory still running
        billing_fut = member_fut = None
        if wo_ids:
            billing_fut = pool.submit(lambda ids=wo_ids: _batch_parallel(
                "SELECT WorkOrderId, PricebookEntryId, Basic_Cost__c, Plus_Cost__c, "
                "Premier_Cost__c, RV_Cost__c, Other_Cost__c FROM WorkOrderLineItem",
                "WorkOrderId", ids,
            ))
            member_fut = pool.submit(lambda ids=wo_ids: _batch_parallel(
                "SELECT Id, WorkOrderNumber, Est_Tow_Over_Mileage_Cost_to_Member1__c "
                "FROM WorkOrder",
                "Id", ids,
            ))

        ah_all: list = []
        for f in ah_futs:
            ah_all.extend(f.result())

        billing_wolis = billing_fut.result() if billing_fut else []
        member_wos    = member_fut.result()   if member_fut  else []

    wo_member: dict[str, float] = {
        w['Id']: (w.get('Est_Tow_Over_Mileage_Cost_to_Member1__c') or 0.0)
        for w in member_wos
    }
    wo_number_map: dict[str, str] = {
        w['Id']: (w.get('WorkOrderNumber') or w['Id'])
        for w in member_wos
    }
    wo_to_billing: dict[str, float] = {}
    for w in billing_wolis:
        if not w.get('PricebookEntryId'):  # skip service WOLIs (always $0)
            continue
        amt = (
            (w.get('Basic_Cost__c')   or 0.0) +
            (w.get('Plus_Cost__c')    or 0.0) +
            (w.get('Premier_Cost__c') or 0.0) +
            (w.get('RV_Cost__c')      or 0.0) +
            (w.get('Other_Cost__c')   or 0.0)
        )
        if amt > 0:
            wo = w['WorkOrderId']
            wo_to_billing[wo] = wo_to_billing.get(wo, 0.0) + amt

    # Aggregate by day
    day_data: dict[str, dict] = defaultdict(lambda: {
        'calls_by_type': defaultdict(int),
        'revenue': 0.0, 'wo_seen': set(),
        'battery_revenue': 0.0, 'battery_wo_seen': set(),
        'member_collected': 0.0,
        'wo_details': [],
    })
    for sa_id, info in sa_day_map.items():
        d = info['date']
        day_data[d]['calls_by_type'][info['work_type']] += 1
        woli_id = info['woli_id']
        if woli_id:
            wo_id = woli_to_wo.get(woli_id)
            if wo_id and wo_id not in day_data[d]['wo_seen']:
                day_data[d]['wo_seen'].add(wo_id)
                amt = wo_to_billing.get(wo_id, 0.0)
                day_data[d]['revenue'] += amt
                day_data[d]['member_collected'] += wo_member.get(wo_id, 0.0)
                day_data[d]['wo_details'].append({
                    'wo_id': wo_id,
                    'wo_number': wo_number_map.get(wo_id, wo_id),
                    'amount': round(amt, 2),
                    'type': info['work_type'],
                    'sf_url': f'{_SF_BASE}/{wo_id}',
                })
        batt_woli_id = info.get('batt_woli_id')
        if batt_woli_id:
            wo_id = woli_to_wo.get(batt_woli_id)
            if wo_id and wo_id not in day_data[d]['battery_wo_seen']:
                day_data[d]['battery_wo_seen'].add(wo_id)
                amt = wo_to_billing.get(wo_id, 0.0)
                day_data[d]['battery_revenue'] += amt
                day_data[d]['wo_details'].append({
                    'wo_id': wo_id,
                    'wo_number': wo_number_map.get(wo_id, wo_id),
                    'amount': round(amt, 2),
                    'type': info['work_type'],
                    'sf_url': f'{_SF_BASE}/{wo_id}',
                })

    # Process AssetHistory (fetched in phase 2, filter to this one driver)
    hours_data    = _process_asset_hours(ah_all, {driver_name}, ah_since, ah_until)
    hours_by_date = {
        k: v for k, v in hours_data.get(driver_name, {}).get('by_date', {}).items()
        if start_date <= k <= end_date
    }

    # Build sorted daily rows
    all_dates = sorted(set(day_data.keys()) | set(hours_by_date.keys()))
    rows = []
    for d in all_dates:
        dd = day_data.get(d, {})
        rows.append({
            'date':              d,
            'calls_by_type':     dict(dd.get('calls_by_type', {})),
            'total_calls':       sum(dd.get('calls_by_type', {}).values()),
            'revenue':           round(dd.get('revenue', 0.0), 2),
            'battery_revenue':   round(dd.get('battery_revenue', 0.0), 2),
            'member_collected':  round(dd.get('member_collected', 0.0), 2),
            'hours':             round(hours_by_date.get(d, 0.0), 1),
            'wo_details':        sorted(dd.get('wo_details', []), key=lambda x: -x['amount']),
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
    request: Request = None,
):
    require_feature("garage.revenue_performance", request)
    tid  = sanitize_soql(territory_id)
    sd   = sanitize_soql(start_date)
    ed   = sanitize_soql(end_date)
    key  = f"driver_rev_{tid}_{sd}_{ed}"
    if bust:
        cache.invalidate(key)
        cache.disk_invalidate(key)
    return cache.stale_while_revalidate(key, lambda: _compute_revenue(tid, sd, ed), ttl=3600, stale_ttl=86400)


@router.get("/api/garages/{territory_id}/driver-revenue/{driver_name}/daily")
def get_driver_daily(
    territory_id: str,
    driver_name:  str,
    start_date: str = Query(...),
    end_date:   str = Query(...),
    request: Request = None,
):
    require_feature("garage.revenue_performance", request)
    tid    = sanitize_soql(territory_id)
    driver = sanitize_soql(driver_name)
    sd     = sanitize_soql(start_date)
    ed     = sanitize_soql(end_date)
    key    = f"driver_daily_{tid}_{driver}_{sd}_{ed}"
    return cache.stale_while_revalidate(
        key, lambda: _compute_driver_daily(tid, driver, sd, ed), ttl=3600, stale_ttl=86400
    )
