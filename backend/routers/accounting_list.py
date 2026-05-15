"""WOA list builder — fetches and processes Work Order Adjustments from Salesforce."""
import logging
from utils import parse_dt as _parse_dt
from sf_client import sf_query_all
from sf_batch import batch_soql_parallel
from routers.accounting_calc import (
    _safe_float, _calc_recommendation, match_best_woli,
    _TOW_CODES, _TIME_CODES, _fmt_date_et,
)
from repositories import accounting

log = logging.getLogger('accounting')


def _fetch_photo_wo_ids(wo_ids: list) -> set:
    """Return set of WO IDs that have at least one Service_Photo__c record."""
    if not wo_ids:
        return set()
    try:
        rows = batch_soql_parallel("""
            SELECT Work_Order__c
            FROM Service_Photo__c
            WHERE Work_Order__c IN ('{id_list}')
            GROUP BY Work_Order__c
        """, wo_ids, chunk_size=400)
        return {r.get('Work_Order__c') for r in (rows or []) if r.get('Work_Order__c')}
    except Exception:
        return set()


def _calc_age_from_wo(woa_created, wo_created):
    """Days between WO creation and WOA creation."""
    if not woa_created or not wo_created:
        return None
    woa_dt = _parse_dt(woa_created)
    wo_dt = _parse_dt(wo_created)
    if woa_dt and wo_dt:
        return (woa_dt - wo_dt).days
    return None


def _calc_age_to_now(woa_created, now):
    """Days from WOA creation to current date."""
    if not woa_created:
        return None
    woa_dt = _parse_dt(woa_created)
    if woa_dt:
        return (now - woa_dt).days
    return None


