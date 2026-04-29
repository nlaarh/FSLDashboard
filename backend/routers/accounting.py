"""Accounting — Work Order Adjustment list, filtering, and export endpoints."""

import logging
from fastapi import APIRouter, HTTPException, Query

from sf_client import sf_query_all, sf_parallel, sanitize_soql
from sf_batch import batch_soql_parallel
from utils import parse_dt as _parse_dt
import cache
from routers.accounting_export import build_export
from routers.accounting_calc import (
    _to_et, _fmt_et, _fmt_date_et, _safe_float,
    _calc_recommendation, _SF_BASE,
)
from routers.accounting_audit import _build_woa_audit

router = APIRouter()
log = logging.getLogger('accounting')

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
               Work_Order__r.ERS_On_Location_Date_Time__c,
               Work_Order__r.Long_Tow_Used__c,
               Work_Order__r.Long_Tow_Miles__c
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
    import database as _db
    _rates = _db.get_accounting_rates_dict()
    _materiality = _rates.get('materiality_threshold_usd', 10.0)

    wo_wolis = defaultdict(list)
    for wl in woli_rows:
        wo_id = wl.get('WorkOrderId')
        if wo_id:
            pbe = (wl.get('PricebookEntry') or {}).get('Name') or ''
            qty = wl.get('Quantity')
            total_price = _safe_float(wl.get('TotalPrice'))
            unit_rate = (total_price / qty) if (qty and qty > 0 and total_price and total_price > 0) else None
            wo_wolis[wo_id].append({
                'id': wl.get('Id'),
                'product': pbe,
                'code': pbe.split(' - ')[0].strip() if ' - ' in pbe else pbe.split(' ')[0] if pbe else '',
                'quantity': qty,
                'unit_rate': unit_rate,
                'description': wl.get('Description'),
            })

    TOW_CODES = {'TW', 'TB', 'TT', 'TU', 'TM', 'EM'}

    def _best_woli(wo_id, requested_qty, wo=None):
        """Find the WOLI most likely related to this WOA.

        Matching priority:
        1. Exact quantity match across ALL named WOLIs (including BA) — single match wins
        2. Multiple non-BA WOLIs: closest quantity
        3. Single non-BA WOLI: check if WOA is for TW not yet billed
           (WO has tow estimate but no TW WOLI, and qty is closer to tow signal than ER)
        4. Fallback: the one non-BA WOLI
        """
        wolis = wo_wolis.get(wo_id, [])
        if not wolis:
            return {}
        named = [w for w in wolis if w['product']]
        if not named:
            return wolis[0] if wolis else {}

        non_ba = [w for w in named if w['code'] != 'BA']
        if not non_ba:
            return named[0]

        if requested_qty is not None:
            # Exact quantity match across ALL named WOLIs (BA included) — single unambiguous match wins
            exact = [w for w in named if w.get('quantity') is not None and abs(w['quantity'] - requested_qty) < 0.01]
            if len(exact) == 1:
                return exact[0]

            # Multiple non-BA WOLIs: closest quantity (works well for ER vs TW on same WO)
            if len(non_ba) > 1:
                candidates = sorted(non_ba, key=lambda w: abs((w.get('quantity') or 0) - requested_qty))
                return candidates[0]

            # Single non-BA WOLI: check if WOA is actually for TW not yet billed.
            # Pattern: WO has tow estimate > 0, no TW WOLI exists, and requested qty
            # is closer to the tow estimate than to the ER WOLI/estimate.
            if wo and not any(w['code'] in TOW_CODES for w in named):
                sf_tow = _safe_float(wo.get('Tow_Miles__c'))
                sf_est_tow = _safe_float(wo.get('ERS_Estimated_Tow_Miles__c'))
                tow_signal = max(sf_tow or 0, sf_est_tow or 0)
                if tow_signal > 0:
                    sf_er = _safe_float(wo.get('ERS_En_Route_Miles__c'))
                    sf_est_er = _safe_float(wo.get('ERS_Estimated_En_Route_Miles__c'))
                    er_woli_qty = non_ba[0].get('quantity') or 0
                    er_anchor = max(sf_er or 0, sf_est_er or 0, er_woli_qty)
                    dist_to_tow = abs(requested_qty - tow_signal)
                    dist_to_er = abs(requested_qty - er_anchor) if er_anchor > 0.1 else float('inf')
                    if dist_to_tow < dist_to_er:
                        tw_paid = sf_tow if sf_tow and sf_tow > 0.1 else 0
                        return {
                            'product': 'TW - Tow Miles',
                            'code': 'TW',
                            'quantity': tw_paid,
                            'description': None,
                            'id': '',
                            '_synthetic': True,
                        }

        return non_ba[0]

    items = []
    for r in woa_rows:
        woa_id = r.get('Id', '')
        wo = r.get('Work_Order__r') or {}
        wo_id = r.get('Work_Order__c', '')
        req_qty = _safe_float(r.get('Quantity__c'))
        woli = _best_woli(wo_id, req_qty, wo=wo)
        is_open = r.get('CreatedById') == r.get('LastModifiedById')

        product = woli.get('product') or ''
        code = woli.get('code') or ''
        paid = _safe_float(woli.get('quantity'))
        # When WO has multiple named non-BA WOLIs, build a comma-separated list for display
        all_named_non_ba = [w for w in wo_wolis.get(wo_id, []) if w.get('product') and w.get('code') != 'BA']
        all_products_str = ', '.join(
            f"{w['code']}={w.get('quantity')}" for w in all_named_non_ba if w.get('code')
        ) if len(all_named_non_ba) > 1 else ''
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
        long_tow_used = bool(wo.get('Long_Tow_Used__c'))
        long_tow_miles = _safe_float(wo.get('Long_Tow_Miles__c'))

        _CONFIDENCE_MAP = {
            'ER': 'HIGH', 'TW': 'HIGH', 'TB': 'HIGH', 'TT': 'HIGH', 'TU': 'HIGH', 'TM': 'HIGH', 'EM': 'HIGH',
            'E1': 'HIGH', 'E2': 'HIGH', 'Z8': 'HIGH',
            'MH': 'HIGH', 'MI': 'MEDIUM', 'TL': 'MEDIUM',
            'BA': 'LOW', 'BC': 'LOW', 'PC': 'LOW', 'HO': 'LOW', 'PG': 'LOW',
        }
        confidence = _CONFIDENCE_MAP.get(code, 'MEDIUM')
        # MH degrades to LOW when no weight data
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

        # Estimated dollar impact = NET additional cost (requested − already billed).
        # WOA.Quantity__c is the total the garage claims, so delta = requested − paid.
        _er_rate  = _rates.get('er_rate_per_mile',  1.75)
        _tow_rate = _rates.get('tow_rate_per_mile', 15.0)
        _e1_rate  = _rates.get('e1_rate_per_min',   0.75)
        _TOW_CODES_EST = {'TW', 'TB', 'TT', 'TU', 'TM', 'EM'}
        _TIME_CODES_EST = {'E1', 'E2', 'MI', 'Z8'}
        if req_qty is not None:
            _delta_qty = req_qty - (paid or 0)  # net additional units being claimed
            if code == 'TL':
                estimated_usd = round(abs(_delta_qty), 2)
            elif code == 'ER':
                estimated_usd = round(abs(_delta_qty) * _er_rate, 2)
            elif code in _TOW_CODES_EST:
                estimated_usd = round(abs(_delta_qty) * _tow_rate, 2)
            elif code in _TIME_CODES_EST:
                estimated_usd = round(abs(_delta_qty) * _e1_rate, 2)
            else:
                estimated_usd = None  # BA/flat — no reliable rate estimate
        else:
            estimated_usd = None
        is_low_materiality = (estimated_usd is not None and estimated_usd < _materiality)

        items.append({
            'id': woa_id,
            'woa_number': r.get('Name', ''),
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
            'wo_number': wo.get('WorkOrderNumber', ''),
            'wo_id': wo_id,
            'woli_id': woli.get('id') or '',
            'created_date': _fmt_date_et(r.get('CreatedDate')),
            '_sort_date': (r.get('CreatedDate') or '')[:10],
            'created_by': (r.get('CreatedBy') or {}).get('Name', ''),
            'sf_miles': {'enroute': sf_er, 'estimated_enroute': sf_est_er, 'tow': sf_tow, 'estimated_tow': sf_est_tow},
            'vehicle': {'make': v_make, 'model': v_model, 'group': v_group},
            'woli_summary': woli_summary,
            'estimated_usd': estimated_usd,
            'is_low_materiality': is_low_materiality,
        })

    # Post-process: per-WO WOA counts and same-product duplicate detection
    wo_total_counts = defaultdict(int)
    wo_code_counts = defaultdict(lambda: defaultdict(int))
    wo_code_qtys = defaultdict(list)      # (wo_id, code) → [requested_qty, ...]
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
            # Within 10% of max → quantities nearly identical → likely accidental re-submit
            qty_spread = (max_q - min_q) / max_q if max_q > 0 else 0
            item['is_possible_duplicate'] = qty_spread < 0.10
            item['is_multi_same_product'] = not item['is_possible_duplicate']
        else:
            item['is_possible_duplicate'] = False
            item['is_multi_same_product'] = False

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


