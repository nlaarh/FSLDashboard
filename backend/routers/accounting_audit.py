"""Accounting audit — heavy WOA audit computation."""

from sf_client import sf_query_all, sf_parallel, sanitize_soql
from sf_batch import batch_soql_parallel
from utils import parse_dt as _parse_dt
from fastapi import HTTPException
import cache, logging, os, requests as _requests
from datetime import timezone as _tz
from zoneinfo import ZoneInfo

log = logging.getLogger("accounting")
_ET = ZoneInfo("America/New_York")
from routers.accounting_calc import (
    _to_et, _fmt_et, _safe_float, _google_distance, _calc_recommendation, match_best_woli,
    _google_toll_check, _google_nearby_places, _scan_keywords, _parse_claimed_minutes,
    _SF_BASE, _TIME_CODES, _TOW_CODES, estimate_gvw,
)
from routers.accounting_audit_ai import call_audit_ai
from routers.accounting_photos import fetch_photos
from repositories import accounting

def _build_woa_data(woa_id: str) -> dict:
    """Build full WOA audit data WITHOUT the AI call (fast path, ~3-5s).
    Returns _ai_context and _garage_history as internal fields for the AI step."""
    import json as _json

    woa_rows = sf_query_all(f"""
        SELECT Id, Name, Quantity__c, Description__c, Internal_Notes__c,
               Status__c,
               Product__c, Product__r.Name,
               Work_Order_Line_Item__c,
               CreatedDate, CreatedById, LastModifiedById,
               CreatedBy.Name, LastModifiedBy.Name,
               Work_Order__c, Work_Order__r.WorkOrderNumber,
               Work_Order__r.ServiceTerritoryId,
               Work_Order__r.ServiceTerritory.Name,
               Work_Order__r.ServiceTerritory.ParentTerritory.Name,
               Work_Order__r.Facility_Name__c,
               Work_Order__r.Facility__r.Name,
               Work_Order__r.Latitude, Work_Order__r.Longitude,
               Work_Order__r.City, Work_Order__r.State,
               Work_Order__r.Tow_Destination__Latitude__s,
               Work_Order__r.Tow_Destination__Longitude__s,
               Work_Order__r.Vehicle_Make__c, Work_Order__r.Vehicle_Model__c,
               Work_Order__r.Weight_lbs__c, Work_Order__r.Vehicle_Group__c,
               Work_Order__r.ERS_En_Route_Miles__c,
               Work_Order__r.ERS_Estimated_En_Route_Miles__c,
               Work_Order__r.Tow_Miles__c,
               Work_Order__r.ERS_Estimated_Tow_Miles__c,
               Work_Order__r.ERS_En_Route_Date_Time__c,
               Work_Order__r.ERS_On_Location_Date_Time__c,
               Work_Order__r.Tax, Work_Order__r.GrandTotal,
               Work_Order__r.Basic_Cost__c, Work_Order__r.Plus_Cost__c,
               Work_Order__r.Other_Cost__c, Work_Order__r.Total_Amount_Invoiced__c,
               Work_Order__r.Trouble_Code__c, Work_Order__r.Resolution_Code__c,
               Work_Order__r.Clear_Code__c, Work_Order__r.Coverage__c,
               Work_Order__r.Tow_Call__c, Work_Order__r.Facility_ID__c,
               Work_Order__r.Number_of_Axles__c, Work_Order__r.AccountId,
               Work_Order__r.Facility_Contract__r.Name,
               Work_Order__r.Entitlement_Master__r.Name,
               Work_Order__r.Long_Tow_Used__c,
               Work_Order__r.Long_Tow_Miles__c,
               Work_Order__r.Type__c
        FROM ERS_Work_Order_Adjustment__c
        WHERE Id = '{woa_id}'
        LIMIT 1
    """)
    if not woa_rows:
        raise HTTPException(status_code=404, detail=f"WOA {woa_id} not found")

    woa = woa_rows[0]
    wo = woa.get('Work_Order__r') or {}
    wo_id = woa.get('Work_Order__c', '')
    territory_id = wo.get('ServiceTerritoryId', '')
    # On-platform = Fleet (100*/800*) or Contractors (e.g. 076DO) — any non-numeric facility ID.
    # Towbook facilities are purely numeric (496, 782, 4654…).
    _fac_id = (wo.get('Facility_ID__c') or '').strip()
    _is_on_platform = bool(_fac_id) and not _fac_id.isdigit()

    # SA fields used in Round 2 sa_direct query.
    _SA_FIELDS = """Id, AppointmentNumber, Status, SchedStartTime,
                   ServiceTerritoryId, ServiceTerritory.Name, ServiceTerritory.ParentTerritory.Name, ParentRecordId,
                   ERS_En_Route_Geolocation__Latitude__s,
                   ERS_En_Route_Geolocation__Longitude__s,
                   On_Location_Geolocation__Latitude__s,
                   On_Location_Geolocation__Longitude__s,
                   ERS_Completed_Geolocation__Latitude__s,
                   ERS_Completed_Geolocation__Longitude__s,
                   ERS_Membership_Level_Coverage__c,
                   WorkType.Name"""
    _account_id = wo.get('AccountId')
    _woa_date_str = (woa.get('CreatedDate') or '')[:10]
    _wo_number = wo.get('WorkOrderNumber', '')

    def _get_rflib_gps_r2():
        if _is_on_platform or not _wo_number:
            return []
        return sf_query_all(f"""
            SELECT ERS_Request__c, CreatedDate
            FROM rflib_Log__c
            WHERE Type__c = 'Integration Towbook Inbound'
              AND Context__c = 'Appointment Update from Towbook'
              AND ReferenceId__c = '{sanitize_soql(_wo_number)}'
            ORDER BY CreatedDate ASC
            LIMIT 50
        """)

    def _get_same_day_r2():
        # same_day only needed for New (open) WOAs — skip for Approved/Rejected
        if (woa.get('Status__c') or '') != 'New':
            return []
        if not (_account_id and _woa_date_str):
            return []
        try:
            rows = sf_query_all(f"""
                SELECT WorkOrderNumber, Status, Trouble_Code__c, CreatedDate,
                       ServiceTerritory.Name
                FROM WorkOrder
                WHERE AccountId = '{sanitize_soql(_account_id)}'
                  AND CreatedDate >= {_woa_date_str}T00:00:00Z
                  AND CreatedDate <= {_woa_date_str}T23:59:59Z
                  AND Id != '{sanitize_soql(wo_id)}'
                LIMIT 10
            """, max_records=10)
            return [
                {'wo_number': r.get('WorkOrderNumber'), 'status': r.get('Status'),
                 'trouble_code': r.get('Trouble_Code__c'), 'created_date': r.get('CreatedDate'),
                 'territory': (r.get('ServiceTerritory') or {}).get('Name')}
                for r in (rows or [])
                if r.get('WorkOrderNumber') != _wo_number
            ]
        except Exception:
            return []

    def _get_all_sa_history_r2():
        """SA history for SAs directly linked to WO (ParentRecordId = WO.Id)."""
        if not wo_id:
            return []
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, OldValue, NewValue
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointmentId IN (
                SELECT Id FROM ServiceAppointment WHERE ParentRecordId = '{wo_id}'
            )
              AND Field = 'Status'
            ORDER BY ServiceAppointmentId, CreatedDate ASC
            LIMIT 200
        """)


    def _get_all_assigned_resource_r2():
        """Semi-join on WO ID — fetches AR for ALL SAs without needing SA IDs first."""
        if not wo_id:
            return []
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, ServiceResourceId, ServiceResource.Name
            FROM AssignedResource
            WHERE ServiceAppointmentId IN (
                SELECT Id FROM ServiceAppointment WHERE ParentRecordId = '{wo_id}'
            )
            ORDER BY CreatedDate DESC
            LIMIT 5
        """)

    # Round 2: all queries that need only Round 1 data (wo_id/woa) run in parallel.
    # SA history and AR fetched via semi-join — eliminates the old Round 3 serial wait.
    _ph2 = sf_parallel(
        woli=lambda: sf_query_all(f"""
            SELECT Id, WorkOrderId, LineItemNumber, PricebookEntry.Name, PricebookEntry.ProductCode,
                   Quantity, TotalPrice, Description, Status
            FROM WorkOrderLineItem
            WHERE WorkOrderId = '{wo_id}'
        """) if wo_id else [],
        costs=lambda: sf_query_all(f"""
            SELECT Name, Quantity__c, Unit_Price__c
            FROM ERS_Work_Order_Cost__c
            WHERE Work_Order__c = '{wo_id}'
        """) if wo_id else [],
        sa_direct=lambda: sf_query_all(f"""
            SELECT {_SA_FIELDS}
            FROM ServiceAppointment
            WHERE ParentRecordId = '{wo_id}'
            ORDER BY SchedStartTime ASC
        """) if wo_id else [],
        rflib_gps=_get_rflib_gps_r2,
        same_day=_get_same_day_r2,
        all_sa_history=_get_all_sa_history_r2,
        all_assigned_resource=_get_all_assigned_resource_r2,
    )
    woli_rows = _ph2['woli']
    wo_costs = _ph2['costs']

    # Build WOLIs list — show only New (pending) items; fallback to all if none are New
    new_wolis = [wl for wl in woli_rows if wl.get('Status') == 'New']
    display_wolis = new_wolis if new_wolis else woli_rows
    # Match WO Cost records to WOLIs
    # Cost records may split a single WOLI into Basic/Plus tiers (e.g., TW 5.88 = 5.0 Basic + 0.88 Plus)
    # Strategy: consume cost records in order, summing amounts per WOLI by matching cumulative quantities
    remaining_costs = sorted([c for c in wo_costs if c.get('Quantity__c')],
                             key=lambda c: -(c.get('Quantity__c') or 0))  # largest first
    product_wolis = sorted([wl for wl in display_wolis if wl.get('Quantity')],
                           key=lambda w: -(w.get('Quantity') or 0))
    woli_amounts = {}  # WOLI LineItemNumber → (total_amount, avg_rate)
    for wl in product_wolis:
        qty = wl.get('Quantity')
        if qty is None or qty == 0:
            continue
        target = round(qty, 2)
        consumed_qty = 0.0
        consumed_amount = 0.0
        to_remove = []
        for i, c in enumerate(remaining_costs):
            cq = round(c.get('Quantity__c') or 0, 2)
            cp = _safe_float(c.get('Unit_Price__c')) or 0
            if consumed_qty + cq <= target + 0.01:
                consumed_qty += cq
                consumed_amount += cq * cp
                to_remove.append(i)
                if abs(consumed_qty - target) < 0.02:
                    break
        for i in reversed(to_remove):
            remaining_costs.pop(i)
        if consumed_amount > 0:
            woli_amounts[wl.get('LineItemNumber')] = (round(consumed_amount, 2), round(consumed_amount / qty, 2) if qty else 0)

    all_wolis = []
    for wl in display_wolis:
        pbe = wl.get('PricebookEntry') or {}
        product_name = pbe.get('Name') or ''
        qty = wl.get('Quantity')
        line_num = wl.get('LineItemNumber')
        amount_info = woli_amounts.get(line_num)
        subtotal = amount_info[0] if amount_info else None
        unit_price = amount_info[1] if amount_info else None
        # Apportion WO-level tax proportionally to each WOLI by its subtotal share
        wo_tax = _safe_float(wo.get('Tax')) or 0
        total_woli_amount = sum(a[0] for a in woli_amounts.values()) if woli_amounts else 0
        tax_share = round(wo_tax * subtotal / total_woli_amount, 2) if subtotal and total_woli_amount > 0 else None
        grand_total = round(subtotal + tax_share, 2) if subtotal is not None and tax_share is not None else subtotal
        all_wolis.append({
            'id': wl.get('Id') or '',
            'name': wl.get('LineItemNumber') or '',
            'product': product_name,
            'code': pbe.get('ProductCode') or (product_name.split(' - ')[0].strip() if ' - ' in product_name else ''),
            'quantity': qty,
            'unit_price': unit_price,
            'subtotal': subtotal,
            'tax': tax_share,
            'grand_total': grand_total,
            'status': wl.get('Status') or '',
        })

    # Resolve product — use Product__c from WOA as authoritative source.
    # Fall back to WOLI quantity-matching only when Product__c is not set.
    req_qty = _safe_float(woa.get('Quantity__c'))
    woa_product_name = (woa.get('Product__r') or {}).get('Name') or ''
    woa_woli_id = woa.get('Work_Order_Line_Item__c') or ''
    woa_description = woa.get('Description__c') or ''
    woa_internal_notes = woa.get('Internal_Notes__c') or ''

    _wm = [{'id': w.get('Id') or '', 'product': (w.get('PricebookEntry') or {}).get('Name') or '',
             'code': (w.get('PricebookEntry') or {}).get('ProductCode') or '',
             'quantity': w.get('Quantity'), 'description': w.get('Description')} for w in woli_rows]

    if woa_product_name:
        pbe_code = woa_product_name.split(' - ')[0].strip() if ' - ' in woa_product_name else woa_product_name.split(' ')[0]
        # Use directly linked WOLI if available, else match by product code
        if woa_woli_id:
            _best = next((w for w in _wm if w['id'] == woa_woli_id), {})
        else:
            _best = next((w for w in _wm if w.get('code') == pbe_code), {})
        if not _best:
            _best = {'product': woa_product_name, 'code': pbe_code, 'quantity': None, 'id': '', '_no_match': True}
        else:
            _best['product'] = woa_product_name  # ensure product name from WOA takes precedence
            _best['code'] = pbe_code
    else:
        _best = match_best_woli(_wm, req_qty, wo=wo)

    _woli_sf = next((w for w in woli_rows if w.get('Id') == _best.get('id')), None)
    woli = _woli_sf or (woli_rows[0] if woli_rows else {})
    _product_not_on_wo = bool(woa_product_name) and not any(
        (w.get('PricebookEntry') or {}).get('Name', '').startswith(pbe_code if woa_product_name else '~')
        for w in woli_rows
    )

    # SA — use direct WO lookup from Round 2.
    # Fallback to WOLI IDs only if still not found (rare — sa_direct no longer
    # filters on Status so it catches in-progress and completed SAs alike).
    sa = {}
    sa_id = ''
    all_sa_rows = _ph2.get('sa_direct') or []
    if all_sa_rows:
        sa = all_sa_rows[0]
        sa_id = sa.get('Id', '')
    else:
        woli_ids = [wl['Id'] for wl in woli_rows if wl.get('Id')]
        if woli_ids:
            sa_check = batch_soql_parallel(f"""
                SELECT {_SA_FIELDS}
                FROM ServiceAppointment
                WHERE ParentRecordId IN ('{{id_list}}')
                ORDER BY SchedStartTime ASC
            """, woli_ids, chunk_size=200)
            if sa_check:
                all_sa_rows = sa_check
                sa = sa_check[0]
                sa_id = sa.get('Id', '')

    # Identify secondary SAs (2nd, 3rd, etc.) for multi-SA timeline
    secondary_sa_rows = all_sa_rows[1:] if len(all_sa_rows) > 1 else []

    # SA history — pre-fetched in Round 2 for WO-linked SAs.
    # If WOLI fallback was used, SA IDs are now known: fetch history directly (fast, 1 query).
    _all_sa_history = _ph2.get('all_sa_history') or []
    if sa_id and not _ph2.get('sa_direct') and all_sa_rows:
        _fallback_ids = [r.get('Id') for r in all_sa_rows if r.get('Id')]
        if _fallback_ids:
            _id_csv = "', '".join(_fallback_ids)
            try:
                _all_sa_history = sf_query_all(f"""
                    SELECT ServiceAppointmentId, CreatedDate, OldValue, NewValue
                    FROM ServiceAppointmentHistory
                    WHERE ServiceAppointmentId IN ('{_id_csv}')
                      AND Field = 'Status'
                    ORDER BY ServiceAppointmentId, CreatedDate ASC
                    LIMIT 200
                """) or []
            except Exception as _e:
                log.warning(f"SA history WOLI fallback failed: {_e}")
    _all_ar = _ph2.get('all_assigned_resource') or []
    _history_by_sa: dict = {}
    for h in _all_sa_history:
        _history_by_sa.setdefault(h.get('ServiceAppointmentId', ''), []).append(h)

    parallel_data = {
        'sa_history': _history_by_sa.get(sa_id, []) if sa_id else [],
        'assigned_resource': [r for r in _all_ar if r.get('ServiceAppointmentId') == sa_id] if sa_id else [],
        'rflib_gps': _ph2.get('rflib_gps') or [],
        'same_day': _ph2.get('same_day') or [],
    }
    for i, sec_sa in enumerate(secondary_sa_rows[:3]):
        parallel_data[f'sa_history_{i+2}'] = _history_by_sa.get(sec_sa.get('Id', ''), [])

    # Photos: pass woli_rows for both channels — Towbook also needs them for CDL fallback.
    parallel_data['photos'] = fetch_photos(wo_id, woli_rows, _is_on_platform)

    status_transitions = ['None', 'Scheduled', 'Assigned', 'Dispatched',
                          'Accepted', 'Declined', 'En Route',
                          'On Location', 'In Progress', 'Completed',
                          'Cannot Complete', 'Canceled']
    sa_history = parallel_data['sa_history']
    sa_timeline = []
    _prev_ts = None
    for h in sa_history:
        nv = h.get('NewValue', '')
        if nv in status_transitions:
            _cur_ts = _parse_dt(h.get('CreatedDate'))
            _elapsed = round((_cur_ts - _prev_ts).total_seconds()) if (_prev_ts and _cur_ts) else None
            sa_timeline.append({
                'time': _fmt_et(h.get('CreatedDate')),
                'from': h.get('OldValue') or '',
                'to': nv,
                'elapsed_seconds': _elapsed,
            })
            if _cur_ts is not None:
                _prev_ts = _cur_ts

    on_loc_ts = None
    completed_ts = None
    enroute_ts = None
    for h in sa_history:
        nv = h.get('NewValue', '')
        ts = _parse_dt(h.get('CreatedDate'))
        if nv == 'En Route' and enroute_ts is None:
            enroute_ts = ts
        if nv == 'On Location' and on_loc_ts is None:
            on_loc_ts = ts
        if nv == 'Completed' and completed_ts is None:
            completed_ts = ts

    on_location_minutes = None
    if on_loc_ts and completed_ts:
        on_location_minutes = round((completed_ts - on_loc_ts).total_seconds() / 60, 1)

    status_quality = 'OK'
    if enroute_ts and on_loc_ts:
        gap_sec = abs((on_loc_ts - enroute_ts).total_seconds())
        if gap_sec < 60:
            status_quality = f'BAD - En Route and On Location {int(gap_sec)} sec apart'

    ar_rows = parallel_data['assigned_resource']
    driver_resource_id = ar_rows[0].get('ServiceResourceId', '') if ar_rows else ''
    driver_name = (ar_rows[0].get('ServiceResource') or {}).get('Name', '') if ar_rows else ''

    # Build secondary SA timelines (for multi-SA work orders)
    secondary_sa_timelines = []
    for i, sec_sa in enumerate(secondary_sa_rows[:3]):
        sec_history = parallel_data.get(f'sa_history_{i+2}') or []
        sec_timeline = []
        _sec_prev_ts = None
        for h in sec_history:
            nv = h.get('NewValue', '')
            if nv in status_transitions:
                _cur_ts = _parse_dt(h.get('CreatedDate'))
                _elapsed = round((_cur_ts - _sec_prev_ts).total_seconds()) if (_sec_prev_ts and _cur_ts) else None
                sec_timeline.append({
                    'time': _fmt_et(h.get('CreatedDate')),
                    'from': h.get('OldValue') or '',
                    'to': nv,
                    'elapsed_seconds': _elapsed,
                })
                if _cur_ts is not None:
                    _sec_prev_ts = _cur_ts
        if sec_timeline:
            secondary_sa_timelines.append({
                'sa_number': sec_sa.get('AppointmentNumber', ''),
                'sa_id': sec_sa.get('Id', ''),
                'work_type': (sec_sa.get('WorkType') or {}).get('Name', ''),
                'status': sec_sa.get('Status', ''),
                'timeline': sec_timeline,
            })

    truck_prev = None

    # Parse Towbook rflib GPS — DISPATCHED, EN_ROUTE, and ON_LOCATION from parallel query.
    # ERS_Request__c is not filterable in SOQL, so we fetch all logs and filter here.
    # DISPATCHED = driver's last known location when the call was assigned (best origin for mileage calc).
    # EN_ROUTE = driver tapped En Route in Towbook app (may be missing if driver skipped tap).
    rflib_dispatched_gps = None
    rflib_enroute_gps = None
    rflib_onloc_gps = None
    for rlog in parallel_data.get('rflib_gps', []):
        try:
            req = _json.loads(rlog.get('ERS_Request__c') or '{}')
            status = req.get('status', '')
            drv = req.get('driver') or {}
            lat = _safe_float(drv.get('latitude'))
            lon = _safe_float(drv.get('longitude'))
            if not (lat and lon):
                continue
            if status == 'DISPATCHED' and not rflib_dispatched_gps:
                rflib_dispatched_gps = {
                    'lat': lat, 'lon': lon,
                    'driver_name': drv.get('name', ''),
                    'truck': drv.get('truckName', ''),
                    'timestamp': rlog.get('CreatedDate'),
                    'source': 'towbook_gps_dispatched',
                }
            elif status == 'EN_ROUTE' and not rflib_enroute_gps:
                rflib_enroute_gps = {
                    'lat': lat, 'lon': lon,
                    'driver_name': drv.get('name', ''),
                    'truck': drv.get('truckName', ''),
                    'timestamp': rlog.get('CreatedDate'),
                    'source': 'towbook_gps_enroute',
                }
            elif status == 'ON_LOCATION' and not rflib_onloc_gps:
                rflib_onloc_gps = {
                    'lat': lat, 'lon': lon,
                    'driver_name': drv.get('name', ''),
                    'truck': drv.get('truckName', ''),
                    'timestamp': rlog.get('CreatedDate'),
                    'source': 'towbook_gps_on_location',
                }
        except Exception:
            pass

    # Priority 1: En Route GPS from THIS SA (Fleet drivers using FSL mobile app)
    er_lat = _safe_float(sa.get('ERS_En_Route_Geolocation__Latitude__s'))
    er_lon = _safe_float(sa.get('ERS_En_Route_Geolocation__Longitude__s'))
    call_lat_check = _safe_float(wo.get('Latitude'))
    if er_lat and er_lon:
        # Verify it's not the same as call location (driver forgot to tap En Route until arriving)
        import math
        dist_check = math.sqrt(((er_lat - (call_lat_check or 0)) * 69) ** 2 + (((er_lon or 0) - _safe_float(wo.get('Longitude') or 0)) * 69 * math.cos(math.radians(er_lat))) ** 2) if call_lat_check else 999
        if dist_check > 0.1:  # Real GPS — more than 500ft from call
            truck_prev = {'lat': er_lat, 'lon': er_lon, 'city': '', 'state': '', 'source': 'driver_gps_enroute'}

    # Priority 2: Towbook rflib EN_ROUTE GPS (driver tapped En Route in Towbook app)
    if not truck_prev and rflib_enroute_gps:
        truck_prev = rflib_enroute_gps

    # Priority 3: Towbook rflib DISPATCHED GPS (last known location when call was assigned)
    if not truck_prev and rflib_dispatched_gps:
        truck_prev = rflib_dispatched_gps

    # Fallback: garage/territory location (no extra query — use data already fetched)
    if not truck_prev and territory_id:
        t = wo.get('ServiceTerritory') or {}
        truck_prev = {'lat': None, 'lon': None, 'city': t.get('Name', ''), 'state': '', 'source': 'garage_location'}

    # SF already has distance data — no need to call Google Distance Matrix.
    google_distance = None
    google_tow_distance = _safe_float(wo.get('ERS_Estimated_Tow_Miles__c')) or None

    call_lat = _safe_float(wo.get('Latitude'))
    call_lon = _safe_float(wo.get('Longitude'))
    tow_dest_lat = _safe_float(wo.get('Tow_Destination__Latitude__s'))
    tow_dest_lon = _safe_float(wo.get('Tow_Destination__Longitude__s'))

    # Google APIs only for TL (toll/parking) product validation
    tl_context = None

    req_qty_audit  = _safe_float(woa.get('Quantity__c'))
    paid_qty_audit = _safe_float(_best.get('quantity'))
    woli_desc      = (woli.get('Description') or '').strip()
    description_keywords = _scan_keywords(woli_desc)
    claimed_minutes = _parse_claimed_minutes(woli_desc)
    long_tow_used  = bool(wo.get('Long_Tow_Used__c'))
    long_tow_miles = _safe_float(wo.get('Long_Tow_Miles__c'))
    woli_code = _best.get('code') or ''

    # Google APIs only for TL product — toll + parking validation only
    if woli_code == 'TL' and call_lat and call_lon:
        gm_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')
        if gm_key:
            _tl_lat0 = call_lat if (tow_dest_lat and tow_dest_lon) else (truck_prev or {}).get('lat')
            _tl_lon0 = call_lon if (tow_dest_lat and tow_dest_lon) else (truck_prev or {}).get('lon')
            _tl_lat1 = tow_dest_lat if (tow_dest_lat and tow_dest_lon) else call_lat
            _tl_lon1 = tow_dest_lon if (tow_dest_lat and tow_dest_lon) else call_lon
            _tl_res = sf_parallel(
                toll=lambda: _google_toll_check(gm_key, _tl_lat0, _tl_lon0, _tl_lat1, _tl_lon1),
                nearby=lambda: _google_nearby_places(gm_key, call_lat, call_lon, types=['parking']),
            )
            tl_context = {'toll': _tl_res['toll'], 'nearby': _tl_res['nearby']}

    photos = parallel_data.get('photos') or {}

    # Check for already-paid MH WOLI on this WO (for MH product only)
    # A "paid" WOLI = status is not 'New', has a non-zero quantity, and is not the WOLI this WOA references
    _already_paid_mh = False
    if woli_code == 'MH':
        for _w in woli_rows:
            _pbe = _w.get('PricebookEntry') or {}
            _w_code = _pbe.get('ProductCode') or ''
            if (_w_code == 'MH'
                    and (_w.get('Status') or 'New') != 'New'
                    and (_w.get('Quantity') or 0) > 0
                    and _w.get('Id') != woa_woli_id):
                _already_paid_mh = True
                break

    rule_rec, rec_reason, _ = _calc_recommendation(
        woli_code, req_qty_audit, paid_qty_audit,
        _safe_float(wo.get('ERS_En_Route_Miles__c')), _safe_float(wo.get('ERS_Estimated_En_Route_Miles__c')),
        _safe_float(wo.get('Tow_Miles__c')), _safe_float(wo.get('ERS_Estimated_Tow_Miles__c')),
        on_loc_minutes=on_location_minutes, vehicle_weight=_safe_float(wo.get('Weight_lbs__c')),
        vehicle_group=wo.get('Vehicle_Group__c'), all_wolis=all_wolis, long_tow_used=long_tow_used,
        vehicle_make=wo.get('Vehicle_Make__c') or None, vehicle_model=wo.get('Vehicle_Model__c') or None,
        already_paid_mh=_already_paid_mh)

    # Reject E1 claims > 14 min on tow calls with no drop-off photos (on-platform only)
    _has_woli_02 = any(w.get('LineItemNumber') == '00000002' for w in woli_rows)
    if (_is_on_platform and woli_code == 'E1' and req_qty_audit is not None and req_qty_audit > 14
            and _has_woli_02 and not photos.get('dropoff_photos') and not photos.get('error')):
        rule_rec = 'reject'
        rec_reason = (rec_reason or '') + '\n→ REJECT: No drop-off photos found on WOLI 00000002. E1 time > 14 min — please resubmit with photos.'

    if req_qty_audit is not None and paid_qty_audit and paid_qty_audit > 0:
        qty_interpretation = f"Requesting total of {req_qty_audit}, already paid {paid_qty_audit} → additional {round(req_qty_audit - paid_qty_audit, 2)}"
    elif req_qty_audit is not None:
        qty_interpretation = f"Nothing currently paid → full adjustment of {req_qty_audit}"
    else:
        qty_interpretation = "No quantity on WOA"

    data_context = {
        'woa_number': woa.get('Name', ''),
        'product': _best.get('product') or (woli.get('PricebookEntry') or {}).get('Name', ''),
        'product_not_on_wo': _product_not_on_wo,
        'woa_description': woa_description,
        'internal_notes': woa_internal_notes,
        'requested_qty': req_qty_audit,
        'currently_paid': paid_qty_audit,
        'qty_interpretation': qty_interpretation,
        'description': woa_description[:500] if woa_description else woli_desc[:500],
        'description_keywords': description_keywords,
        'claimed_minutes_from_description': claimed_minutes,
        'long_tow_used': long_tow_used,
        'long_tow_miles': long_tow_miles,
        'facility': (wo.get('Facility__r') or {}).get('Name', '') or wo.get('Facility_Name__c') or (wo.get('ServiceTerritory', {}).get('Name', '') if wo.get('ServiceTerritory') else ''),
        'on_location_minutes': on_location_minutes,
        'status_quality': status_quality,
        'google_distance_miles': google_distance,
        'google_tow_distance_miles': google_tow_distance,
        'sf_enroute_miles': _safe_float(wo.get('ERS_En_Route_Miles__c')),
        'sf_estimated_enroute_miles': _safe_float(wo.get('ERS_Estimated_En_Route_Miles__c')),
        'sf_tow_miles': _safe_float(wo.get('Tow_Miles__c')),
        'sf_estimated_tow_miles': _safe_float(wo.get('ERS_Estimated_Tow_Miles__c')),
        'truck_prev_location': truck_prev,
        'call_location': {
            'lat': _safe_float(wo.get('Latitude')),
            'lon': _safe_float(wo.get('Longitude')),
            'city': wo.get('City') or '',
            'state': wo.get('State') or '',
        },
        'tow_destination': {
            'lat': _safe_float(wo.get('Tow_Destination__Latitude__s')),
            'lon': _safe_float(wo.get('Tow_Destination__Longitude__s')),
        },
        'vehicle': {
            'make': wo.get('Vehicle_Make__c') or None,
            'model': wo.get('Vehicle_Model__c') or None,
            'weight': _safe_float(wo.get('Weight_lbs__c')),
            'group': wo.get('Vehicle_Group__c') or None,
        },
        'driver': driver_name,
        'sa_timeline': sa_timeline,
        'wo_classification': {
            'trouble_code': wo.get('Trouble_Code__c'),
            'resolution_code': wo.get('Resolution_Code__c'),
            'coverage': wo.get('Coverage__c'),
            'tow_call': wo.get('Tow_Call__c'),
            'axle_count': _safe_float(wo.get('Number_of_Axles__c')),
            'vehicle_group': wo.get('Vehicle_Group__c'),
            'vehicle_weight': _safe_float(wo.get('Weight_lbs__c')),
        },
        'reference_rates': accounting.get_accounting_rates_dict(),
        'tl_context': tl_context,
    }

    garage_history = None
    same_day_calls = parallel_data.get('same_day') or []
    data_context['same_member_same_day_count'] = len(same_day_calls)

    # Strip product-irrelevant fields from AI context to prevent cross-product commingling.
    # E.g. WOA-20541 (E1 winch) and WOA-20542 (ER miles) share a Work Order — the AI must
    # not see ER miles data when auditing the E1 claim.
    _woli_code_upper = woli_code.upper() if woli_code else ''
    _MILES_FIELDS = ('sf_enroute_miles', 'sf_estimated_enroute_miles', 'google_distance_miles',
                     'truck_prev_location')
    _TOW_FIELDS   = ('sf_tow_miles', 'sf_estimated_tow_miles', 'google_tow_distance_miles',
                     'tow_destination')
    if _woli_code_upper in _TIME_CODES:
        # Time product (E1/E2/MI/Z8): remove all miles data — only on_location_minutes matters
        for _k in _MILES_FIELDS + _TOW_FIELDS:
            data_context.pop(_k, None)
    elif _woli_code_upper == 'ER':
        # Enroute miles: remove tow data and on-location time (irrelevant for ER)
        for _k in _TOW_FIELDS:
            data_context.pop(_k, None)
        data_context.pop('on_location_minutes', None)
    elif _woli_code_upper in _TOW_CODES:
        # Tow product: remove enroute data (irrelevant for tow)
        for _k in _MILES_FIELDS:
            data_context.pop(_k, None)
        data_context.pop('on_location_minutes', None)

    return {
        'woa_id': woa_id,
        'woa_number': woa.get('Name', ''),
        'woa_status': woa.get('Status__c') or '',
        'territory_name': (sa.get('ServiceTerritory') or {}).get('Name') or (wo.get('ServiceTerritory') or {}).get('Name') or '',
        'parent_territory_name': ((sa.get('ServiceTerritory') or {}).get('ParentTerritory') or {}).get('Name') or ((wo.get('ServiceTerritory') or {}).get('ParentTerritory') or {}).get('Name') or '',
        'recommendation': rule_rec,
        'rec_reason': rec_reason,
        'confidence': 'LOW',
        'ai_summary': None,
        'ai_headline': None,
        'ai_story': None,
        'ai_fraud_signals': [],
        'ai_anomalies': [],
        'ai_what_to_do': [],
        '_ai_context': data_context,
        '_garage_history': garage_history,
        'evidence': {
            'on_location_minutes': on_location_minutes,
            'status_quality': status_quality,
            'google_distance_miles': google_distance,
            'google_tow_distance_miles': google_tow_distance,
            'sf_enroute_miles': _safe_float(wo.get('ERS_En_Route_Miles__c')),
            'sf_estimated_miles': _safe_float(wo.get('ERS_Estimated_En_Route_Miles__c')),
            'sf_tow_miles': _safe_float(wo.get('Tow_Miles__c')),
            'truck_prev_location': truck_prev,
            'rflib_on_location': rflib_onloc_gps,
            'call_location_lat': _safe_float(wo.get('Latitude')),
            'call_location_lon': _safe_float(wo.get('Longitude')),
            'call_location_city': wo.get('City') or '',
            'call_location_state': wo.get('State') or '',
            'currently_paid': paid_qty_audit,
            'requested': req_qty_audit,
            'qty_interpretation': qty_interpretation,
            'product': _best.get('product') or (woli.get('PricebookEntry') or {}).get('Name') or '',
            'garage_note': woli_desc or None,
            'description_keywords': description_keywords,
            'claimed_minutes_from_description': claimed_minutes,
            'long_tow_used': long_tow_used,
            'long_tow_miles': long_tow_miles,
            'vehicle_make': wo.get('Vehicle_Make__c') or None,
            'vehicle_model': wo.get('Vehicle_Model__c') or None,
            'vehicle_weight': _safe_float(wo.get('Weight_lbs__c')),
            'vehicle_group': wo.get('Vehicle_Group__c') or None,
            'gvw': estimate_gvw(
                wo.get('Vehicle_Make__c') or '',
                wo.get('Vehicle_Model__c') or '',
                _safe_float(wo.get('Number_of_Axles__c')),
                wo.get('Vehicle_Group__c') or '',
                (woa.get('Description__c') or '') + ' ' + (woa.get('Internal_Notes__c') or ''),
                _safe_float(wo.get('Weight_lbs__c')),
            ),
            'tow_destination_lat': _safe_float(wo.get('Tow_Destination__Latitude__s')),
            'tow_destination_lon': _safe_float(wo.get('Tow_Destination__Longitude__s')),
            'sf_estimated_tow_miles': _safe_float(wo.get('ERS_Estimated_Tow_Miles__c')),
            # WO classification — drives billing rules (verified from sf_describe Apr 28 2026)
            'trouble_code': wo.get('Trouble_Code__c'),
            'resolution_code': wo.get('Resolution_Code__c'),
            'clear_code': wo.get('Clear_Code__c'),
            'coverage': wo.get('Coverage__c'),
            'tow_call': wo.get('Tow_Call__c'),
            'facility_id': wo.get('Facility_ID__c'),
            'axle_count': _safe_float(wo.get('Number_of_Axles__c')),
            'account_id': wo.get('AccountId'),
            'contract_name': (wo.get('Facility_Contract__r') or {}).get('Name'),
            'entitlement_name': (wo.get('Entitlement_Master__r') or {}).get('Name'),
            # SA GPS — driver location at each status tap (Fleet FSL mobile app only; Towbook in rflib)
            'sa_on_location_lat': _safe_float(sa.get('On_Location_Geolocation__Latitude__s')),
            'sa_on_location_lon': _safe_float(sa.get('On_Location_Geolocation__Longitude__s')),
            'sa_completed_lat': _safe_float(sa.get('ERS_Completed_Geolocation__Latitude__s')),
            'sa_completed_lon': _safe_float(sa.get('ERS_Completed_Geolocation__Longitude__s')),
            'membership_level_coverage': sa.get('ERS_Membership_Level_Coverage__c'),
            'wo_type': (sa.get('WorkType') or {}).get('Name') or None,
            'program': (wo.get('Type__c') or '').strip() or None,
            # Derived flags
            'is_cancel_en_route': wo.get('Resolution_Code__c') == 'X002',
            'same_member_same_day': same_day_calls,
            'tl_context': tl_context,
        },
        'wo_pricing': {
            'tax': _safe_float(wo.get('Tax')),
            'grand_total': _safe_float(wo.get('GrandTotal')),
            'basic_cost': _safe_float(wo.get('Basic_Cost__c')),
            'plus_cost': _safe_float(wo.get('Plus_Cost__c')),
            'other_cost': _safe_float(wo.get('Other_Cost__c')),
            'total_invoiced': _safe_float(wo.get('Total_Amount_Invoiced__c')),
        },
        'woli_items': all_wolis,
        'sa_timeline': sa_timeline,
        'secondary_sa_timelines': secondary_sa_timelines,
        'sf_urls': {
            'woa': f'{_SF_BASE}/{woa_id}',
            'wo': f'{_SF_BASE}/{wo_id}' if wo_id else None,
            'sa': f'{_SF_BASE}/{sa_id}' if sa_id else None,
            'facility': f'{_SF_BASE}/{territory_id}' if territory_id else None,
            'account': f'{_SF_BASE}/{wo.get("AccountId")}' if wo.get('AccountId') else None,
        },
        'ask_garage': [],
        'same_member_same_day': same_day_calls,
        'photos': photos,
    }
