"""Accounting — Work Order Adjustment auditing with AI-powered recommendations."""

import logging
import requests as _requests
from datetime import datetime as _dt, timezone as _tz
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException, Query

from sf_client import sf_query_all, sf_parallel, sanitize_soql
from sf_batch import batch_soql_parallel
from utils import parse_dt as _parse_dt, load_ai_settings as _load_ai_settings, call_openai_simple as _call_openai_simple
import cache
from routers.accounting_export import build_export

router = APIRouter()
log = logging.getLogger('accounting')

_ET = ZoneInfo('America/New_York')
_SF_BASE = 'https://aaawcny.lightning.force.com'

# ── Default audit prompt (used when no custom prompt configured) ─────────────

_DEFAULT_AUDIT_PROMPT = (
    "You are a senior accounting auditor for AAA Western & Central NY roadside assistance. "
    "You're writing for an internal auditor who needs to understand WHAT HAPPENED on this call and WHETHER the garage's claim is justified. "
    "NEVER just repeat numbers — explain what they MEAN. "
    "ALWAYS spell out product names (ER = Enroute Miles, TW = Tow Miles, E1 = Extrication in minutes, BA = Base Rate, TL = Tolls/Parking, MH = Medium/Heavy Duty, MI = Wait Time). "
    "ALWAYS include units (miles, minutes, dollars). "
    "Tell the STORY: What service was performed? Where did the truck go? How long was the driver on scene? "
    "Is the garage's claim reasonable compared to what Salesforce calculated using Google Maps? "
    "If there's a discrepancy, explain POSSIBLE reasons (driver status issue, detour, system error) and what the auditor should check. "
    "Rules: ER/TW within 130% of SF Google distance=reasonable. E1/MI within 120% of on-scene time=reasonable. "
    "BA/BC/PC always need policy review. TL needs receipts. MH needs vehicle weight verification. "
    'Respond JSON: {"recommendation":"PAY|REVIEW|DENY","confidence":"HIGH|MEDIUM|LOW",'
    '"summary":"2-3 sentence auditor narrative with units and context",'
    '"reasoning":["specific finding 1","specific finding 2"],'
    '"ask_garage":["question for the garage if REVIEW"]}'
)

def _to_et(dt_str):
    dt = _parse_dt(dt_str)
    if not dt: return None
    return dt.replace(tzinfo=_tz.utc) if dt.tzinfo is None else dt