@router.get("/api/accounting/rates")
def api_accounting_rates():
    """Public read-only: return accounting reference rates for the audit panel."""
    import database
    return {r['code']: r for r in database.get_accounting_rates()}


@router.get("/api/accounting/analytics")
def api_accounting_analytics(status: str = Query('open')):
    cache_key = f'accounting_woa_list_{status}'
    full = cache.stale_while_revalidate(cache_key, lambda: _build_woa_list(status), ttl=900, stale_ttl=3600)
    return _compute_analytics(full.get('items', []))


def _compute_analytics(items: list) -> dict:
    from collections import Counter, defaultdict
    import re as _re

    fac_stats: dict = defaultdict(lambda: {
        'count': 0, 'approve': 0, 'review': 0, 'est_usd': 0.0,
        'codes': Counter(), 'creators': Counter(),
    })
    prod_stats: Counter = Counter()
    prod_rec: dict = defaultdict(lambda: {'approve': 0, 'review': 0})
    creator_stats: Counter = Counter()
    creator_rec: dict = defaultdict(lambda: {'approve': 0, 'review': 0})
    approve_total = review_total = 0
    total_est_usd = 0.0
    _STOP = {'the','a','an','and','or','for','of','to','in','is','was','it','this','that',
             'with','on','at','from','by','per','no','not','na','was','are','be','we'}
    kw_counter: Counter = Counter()

    for item in items:
        fac     = item.get('facility') or 'Unknown'
        code    = item.get('code') or ''
        rec     = item.get('recommendation') or 'review'
        creator = item.get('created_by') or 'Unknown'
        est     = item.get('estimated_usd') or 0.0

        fs = fac_stats[fac]
        fs['count'] += 1
        fs['est_usd'] += est
        if code: fs['codes'][code] += 1
        fs['creators'][creator] += 1
        if rec == 'approve':
            fs['approve'] += 1; approve_total += 1
        else:
            fs['review'] += 1; review_total += 1

        if code:
            prod_stats[code] += 1
            prod_rec[code]['approve' if rec == 'approve' else 'review'] += 1
        creator_stats[creator] += 1
        creator_rec[creator]['approve' if rec == 'approve' else 'review'] += 1
        total_est_usd += est

        desc = (item.get('description') or '').lower()
        if desc:
            for w in _re.findall(r'\b[a-z]{3,}\b', desc):
                if w not in _STOP:
                    kw_counter[w] += 1

    by_fac = sorted([
        {
            'facility': fac,
            'count': s['count'],
            'approve': s['approve'],
            'review': s['review'],
            'risk_score': s['review'],  # WOAs needing manual review — primary sort key
            'approve_pct': round(s['approve'] / s['count'] * 100) if s['count'] else 0,
            'est_usd': round(s['est_usd'], 2),
            'all_codes': [{'code': c, 'count': n} for c, n in s['codes'].most_common()],
            'top_creators': [{'name': n, 'count': c} for n, c in s['creators'].most_common(3)],
        }
        for fac, s in fac_stats.items()
    ], key=lambda x: x['risk_score'], reverse=True)

    return {
        'total_woas': len(items),
        'total_facilities': len(fac_stats),
        'total_est_usd': round(total_est_usd, 2),
        'approve_count': approve_total,
        'review_count': review_total,
        'by_facility': by_fac[:50],
        'by_product': [
            {'code': c, 'count': n,
             'approve': prod_rec[c]['approve'], 'review': prod_rec[c]['review']}
            for c, n in prod_stats.most_common()
        ],
        'by_creator': [
            {'name': n, 'count': c,
             'approve': creator_rec[n]['approve'], 'review': creator_rec[n]['review']}
            for n, c in creator_stats.most_common(20)
        ],
        'keywords': [{'word': w, 'count': c} for w, c in kw_counter.most_common(30)],
    }


