"""Accounting audit — heavy WOA audit computation."""

from sf_client import sf_query_all, sf_parallel, sanitize_soql
from sf_batch import batch_soql_parallel
from utils import parse_dt as _parse_dt, load_ai_settings as _load_ai_settings, call_openai_simple as _call_openai_simple
from fastapi import HTTPException
import cache, logging, requests as _requests
from datetime import timezone as _tz
from zoneinfo import ZoneInfo

log = logging.getLogger("accounting")
_ET = ZoneInfo("America/New_York")
_SF_BASE = "https://aaawcny.lightning.force.com"

from routers.accounting import _to_et, _fmt_et, _safe_float, _google_distance, _DEFAULT_AUDIT_PROMPT

def _build_woa_audit(woa_id: str) -> dict:
    import json as _json
    import database

    woa_rows = sf_query_all(f"""
        SELECT Id, Name, Quantity__c, CreatedDate, CreatedById, LastModifiedById,
               CreatedBy.Name, LastModifiedBy.Name,
               Work_Order__c, Work_Order__r.WorkOrderNumber,
               Work_Order__r.ServiceTerritoryId,
               Work_Order__r.ServiceTerritory.Name,
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
               Work_Order__r.Other_Cost__c, Work_Order__r.Total_Amount_Invoiced__c
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

    woli_rows = sf_query_all(f"""
        SELECT Id, WorkOrderId, LineItemNumber, PricebookEntry.Name, PricebookEntry.ProductCode,
               Quantity, ListPrice, Subtotal, TotalPrice, Discount, Description, Status
        FROM WorkOrderLineItem
        WHERE WorkOrderId = '{wo_id}'
    """) if wo_id else []

    # Query WO Cost records for per-product pricing (unit price, tax, grand total)
    wo_costs = sf_query_all(f"""
        SELECT Name, Quantity__c, Unit_Price__c
        FROM ERS_Work_Order_Cost__c
        WHERE Work_Order__c = '{wo_id}'
    """) if wo_id else []

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

    # Match WOA to best WOLI by requested quantity (same logic as list endpoint)
    req_qty = _safe_float(woa.get('Quantity__c'))
    named_wolis = [wl for wl in woli_rows if (wl.get('PricebookEntry') or {}).get('Name')]
    if named_wolis and req_qty is not None:
        # Exact quantity match first
        exact = [w for w in named_wolis if w.get('Quantity') is not None and abs(w['Quantity'] - req_qty) < 0.01]
        if len(exact) == 1:
            woli = exact[0]
        else:
            # Closest match, prefer non-BA
            non_ba = [w for w in named_wolis if not (w.get('PricebookEntry') or {}).get('Name', '').startswith('BA')]
            candidates = non_ba if non_ba else named_wolis
            candidates = sorted(candidates, key=lambda w: abs((w.get('Quantity') or 0) - req_qty))
            woli = candidates[0]
    elif named_wolis:
        woli = named_wolis[0]
    else:
        woli = woli_rows[0] if woli_rows else {}

    # Find SA from any WOLI — single batch query
    woli_ids = [wl['Id'] for wl in woli_rows if wl.get('Id')]
    sa = {}
    sa_id = ''
    if woli_ids:
        sa_check = batch_soql_parallel("""
            SELECT Id, AppointmentNumber, Status, SchedStartTime,
                   ServiceTerritoryId, ServiceTerritory.Name, ParentRecordId,
                   ERS_En_Route_Geolocation__Latitude__s,
                   ERS_En_Route_Geolocation__Longitude__s
            FROM ServiceAppointment
            WHERE ParentRecordId IN ('{id_list}')
              AND Status = 'Completed'
        """, woli_ids, chunk_size=200)
        if sa_check:
            sa = sa_check[0]
            sa_id = sa.get('Id', '')

    def _get_sa_history():
        if not sa_id:
            return []
        return sf_query_all(f"""
            SELECT CreatedDate, OldValue, NewValue
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointmentId = '{sa_id}'
              AND Field = 'Status'
            ORDER BY CreatedDate ASC
            LIMIT 200
        """)

    def _get_assigned_resource():
        if not sa_id:
            return []
        return sf_query_all(f"""
            SELECT ServiceResourceId, ServiceResource.Name
            FROM AssignedResource
            WHERE ServiceAppointmentId = '{sa_id}'
            ORDER BY CreatedDate DESC
            LIMIT 1
        """)

    parallel_data = sf_parallel(
        sa_history=_get_sa_history,
        assigned_resource=_get_assigned_resource,
    )

    status_transitions = ['None', 'Scheduled', 'Assigned', 'Dispatched',
                          'Accepted', 'Declined', 'En Route',
                          'On Location', 'In Progress', 'Completed',
                          'Cannot Complete', 'Canceled']
    sa_history = parallel_data['sa_history']
    sa_timeline = []
    for h in sa_history:
        nv = h.get('NewValue', '')
        if nv in status_transitions:
            sa_timeline.append({
                'time': _fmt_et(h.get('CreatedDate')),
                'from': h.get('OldValue') or '',
                'to': nv,
            })

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
    truck_prev = None

    # Priority 1: En Route GPS from THIS SA (driver's actual position when they started driving)
    er_lat = _safe_float(sa.get('ERS_En_Route_Geolocation__Latitude__s'))
    er_lon = _safe_float(sa.get('ERS_En_Route_Geolocation__Longitude__s'))
    call_lat_check = _safe_float(wo.get('Latitude'))
    if er_lat and er_lon:
        # Verify it's not the same as call location (driver forgot to tap En Route until arriving)
        import math
        dist_check = math.sqrt(((er_lat - (call_lat_check or 0)) * 69) ** 2 + (((er_lon or 0) - _safe_float(wo.get('Longitude') or 0)) * 69 * math.cos(math.radians(er_lat))) ** 2) if call_lat_check else 999
        if dist_check > 0.1:  # Real GPS — more than 500ft from call
            truck_prev = {'lat': er_lat, 'lon': er_lon, 'city': '', 'state': '', 'source': 'driver_gps_enroute'}

    # Priority 2: Previous completed SA call location (best estimate for Towbook)
    if not truck_prev and driver_resource_id and sa.get('SchedStartTime'):
        prev_rows = sf_query_all(f"""
            SELECT ServiceAppointment.Latitude, ServiceAppointment.Longitude,
                   ServiceAppointment.City, ServiceAppointment.State
            FROM AssignedResource
            WHERE ServiceResourceId = '{driver_resource_id}'
              AND ServiceAppointment.Status = 'Completed'
              AND ServiceAppointment.SchedStartTime < {sa['SchedStartTime']}
              AND ServiceAppointment.Id != '{sa_id}'
            ORDER BY ServiceAppointment.SchedStartTime DESC LIMIT 1
        """)
        if prev_rows:
            p = (prev_rows[0].get('ServiceAppointment') or {})
            truck_prev = {'lat': _safe_float(p.get('Latitude')), 'lon': _safe_float(p.get('Longitude')),
                          'city': p.get('City') or '', 'state': p.get('State') or '', 'source': 'previous_job'}

    # Priority 3: Garage location (last resort)
    if not truck_prev and territory_id:
        t = wo.get('ServiceTerritory') or {}
        t_name = t.get('Name', '')
        t_lat, t_lon = _safe_float(t.get('Latitude')), _safe_float(t.get('Longitude'))
        if not t_lat:
            t_rows = sf_query_all(f"SELECT Latitude, Longitude FROM ServiceTerritory WHERE Id = '{territory_id}' LIMIT 1")
            if t_rows:
                t_lat, t_lon = _safe_float(t_rows[0].get('Latitude')), _safe_float(t_rows[0].get('Longitude'))
        truck_prev = {'lat': t_lat, 'lon': t_lon, 'city': t_name, 'state': '', 'source': 'garage_location'}

    google_distance = None
    gm_settings = database.get_setting('google_maps') or {}
    gm_key = gm_settings.get('api_key', '')

    if gm_key and truck_prev:
        call_lat = _safe_float(wo.get('Latitude'))
        call_lon = _safe_float(wo.get('Longitude'))
        google_distance = _google_distance(
            gm_key,
            truck_prev.get('lat'), truck_prev.get('lon'),
            call_lat, call_lon,
            origin_str=truck_prev.get('address_str'),
        )

    data_context = {
        'woa_number': woa.get('Name', ''),
        'product': (woli.get('PricebookEntry') or {}).get('Name', ''),
        'requested_qty': _safe_float(woa.get('Quantity__c')),
        'currently_paid': _safe_float(woli.get('Quantity')),
        'description': (woli.get('Description') or '')[:500],
        'facility': (wo.get('Facility__r') or {}).get('Name', '') or wo.get('Facility_Name__c') or (wo.get('ServiceTerritory', {}).get('Name', '') if wo.get('ServiceTerritory') else ''),
        'on_location_minutes': on_location_minutes,
        'status_quality': status_quality,
        'google_distance_miles': google_distance,
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
    }

    acct_settings = database.get_setting('accounting') or {}
    audit_prompt = acct_settings.get('audit_prompt', '') or _DEFAULT_AUDIT_PROMPT
    recommendation, confidence, ai_summary, ask_garage = 'REVIEW', 'LOW', None, None

    _provider, api_key, model = _load_ai_settings()
    if api_key:
        user_prompt = f"Audit this WOA:\n\n{_json.dumps(data_context, indent=2, default=str)}"
        raw = _call_openai_simple(api_key, model, audit_prompt, user_prompt)
        if raw:
            ai_summary = raw
            # Try to parse JSON from the AI response
            try:
                # Handle markdown code fences
                clean = raw.strip()
                if clean.startswith('```'):
                    clean = clean.split('\n', 1)[1] if '\n' in clean else clean[3:]
                    clean = clean.rsplit('```', 1)[0]
                parsed = _json.loads(clean)
                recommendation = parsed.get('recommendation', 'REVIEW')
                confidence = parsed.get('confidence', 'LOW')
                ai_summary = parsed.get('summary', raw)
                ask_garage = parsed.get('ask_garage')
            except (_json.JSONDecodeError, AttributeError):
                # AI returned free-text — use as-is
                pass
    else:
        ai_summary = 'AI not configured. Go to Admin → AI Assistant to set up.'

    return {
        'woa_id': woa_id,
        'woa_number': woa.get('Name', ''),
        'recommendation': recommendation,
        'confidence': confidence,
        'ai_summary': ai_summary,
        'evidence': {
            'on_location_minutes': on_location_minutes,
            'status_quality': status_quality,
            'google_distance_miles': google_distance,
            'sf_enroute_miles': _safe_float(wo.get('ERS_En_Route_Miles__c')),
            'sf_estimated_miles': _safe_float(wo.get('ERS_Estimated_En_Route_Miles__c')),
            'sf_tow_miles': _safe_float(wo.get('Tow_Miles__c')),
            'truck_prev_location': truck_prev,
            'call_location_lat': _safe_float(wo.get('Latitude')),
            'call_location_lon': _safe_float(wo.get('Longitude')),
            'call_location_city': wo.get('City') or '',
            'call_location_state': wo.get('State') or '',
            'currently_paid': _safe_float(woli.get('Quantity')),
            'requested': _safe_float(woa.get('Quantity__c')),
            'product': (woli.get('PricebookEntry') or {}).get('Name') or '',
            'garage_note': (woli.get('Description') or '').strip() or None,
            'vehicle_make': wo.get('Vehicle_Make__c') or None,
            'vehicle_model': wo.get('Vehicle_Model__c') or None,
            'vehicle_weight': _safe_float(wo.get('Weight_lbs__c')),
            'vehicle_group': wo.get('Vehicle_Group__c') or None,
            'tow_destination_lat': _safe_float(wo.get('Tow_Destination__Latitude__s')),
            'tow_destination_lon': _safe_float(wo.get('Tow_Destination__Longitude__s')),
            'sf_estimated_tow_miles': _safe_float(wo.get('ERS_Estimated_Tow_Miles__c')),
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
        'sf_urls': {
            'woa': f'{_SF_BASE}/{woa_id}',
            'wo': f'{_SF_BASE}/{wo_id}' if wo_id else None,
            'sa': f'{_SF_BASE}/{sa_id}' if sa_id else None,
            'facility': f'{_SF_BASE}/{territory_id}' if territory_id else None,
        },
        'ask_garage': ask_garage,
    }