def _calc_recommendation(code, requested, paid, sf_er, sf_est_er, sf_tow, sf_est_tow,
                         on_loc_minutes=None, vehicle_weight=None, vehicle_group=None,
                         all_wolis=None):
    """Pure math recommendation. Returns (rec, step_by_step_reason, verification)."""
    NAMES = {'ER': 'Enroute Miles', 'TW': 'Tow Miles', 'TB': 'Tow Miles Basic',
             'TT': 'Tow Miles Plus (5-30mi)', 'TU': 'Tow Miles Plus (30-100mi)',
             'TM': 'Tow Miles Premier', 'EM': 'Extra Tow Mileage',
             'E1': 'Extrication (1st Truck)', 'E2': 'Extrication (2nd Truck)',
             'Z8': 'RAP Extrication', 'MH': 'Medium/Heavy Duty', 'TL': 'Tolls/Parking',
             'MI': 'Miscellaneous/Wait Time', 'BA': 'Base Rate', 'BC': 'Basic Cost',
             'PC': 'Plus Cost', 'HO': 'Holiday Bonus', 'PG': 'Plus/Premier Fuel',
             'Z5': 'RAP Fuel Delivery', 'Z7': 'RAP Lockout', 'TJ': 'TireJect',
             'Z0': 'RAP Gone on Arrival', 'Z1': 'RAP Flat Tire', 'Z3': 'RAP Battery Boost'}
    # Product category classification
    TOW_CODES = {'TW', 'TB', 'TT', 'TU', 'TM', 'EM'}
    TIME_CODES = {'E1', 'E2', 'Z8'}
    FLAT_CODES = {'BA', 'BC', 'PC', 'HO', 'PG', 'Z5', 'Z7', 'TJ', 'Z0', 'Z1', 'Z3'}
    L = []
    v = {}
    prod_name = NAMES.get(code, 'Unknown') if code else 'No product on WO'
    L.append(f'PRODUCT: {code or "—"} — {prod_name}')
    L.append(f'GARAGE REQUESTED: {requested}')
    L.append(f'SF BILLED (WOLI): {paid if paid else "Not on WO"}')

    if requested is None:
        L.append('→ No quantity → REVIEW'); return 'review', '\n'.join(L), {}
    if requested < 0:
        L.append(f'→ Negative qty = credit/reduction → REVIEW'); return 'review', '\n'.join(L), {}
    if requested == 0:
        L.append('→ Zero qty → APPROVE'); return 'approve', '\n'.join(L), {}

    if not code:
        L.append(f'\nNO PRODUCT IDENTIFIED:')
        L.append(f'  This Work Order has no line items.')
        L.append(f'  Cannot determine what product the garage is requesting.')
        L.append(f'  Auditor: open the WO in Salesforce to check what service was performed.')
        L.append(f'\n→ Manual review required — no data to verify automatically.')
        return 'review', '\n'.join(L), {}
    if code == 'ER':
        L.append(f'\nDATA FROM SF:')
        L.append(f'  SF Google Estimate: {sf_est_er or "N/A"} mi')
        L.append(f'  SF Recorded Actual: {sf_er or "N/A"} mi')
        baseline = sf_est_er if sf_est_er and sf_est_er > 0 else sf_er if sf_er and sf_er > 0 else None
        src = 'SF Google Estimate' if sf_est_er and sf_est_er > 0 else 'SF Recorded'
        L.append(f'  Baseline: {src} = {baseline or "none"}')
        v = {'sf_google_estimate': sf_est_er, 'sf_recorded': sf_er, 'sf_billed': paid, 'unit': 'mi'}
    elif code in TOW_CODES:
        L.append(f'\nDATA FROM SF (tow distance):')
        L.append(f'  SF Google Tow Estimate: {sf_est_tow or "N/A"} mi')
        L.append(f'  SF Recorded Tow: {sf_tow or "N/A"} mi')
        baseline = sf_est_tow if sf_est_tow and sf_est_tow > 0 else sf_tow if sf_tow and sf_tow > 0 else None
        src = 'SF Google Estimate' if sf_est_tow and sf_est_tow > 0 else 'SF Recorded'
        L.append(f'  Baseline: {src} = {baseline or "none"}')
        v = {'sf_google_estimate': sf_est_tow, 'sf_recorded': sf_tow, 'sf_billed': paid, 'unit': 'mi'}
    elif code in TIME_CODES:
        L.append(f'\nDATA FROM SF:')
        L.append(f'  On-Location Time: {on_loc_minutes or "N/A"} min')
        L.append(f'  (Completed timestamp - On Location timestamp)')
        v = {'on_location_min': on_loc_minutes, 'sf_billed': paid, 'unit': 'min'}
        if paid and paid > 0 and abs(requested - paid) < 0.5:
            L.append(f'\n→ Requesting same as billed ({paid} min). No change needed.')
            return 'approve', '\n'.join(L), v
        if on_loc_minutes and on_loc_minutes > 0:
            ratio = requested / on_loc_minutes
            L.append(f'\nCALCULATION:')
            L.append(f'  {requested} ÷ {on_loc_minutes} = {ratio:.0%}')
            L.append(f'  Threshold: ≤120% = Approve')
            if ratio <= 1.2:
                L.append(f'→ {ratio:.0%} ≤ 120% → APPROVE'); return 'approve', '\n'.join(L), v
            L.append(f'→ {ratio:.0%} > 120% → REVIEW'); return 'review', '\n'.join(L), v
        L.append(f'→ No on-location time available → REVIEW'); return 'review', '\n'.join(L), v
    elif code == 'MI':
        L.append(f'\nDATA FROM SF:')
        L.append(f'  On-Location Time: {on_loc_minutes or "N/A"} min')
        v = {'on_location_min': on_loc_minutes, 'sf_billed': paid, 'unit': 'min'}
        if paid and paid > 0 and abs(requested - paid) < 0.5:
            L.append(f'\n→ Requesting same as billed ({paid} min). No change needed.')
            return 'approve', '\n'.join(L), v
        if on_loc_minutes and on_loc_minutes > 0:
            L.append(f'\nCALCULATION:')
            L.append(f'  On-scene {on_loc_minutes} min vs claimed {requested} min')
            if on_loc_minutes >= requested * 0.8:
                L.append(f'→ On-scene supports claim → APPROVE'); return 'approve', '\n'.join(L), v
            L.append(f'→ On-scene shorter than claimed → REVIEW'); return 'review', '\n'.join(L), v
        L.append(f'→ No on-location time → REVIEW'); return 'review', '\n'.join(L), v
    elif code == 'MH':
        L.append(f'\nDATA FROM SF:')
        L.append(f'  Vehicle Weight: {vehicle_weight or "Not populated"} lbs')
        L.append(f'  Vehicle Group: {vehicle_group or "N/A"}')
        L.append(f'  Threshold: ≥10,000 lbs or Group DW/HD/MD')
        v = {'vehicle_weight': vehicle_weight, 'vehicle_group': vehicle_group}
        if paid and paid > 0 and abs(requested - paid) < 0.5:
            L.append(f'\n→ Requesting same as billed ({paid}). No change needed.')
            return 'approve', '\n'.join(L), v
        if vehicle_weight and vehicle_weight >= 10000:
            L.append(f'→ {vehicle_weight} lbs ≥ 10,000 → APPROVE'); return 'approve', '\n'.join(L), v
        if vehicle_group in ('MD', 'HD', 'DW'):
            L.append(f'→ Group {vehicle_group} = heavy → APPROVE'); return 'approve', '\n'.join(L), v
        if vehicle_weight and vehicle_weight < 10000:
            L.append(f'→ {vehicle_weight} lbs < 10,000 → REVIEW'); return 'review', '\n'.join(L), v
        L.append(f'→ No weight data → REVIEW'); return 'review', '\n'.join(L), v
    elif code == 'TL':
        wolis = all_wolis or []
        has_tow = any(w.get('code') in TOW_CODES for w in wolis)
        has_er = any(w.get('code') == 'ER' for w in wolis)
        L.append(f'\nTOLLS/PARKING:')
        L.append(f'  No receipts in SF — cannot verify amount automatically.')
        L.append(f'  WO has tow: {"YES" if has_tow else "NO"}')
        if has_tow:
            L.append(f'  Tow present → tolls are plausible if route crosses toll road.')
        else:
            L.append(f'  No tow on WO → tolls less likely (unless parking/airport).')
        if paid and paid > 0:
            L.append(f'  Currently billed: ${paid}')
            if abs(requested - paid) < 0.01:
                L.append(f'\n→ Requesting same as billed. No change needed.')
                return 'approve', '\n'.join(L), {'sf_billed': paid, 'unit': '$'}
        if has_tow and requested and requested <= 20:
            L.append(f'\n→ Small toll (${requested}) with tow on WO — plausible. Still request receipt.')
            return 'approve', '\n'.join(L), {'sf_billed': paid, 'unit': '$'}
        L.append(f'\n→ Request receipt from garage to verify ${requested}.')
        return 'review', '\n'.join(L), {'sf_billed': paid, 'unit': '$'}
    elif code in FLAT_CODES:
        L.append(f'\nFLAT FEE / SERVICE EVENT:')
        L.append(f'  {prod_name} — verify the service was performed.')
        if paid and paid > 0 and abs(requested - paid) < 0.01:
            L.append(f'→ Requesting same as billed → APPROVE')
            return 'approve', '\n'.join(L), {'sf_billed': paid}
        L.append(f'→ Requires policy review'); return 'review', '\n'.join(L), {'sf_billed': paid}
    else:
        baseline = sf_est_er if sf_est_er and sf_est_er > 0 else sf_er if sf_er and sf_er > 0 else None
        src = 'SF data'
        L.append(f'\nDATA: SF={baseline or "N/A"}')
        v = {'sf_google_estimate': sf_est_er, 'sf_recorded': sf_er, 'sf_billed': paid}

    # Mileage comparison (ER, TW, unknown)
    L.append(f'\nCALCULATION:')
    if baseline is None or baseline == 0:
        L.append(f'\n→ No SF data to compare against. Cannot verify automatically.')
        return 'review', '\n'.join(L), v
    if paid and paid > 0 and abs(requested - paid) < 0.5:
        L.append(f'\n→ Garage is asking for the same amount already billed. No change needed.')
        return 'approve', '\n'.join(L), v
    ratio = requested / baseline
    pct_over = round((ratio - 1) * 100)
    L.append(f'\nCOMPARISON:')
    L.append(f'  Requested {requested} vs {src} {baseline}')
    if ratio <= 1.0:
        L.append(f'\n→ Garage is asking for less than what SF calculated. Reasonable.')
    elif ratio <= 1.3:
        L.append(f'\n→ Garage is asking {pct_over}% more than SF calculated. Within normal range.')
    elif ratio <= 1.5:
        L.append(f'\n→ Garage is asking {pct_over}% more than SF calculated. Slightly high — verify the route.')
    elif ratio <= 2.0:
        L.append(f'\n→ Garage is asking {ratio:.1f}x what SF calculated ({pct_over}% more). Needs verification.')
    else:
        L.append(f'\n→ Garage is asking {ratio:.1f}x what SF calculated. Significant discrepancy — investigate.')
    if ratio <= 1.3:
        return 'approve', '\n'.join(L), v
    return 'review', '\n'.join(L), v