from pydantic import BaseModel
import concurrent.futures

class BatchAuditRequest(BaseModel):
    woa_ids: list[str] = []
    product_filter: str = ''

@router.post("/api/accounting/wo-adjustments/batch-audit")
def api_batch_audit(body: BatchAuditRequest):
    """Run audit on multiple WOAs in parallel. Returns cached results where available."""
    woa_ids = [sanitize_soql(wid) for wid in body.woa_ids[:50]]

    if not woa_ids and body.product_filter:
        full = cache.stale_while_revalidate('accounting_woa_list_open', lambda: _build_woa_list('open'), ttl=900, stale_ttl=3600)
        woa_ids = [r['id'] for r in full.get('items', [])
                   if body.product_filter.lower() in (r.get('product') or '').lower()][:50]

    def _audit_one(woa_id):
        ck = f'accounting_woa_audit_{woa_id}'
        cached = cache.get(ck) or cache.disk_get(ck, ttl=1800)
        if cached:
            return {'woa_id': woa_id, 'from_cache': True,
                    **{k: cached.get(k) for k in ('recommendation', 'confidence', 'woa_number')}}
        try:
            result = _build_woa_audit(woa_id)
            cache.put(ck, result, ttl=1800)
            cache.disk_put(ck, result, ttl=1800)
            return {'woa_id': woa_id, 'from_cache': False,
                    **{k: result.get(k) for k in ('recommendation', 'confidence', 'woa_number')}}
        except Exception as e:
            return {'woa_id': woa_id, 'error': str(e)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_audit_one, woa_ids))

    return {'total': len(results), 'results': results}