def _build_woa_list() -> dict:
    woa_rows = sf_query_all("""
        SELECT Id, Name, Quantity__c, Status__c, Description__c, Internal_Notes__c,
               Product__c, Product__r.Name,
               Work_Order_Line_Item__c,
               CreatedDate, CreatedById, LastModifiedById,
               OwnerId, Owner.Name, CreatedBy.Name, LastModifiedBy.Name,
               Work_Order__c, Work_Order__r.WorkOrderNumber,
               Work_Order__r.ServiceTerritoryId,
               Work_Order__r.ServiceTerritory.Name,
               Work_Order__r.ServiceTerritory.ParentTerritory.Name,
               Work_Order__r.Facility_Name__c, Work_Order__r.Facility_ID__c,
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
               Work_Order__r.Long_Tow_Used__c,
               Work_Order__r.Long_Tow_Miles__c,
               Work_Order__r.Type__c,
               Work_Order__r.ERS_Unable_To_Complete_Dupe__c,
               Work_Order__r.Out_of_Territory__c,
               Work_Order__r.CreatedDate
        FROM ERS_Work_Order_Adjustment__c
        ORDER BY CreatedDate DESC
        LIMIT 5000
    """)

    if not woa_rows:
        return {'items': [], 'total': 0}

    import time as _time
    from datetime import datetime, timezone as _tz
    _now = datetime.now(_tz.utc)
    _t0 = _time.time()

    wo_ids = list({r.get('Work_Order__c') for r in woa_rows if r.get('Work_Order__c')})
    log.info(f"WOA list: {len(woa_rows)} rows, {len(wo_ids)} unique WOs to query WOLIs")
    woli_rows = batch_soql_parallel("""
        SELECT Id, WorkOrderId, WorkOrder.WorkOrderNumber, PricebookEntry.Name,
               Quantity, UnitPrice, TotalPrice, Description
        FROM WorkOrderLineItem
        WHERE WorkOrderId IN ('{id_list}')
    """, wo_ids, chunk_size=500) if wo_ids else []

    from collections import defaultdict
    _rates = accounting.get_accounting_rates_dict()
    _materiality = _rates.get('materiality_threshold_usd', 10.0)

    wo_wolis = defaultdict(list)
    for wl in woli_rows:
        wo_id = wl.get('WorkOrderId')
        if wo_id:
            pbe = (wl.get('PricebookEntry') or {}).get('Name') or ''
            qty = wl.get('Quantity')
            total_price = _safe_float(wl.get('TotalPrice'))
            unit_price = _safe_float(wl.get('UnitPrice'))
            unit_rate = (total_price / qty) if (qty and qty > 0 and total_price and total_price > 0) else None
            wo_wolis[wo_id].append({
                'id': wl.get('Id'),
                'product': pbe,
                'code': pbe.split(' - ')[0].strip() if ' - ' in pbe else pbe.split(' ')[0] if pbe else '',
                'quantity': qty,
                'unit_rate': unit_rate,
                'unit_price': unit_price,
                'description': wl.get('Description'),
            })

    def _best_woli(wo_id, requested_qty, wo=None):
        return match_best_woli(wo_wolis.get(wo_id, []), requested_qty, wo)

    items = []
    for r in woa_rows:
        woa_id = r.get('Id', '')
        wo = r.get('Work_Order__r') or {}
        wo_id = r.get('Work_Order__c', '')
        req_qty = _safe_float(r.get('Quantity__c'))
        woa_description = r.get('Description__c') or ''
        woa_internal_notes = r.get('Internal_Notes__c') or ''

        woa_product_name = (r.get('Product__r') or {}).get('Name') or ''
        woa_woli_id = r.get('Work_Order_Line_Item__c') or ''

        if woa_product_name:
            pbe_name = woa_product_name
            pbe_code = pbe_name.split(' - ')[0].strip() if ' - ' in pbe_name else pbe_name.split(' ')[0]
            if woa_woli_id and woa_woli_id in {w.get('id') for w in wo_wolis.get(wo_id, [])}:
                woli = next(w for w in wo_wolis[wo_id] if w.get('id') == woa_woli_id)
            else:
                woli = next((w for w in wo_wolis.get(wo_id, []) if w.get('code') == pbe_code), {})
            product = pbe_name
            code = pbe_code
            paid = _safe_float(woli.get('quantity')) if woli else None
        else:
            woli = _best_woli(wo_id, req_qty, wo=wo)
            product = woli.get('product') or ''
            code = woli.get('code') or ''
            paid = _safe_float(woli.get('quantity'))

        all_named_non_ba = [w for w in wo_wolis.get(wo_id, []) if w.get('product') and w.get('code') != 'BA']
        _no_match = woli.get('_no_match', False) if isinstance(woli, dict) else False
        _product_not_on_wo = bool(woa_product_name) and not any(w.get('code') == code for w in wo_wolis.get(wo_id, []))
        all_products_str = ', '.join(
            f"{w['code']}={w.get('quantity')}" for w in all_named_non_ba if w.get('code')
        ) if (len(all_named_non_ba) > 1 or _no_match or _product_not_on_wo) else ''
        sf_er = _safe_float(wo.get('ERS_En_Route_Miles__c'))
        sf_est_er = _safe_float(wo.get('ERS_Estimated_En_Route_Miles__c'))
        sf_tow = _safe_float(wo.get('Tow_Miles__c'))
        sf_est_tow = _safe_float(wo.get('ERS_Estimated_Tow_Miles__c'))

        on_loc_min = None

        v_make = wo.get('Vehicle_Make__c') or ''
        v_model = wo.get('Vehicle_Model__c') or ''
        v_group = wo.get('Vehicle_Group__c') or ''
        all_wolis = wo_wolis.get(wo_id, [])
        long_tow_used = bool(wo.get('Long_Tow_Used__c'))
        long_tow_miles = _safe_float(wo.get('Long_Tow_Miles__c'))

        _CONFIDENCE_MAP = {
            'ER': 'HIGH', 'TW': 'HIGH', 'TB': 'HIGH', 'TT': 'HIGH', 'TU': 'HIGH', 'TM': 'HIGH', 'EM': 'HIGH',
            'E1': 'HIGH', 'E2': 'HIGH', 'Z8': 'HIGH',
            'MH': 'HIGH', 'MI': 'MEDIUM', 'TL': 'MEDIUM',
            'BA': 'LOW', 'BC': 'LOW', 'PC': 'LOW', 'HO': 'LOW', 'PG': 'LOW',
        }
        confidence = _CONFIDENCE_MAP.get(code, 'MEDIUM')
        if code == 'MH' and not _safe_float(wo.get('Weight_lbs__c')) and v_group not in ('MD', 'HD', 'DW'):
            confidence = 'LOW'

        woli_description = woli.get('description') or ''

        rec, rec_reason, verification = _calc_recommendation(
            code, req_qty, paid, sf_er, sf_est_er, sf_tow, sf_est_tow,
            on_loc_minutes=on_loc_min,
            vehicle_weight=_safe_float(wo.get('Weight_lbs__c')),
            vehicle_group=v_group,
            all_wolis=all_wolis,
            long_tow_used=long_tow_used)

        if all_wolis:
            rec_reason += '\n\nWO LINE ITEMS:'
            for wl in all_wolis:
                if wl.get('product'):
                    rec_reason += f'\n  {wl["code"]:5s} {wl["product"]}: qty={wl.get("quantity")}'
        if v_make:
            rec_reason += f'\n\nVEHICLE: {v_make} {v_model} (group={v_group})'

        woli_summary = ' | '.join(f'{wl["code"]}={wl.get("quantity")}' for wl in all_wolis if wl.get('product'))

        _er_rate  = _rates.get('er_rate_per_mile',  1.75)
        _tow_rate = _rates.get('tow_rate_per_mile', 15.0)
        _em_rate  = _rates.get('em_rate_per_mile',   2.0)
        _e1_rate  = _rates.get('e1_rate_per_min',   0.75)
        _ba_rate  = _rates.get('ba_rate_per_call',  40.0)
        _mh_rate  = _rates.get('mh_rate_per_call',  20.0)
        if req_qty is not None:
            _delta_qty = req_qty - (paid or 0)
            if code == 'TL':
                estimated_usd = round(abs(_delta_qty), 2)
            elif code == 'ER':
                estimated_usd = round(abs(_delta_qty) * _er_rate, 2)
            elif code in _TOW_CODES:
                estimated_usd = round(abs(_delta_qty) * _tow_rate, 2)
            elif code in _TIME_CODES:
                estimated_usd = round(abs(_delta_qty) * _e1_rate, 2)
            else:
                estimated_usd = None
        else:
            estimated_usd = None
        is_low_materiality = (estimated_usd is not None and estimated_usd < _materiality)
        if is_low_materiality and rec == 'review':
            rec = 'approve'

        # requested_usd — total value of what the garage is claiming (req_qty × unit rate).
        # Uses WOLI UnitPrice when SF has it, otherwise reference rate defaults.
        # Shown as "Est. $?" in the list — always an estimate, never an invoice.
        _woli_unit_price = _safe_float(woli.get('unit_price')) if isinstance(woli, dict) else None
        if req_qty is not None:
            if _woli_unit_price and _woli_unit_price > 0:
                requested_usd = round(req_qty * _woli_unit_price, 2)
            elif code == 'TL':
                requested_usd = round(req_qty, 2)
            elif code == 'ER':
                requested_usd = round(req_qty * _er_rate, 2)
            elif code == 'EM':
                requested_usd = round(req_qty * _em_rate, 2)
            elif code in _TOW_CODES:
                requested_usd = round(req_qty * _tow_rate, 2)
            elif code in _TIME_CODES:
                requested_usd = round(req_qty * _e1_rate, 2)
            elif code == 'BA':
                requested_usd = round(req_qty * _ba_rate, 2)
            elif code == 'MH':
                requested_usd = round(req_qty * _mh_rate, 2)
            else:
                requested_usd = None
        else:
            requested_usd = None

        _is_oot_private_service = (
            bool(wo.get('ERS_Unable_To_Complete_Dupe__c'))
            and bool(wo.get('Out_of_Territory__c'))
            and (wo.get('Type__c') or '').strip() == 'Private Service'
        )

        items.append({
            'id': woa_id,
            'woa_number': r.get('Name', ''),
            'status': r.get('Status__c') or '',
            'product': product,
            'code': code,
            'all_products': all_products_str,
            'product_synthetic': woli.get('_synthetic', False),
            'requested_qty': req_qty,
            'currently_paid': paid,
            'recommendation': rec,
            'confidence': confidence,
            'description': woli_description[:200] if woli_description else '',
            'long_tow_used': long_tow_used,
            'long_tow_miles': long_tow_miles,
            'rec_reason': rec_reason,
            'facility': (wo.get('Facility__r') or {}).get('Name', '') or wo.get('Facility_Name__c') or (wo.get('ServiceTerritory', {}).get('Name', '') if wo.get('ServiceTerritory') else ''),
            'parent_territory': ((wo.get('ServiceTerritory') or {}).get('ParentTerritory') or {}).get('Name', ''),
            'wo_number': wo.get('WorkOrderNumber', ''),
            'wo_id': wo_id,
            'woli_id': woli.get('id') or '' if isinstance(woli, dict) else '',
            'woa_description': woa_description,
            'internal_notes': woa_internal_notes,
            'product_not_on_wo': _product_not_on_wo,
            'created_date': _fmt_date_et(r.get('CreatedDate')),
            '_sort_date': (r.get('CreatedDate') or '')[:10],
            'created_by': (r.get('CreatedBy') or {}).get('Name', ''),
            'owner': (r.get('Owner') or {}).get('Name', ''),
            'woa_age_from_wo_days': _calc_age_from_wo(r.get('CreatedDate'), wo.get('CreatedDate')),
            'woa_age_days': _calc_age_to_now(r.get('CreatedDate'), _now),
            'sf_miles': {'enroute': sf_er, 'estimated_enroute': sf_est_er, 'tow': sf_tow, 'estimated_tow': sf_est_tow},
            'vehicle': {'make': v_make, 'model': v_model, 'group': v_group},
            'woli_summary': woli_summary,
            'estimated_usd': estimated_usd,
            'requested_usd': requested_usd,
            'is_low_materiality': is_low_materiality,
            'program': (wo.get('Type__c') or '').strip(),
            'service_type': '',
            'is_oot_private_service': _is_oot_private_service,
        })

    from collections import defaultdict
    wo_total_counts = defaultdict(int)
    wo_code_counts = defaultdict(lambda: defaultdict(int))
    wo_code_qtys = defaultdict(list)
    for item in items:
        wid = item.get('wo_id', '')
        c = item.get('code', '')
        q = item.get('requested_qty') or 0
        if wid:
            wo_total_counts[wid] += 1
            if c:
                wo_code_counts[wid][c] += 1
                wo_code_qtys[(wid, c)].append(q)
    for item in items:
        wid = item.get('wo_id', '')
        c = item.get('code', '')
        woa_count = wo_total_counts.get(wid, 1)
        same_code = wo_code_counts.get(wid, {}).get(c, 1) if c else 1
        item['wo_woa_count'] = woa_count
        if woa_count > 1 and same_code > 1 and c:
            qtys = wo_code_qtys.get((wid, c), [])
            max_q = max(qtys) if qtys else 0
            min_q = min(qtys) if qtys else 0
            qty_spread = (max_q - min_q) / max_q if max_q > 0 else 0
            item['is_possible_duplicate'] = qty_spread < 0.10
            item['is_multi_same_product'] = not item['is_possible_duplicate']
        else:
            item['is_possible_duplicate'] = False
            item['is_multi_same_product'] = False

    # Mark which WOs have Towbook photos (Service_Photo__c records)
    _all_wo_ids = [item['wo_id'] for item in items if item.get('wo_id')]
    _photo_wo_ids = _fetch_photo_wo_ids(_all_wo_ids)
    for item in items:
        item['has_photos'] = item.get('wo_id', '') in _photo_wo_ids

    log.info(f"WOA list built: {len(items)} items in {_time.time() - _t0:.1f}s")
    return {'items': items, 'total': len(items)}