def _fmt_et(dt_str):
    dt = _to_et(dt_str)
    return dt.astimezone(_ET).strftime('%m/%d/%Y %I:%M:%S %p') if dt else None

def _fmt_date_et(dt_str):
    dt = _to_et(dt_str)
    return dt.astimezone(_ET).strftime('%m/%d/%Y') if dt else None

def _safe_float(val):
    """Safely convert to float, return None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def _google_distance(api_key, origin_lat, origin_lon, dest_lat, dest_lon, origin_str=None):
    if not api_key or None in (dest_lat, dest_lon):
        return None
    if origin_str:
        origin_param = origin_str
    elif origin_lat is not None and origin_lon is not None:
        origin_param = f"{origin_lat},{origin_lon}"
    else:
        return None
    try:
        resp = _requests.get(
            "https://maps.googleapis.com/maps/api/distancematrix/json",
            params={
                "origins": origin_param,
                "destinations": f"{dest_lat},{dest_lon}",
                "key": api_key,
                "units": "imperial",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        element = data.get("rows", [{}])[0].get("elements", [{}])[0]
        if element.get("status") == "OK":
            meters = element["distance"]["value"]
            return round(meters / 1609.344, 2)
    except Exception as e:
        log.warning('Google Distance Matrix failed: %s', e)
    return None

@router.get("/api/accounting/wo-adjustments")
def api_wo_adjustments(status: str = Query('open'), page: int = Query(0), page_size: int = Query(50),
                       product_filter: str = Query(''), rec_filter: str = Query(''), q: str = Query(''),
                       sort_col: str = Query('created_date'), sort_dir: str = Query('desc'),
                       start_date: str = Query(''), end_date: str = Query('')):
    cache_key = f'accounting_woa_list_{status}'
    def _compute():
        return _build_woa_list(status)
    full = cache.stale_while_revalidate(cache_key, _compute, ttl=900, stale_ttl=3600)
    items = full.get('items', [])

    # Server-side filtering
    if product_filter and product_filter != 'All':
        items = [r for r in items if product_filter.lower() in (r.get('product') or '').lower()]
    if rec_filter == 'Approve':
        items = [r for r in items if r.get('recommendation') == 'approve']
    elif rec_filter == 'Review':
        items = [r for r in items if r.get('recommendation') == 'review']
    elif rec_filter == 'Credit':
        items = [r for r in items if (r.get('requested_qty') or 0) < 0]
    if q:
        ql = q.lower()
        items = [r for r in items if ql in (r.get('woa_number') or '').lower()
                 or ql in (r.get('wo_number') or '').lower()
                 or ql in (r.get('facility') or '').lower()]
    if start_date:
        items = [r for r in items if (r.get('_sort_date') or '') >= start_date]
    if end_date:
        items = [r for r in items if (r.get('_sort_date') or '') <= end_date]

    # Server-side sort
    reverse = sort_dir == 'desc'
    actual_col = '_sort_date' if sort_col == 'created_date' else sort_col
    def _sort_key(r):
        v = r.get(actual_col, '') or ''
        if isinstance(v, (int, float)): return v
        return str(v).lower()
    try:
        items.sort(key=_sort_key, reverse=reverse)
    except Exception:
        pass

    # Aggregate totals across ALL filtered items (not just the page)
    total = len(items)
    total_requested = sum(r.get('requested_qty') or 0 for r in items)
    total_billed = sum(r.get('currently_paid') or 0 for r in items)
    total_approve = sum(1 for r in items if r.get('recommendation') == 'approve')
    total_review = sum(1 for r in items if r.get('recommendation') == 'review')

    start = page * page_size
    _STRIP = {'sf_miles', 'vehicle', 'woli_summary', '_sort_date'}
    page_items = [{k: v for k, v in r.items() if k not in _STRIP} for r in items[start:start + page_size]]
    return {
        'items': page_items, 'total': total, 'page': page, 'page_size': page_size,
        'totals': {
            'requested': round(total_requested, 2),
            'billed': round(total_billed, 2),
            'delta': round(total_requested - total_billed, 2),
            'approve_count': total_approve,
            'review_count': total_review,
        },
    }

def _build_woa_list(status_filter: str) -> dict:
    woa_rows = sf_query_all("""
        SELECT Id, Name, Quantity__c, CreatedDate, CreatedById, LastModifiedById,
               OwnerId, Owner.Name, CreatedBy.Name, LastModifiedBy.Name,
               Work_Order__c, Work_Order__r.WorkOrderNumber,
               Work_Order__r.ServiceTerritoryId,
               Work_Order__r.ServiceTerritory.Name,
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
               Work_Order__r.ERS_On_Location_Date_Time__c
        FROM ERS_Work_Order_Adjustment__c
        ORDER BY CreatedDate DESC
        LIMIT 15000
    """)

    if not woa_rows:
        return {'items': [], 'total': 0, 'status_filter': status_filter}

    import time as _time
    _t0 = _time.time()

    # Filter BEFORE WOLI query to reduce SF load (open = ~2500 vs all = ~15000)
    _ACCT_REVIEWERS = {'Paul Nigro', 'Kerry Smeal', 'Jessica Nunez'}
    if status_filter == 'open':
        woa_rows = [r for r in woa_rows
                    if r.get('CreatedById') == r.get('LastModifiedById')
                    and (r.get('CreatedBy') or {}).get('Name', '') not in _ACCT_REVIEWERS]

    wo_ids = list({r.get('Work_Order__c') for r in woa_rows if r.get('Work_Order__c')})
    log.info(f"WOA list: {len(woa_rows)} rows, {len(wo_ids)} unique WOs to query WOLIs")
    woli_rows = batch_soql_parallel("""
        SELECT Id, WorkOrderId, WorkOrder.WorkOrderNumber, PricebookEntry.Name,
               Quantity, TotalPrice, Description
        FROM WorkOrderLineItem
        WHERE WorkOrderId IN ('{id_list}')
    """, wo_ids, chunk_size=500) if wo_ids else []

    # Build WO → ALL WOLIs map (keep all line items per WO)
    from collections import defaultdict
    wo_wolis = defaultdict(list)
    for wl in woli_rows:
        wo_id = wl.get('WorkOrderId')
        if wo_id:
            pbe = (wl.get('PricebookEntry') or {}).get('Name') or ''
            wo_wolis[wo_id].append({
                'id': wl.get('Id'),
                'product': pbe,
                'code': pbe.split(' - ')[0].strip() if ' - ' in pbe else pbe.split(' ')[0] if pbe else '',
                'quantity': wl.get('Quantity'),
                'description': wl.get('Description'),
            })

    def _best_woli(wo_id, requested_qty):
        """Find the WOLI most likely related to this WOA."""
        wolis = wo_wolis.get(wo_id, [])
        if not wolis:
            return {}
        named = [w for w in wolis if w['product']]
        if not named:
            return wolis[0] if wolis else {}
        if len(named) == 1:
            return named[0]
        if requested_qty is not None:
            # Exact match first (e.g., requested=1.0 matches BA qty=1.0)
            exact = [w for w in named if w.get('quantity') is not None and abs((w['quantity']) - requested_qty) < 0.01]
            if len(exact) == 1:
                return exact[0]
            # Otherwise closest match, preferring non-BA
            non_ba = [w for w in named if w['code'] != 'BA']
            candidates = non_ba if non_ba else named
            candidates.sort(key=lambda w: abs((w.get('quantity') or 0) - requested_qty))
            return candidates[0]
        return named[0]

    items = []
    for r in woa_rows:
        woa_id = r.get('Id', '')
        wo = r.get('Work_Order__r') or {}
        wo_id = r.get('Work_Order__c', '')
        req_qty = _safe_float(r.get('Quantity__c'))
        woli = _best_woli(wo_id, req_qty)
        is_open = r.get('CreatedById') == r.get('LastModifiedById')

        product = woli.get('product') or ''
        code = woli.get('code') or ''
        paid = _safe_float(woli.get('quantity'))
        sf_er = _safe_float(wo.get('ERS_En_Route_Miles__c'))
        sf_est_er = _safe_float(wo.get('ERS_Estimated_En_Route_Miles__c'))
        sf_tow = _safe_float(wo.get('Tow_Miles__c'))
        sf_est_tow = _safe_float(wo.get('ERS_Estimated_Tow_Miles__c'))

        # Calculate on-location time from WO timestamps (for E1/MI)
        enroute_dt = _parse_dt(wo.get('ERS_En_Route_Date_Time__c'))
        onloc_dt = _parse_dt(wo.get('ERS_On_Location_Date_Time__c'))
        on_loc_min = round((onloc_dt - enroute_dt).total_seconds() / 60, 1) if enroute_dt and onloc_dt and onloc_dt > enroute_dt else None

        v_make = wo.get('Vehicle_Make__c') or ''
        v_model = wo.get('Vehicle_Model__c') or ''
        v_group = wo.get('Vehicle_Group__c') or ''
        all_wolis = wo_wolis.get(wo_id, [])

        rec, rec_reason, verification = _calc_recommendation(
            code, req_qty, paid, sf_er, sf_est_er, sf_tow, sf_est_tow,
            on_loc_minutes=on_loc_min,
            vehicle_weight=_safe_float(wo.get('Weight_lbs__c')),
            vehicle_group=v_group,
            all_wolis=all_wolis)

        # Append WO context to the reason tooltip
        if all_wolis:
            rec_reason += '\n\nWO LINE ITEMS:'
            for wl in all_wolis:
                if wl.get('product'):
                    rec_reason += f'\n  {wl["code"]:5s} {wl["product"]}: qty={wl.get("quantity")}'
        if v_make:
            rec_reason += f'\n\nVEHICLE: {v_make} {v_model} (group={v_group})'

        # WO line items summary for export
        woli_summary = ' | '.join(f'{wl["code"]}={wl.get("quantity")}' for wl in all_wolis if wl.get('product'))

        items.append({
            'id': woa_id,
            'woa_number': r.get('Name', ''),
            'product': product,
            'requested_qty': req_qty,
            'currently_paid': paid,
            'recommendation': rec,
            'rec_reason': rec_reason,
            'facility': (wo.get('Facility__r') or {}).get('Name', '') or wo.get('Facility_Name__c') or (wo.get('ServiceTerritory', {}).get('Name', '') if wo.get('ServiceTerritory') else ''),
            'wo_number': wo.get('WorkOrderNumber', ''),
            'wo_id': wo_id,
            'woli_id': woli.get('id') or '',
            'created_date': _fmt_date_et(r.get('CreatedDate')),
            '_sort_date': (r.get('CreatedDate') or '')[:10],
            'created_by': (r.get('CreatedBy') or {}).get('Name', ''),
            'sf_miles': {'enroute': sf_er, 'estimated_enroute': sf_est_er, 'tow': sf_tow, 'estimated_tow': sf_est_tow},
            'vehicle': {'make': v_make, 'model': v_model, 'group': v_group},
            'woli_summary': woli_summary,
        })

    log.info(f"WOA list built: {len(items)} items in {_time.time() - _t0:.1f}s")
    return {'items': items, 'total': len(items), 'status_filter': status_filter}

@router.get("/api/accounting/wo-adjustments/export")
def api_woa_export(status: str = Query('open'), product_filter: str = Query(''),
                   rec_filter: str = Query(''), q: str = Query(''),
                   start_date: str = Query(''), end_date: str = Query('')):
    cache_key = f'accounting_woa_list_{status}'
    full = cache.stale_while_revalidate(cache_key, lambda: _build_woa_list(status), ttl=900, stale_ttl=3600)
    items = full.get('items', [])
    if product_filter:
        items = [r for r in items if product_filter.lower() in (r.get('product') or '').lower()]
    if rec_filter == 'Approve':
        items = [r for r in items if r.get('recommendation') == 'approve']
    elif rec_filter == 'Review':
        items = [r for r in items if r.get('recommendation') == 'review']
    elif rec_filter == 'Credit':
        items = [r for r in items if (r.get('requested_qty') or 0) < 0]
    if q:
        ql = q.lower()
        items = [r for r in items if ql in (r.get('woa_number') or '').lower() or ql in (r.get('wo_number') or '').lower() or ql in (r.get('facility') or '').lower()]
    if start_date:
        items = [r for r in items if (r.get('_sort_date') or '') >= start_date]
    if end_date:
        items = [r for r in items if (r.get('_sort_date') or '') <= end_date]

    return build_export(items, status)

@router.get("/api/accounting/wo-adjustments/{woa_id}/audit")
def api_woa_audit(woa_id: str):
    woa_id = sanitize_soql(woa_id)
    cache_key = f'accounting_woa_audit_{woa_id}'

    cached = cache.get(cache_key) or cache.disk_get(cache_key, ttl=1800)
    if cached:
        return cached

    result = _build_woa_audit(woa_id)
    cache.put(cache_key, result, ttl=1800)
    cache.disk_put(cache_key, result, ttl=1800)
    return result

@router.post("/api/accounting/wo-adjustments/{woa_id}/recalculate")
def api_woa_recalculate(woa_id: str):
    woa_id = sanitize_soql(woa_id)
    cache_key = f'accounting_woa_audit_{woa_id}'
    cache.invalidate(cache_key)
    cache.disk_invalidate(cache_key)
    result = _build_woa_audit(woa_id)
    cache.put(cache_key, result, ttl=1800)
    cache.disk_put(cache_key, result, ttl=1800)
    return result


from routers.accounting_audit import _build_woa_audit
