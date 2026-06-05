"""Accounting — Work Order Adjustment list, filtering, and export endpoints."""

import logging
from fastapi import APIRouter, HTTPException, Query

from sf_client import sanitize_soql, SF_API_VERSION
import cache
from routers.accounting_export import build_export
from routers.accounting_pdf import build_woa_pdf
from routers.accounting_audit import _build_woa_data
from routers.accounting_audit_ai import call_audit_ai, _build_woa_audit
from routers.accounting_list import _build_woa_list
from repositories import accounting

router = APIRouter()
log = logging.getLogger('accounting')

@router.get("/api/accounting/wo-adjustments")
def api_wo_adjustments(status: str = Query('open'), page: int = Query(0), page_size: int = Query(50),
                       product_filter: str = Query(''), rec_filter: str = Query(''), q: str = Query(''),
                       sort_col: str = Query('created_date'), sort_dir: str = Query('desc'),
                       start_date: str = Query(''), end_date: str = Query('')):
    full = cache.stale_while_revalidate('accounting_woa_list', _build_woa_list, ttl=900, stale_ttl=86400)
    items = full.get('items', [])

    # Search override: if user typed a query, find matching records across ALL statuses first.
    # Status filter is skipped when a search is active so WOA# lookups always work.
    if q:
        ql = q.lower()
        items = [r for r in items if ql in (r.get('woa_number') or '').lower()
                 or ql in (r.get('wo_number') or '').lower()
                 or ql in (r.get('facility') or '').lower()
                 or ql in (r.get('program') or '').lower()]
    else:
        # Status filter applied in memory — New / Approved / Rejected / All
        if status in ('New', 'Approved', 'Rejected'):
            items = [r for r in items if r.get('status') == status]
        # Approved records: limit to last 3 months to keep list manageable
        if status == 'Approved':
            from datetime import datetime, timezone as _tz, timedelta as _td
            _cutoff = (datetime.now(_tz.utc) - _td(days=90)).strftime('%Y-%m-%d')
            items = [r for r in items if (r.get('_sort_date') or '') >= _cutoff]

    # Server-side filtering
    if product_filter and product_filter != 'All':
        items = [r for r in items if r.get('code', '').upper() == product_filter.upper()]
    if rec_filter == 'Approve':
        items = [r for r in items if r.get('recommendation') == 'approve']
    elif rec_filter == 'Review':
        items = [r for r in items if r.get('recommendation') == 'review']
    elif rec_filter == 'Credit':
        items = [r for r in items if (r.get('requested_qty') or 0) < 0]
    if start_date:
        items = [r for r in items if (r.get('_sort_date') or '') >= start_date]
    if end_date:
        items = [r for r in items if (r.get('_sort_date') or '') <= end_date]

    # Server-side sort
    reverse = sort_dir == 'desc'
    actual_col = '_sort_date' if sort_col == 'created_date' else sort_col
    def _sort_key(r):
        v = r.get(actual_col)
        if v is None:
            return (0, '') if actual_col in _NUMERIC_COLS else (0, '')
        if isinstance(v, (int, float)):
            return (1, v)
        return (1, str(v).lower())

    _NUMERIC_COLS = {'requested_qty', 'currently_paid', 'delta', 'woa_age_from_wo_days', 'woa_age_days'}
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
        'cached_at': full.get('cached_at', ''),
        'totals': {
            'requested': round(total_requested, 2),
            'billed': round(total_billed, 2),
            'delta': round(total_requested - total_billed, 2),
            'approve_count': total_approve,
            'review_count': total_review,
        },
    }


@router.get("/api/accounting/wo-adjustments/export")
def api_woa_export(status: str = Query('open'), product_filter: str = Query(''),
                   rec_filter: str = Query(''), q: str = Query(''),
                   start_date: str = Query(''), end_date: str = Query('')):
    full = cache.stale_while_revalidate('accounting_woa_list', _build_woa_list, ttl=900, stale_ttl=86400)
    items = full.get('items', [])
    if status in ('New', 'Approved', 'Rejected'):
        items = [r for r in items if r.get('status') == status]
    if product_filter:
        items = [r for r in items if r.get('code', '').upper() == product_filter.upper()]
    if rec_filter == 'Approve':
        items = [r for r in items if r.get('recommendation') == 'approve']
    elif rec_filter == 'Review':
        items = [r for r in items if r.get('recommendation') == 'review']
    elif rec_filter == 'Credit':
        items = [r for r in items if (r.get('requested_qty') or 0) < 0]
    if q:
        ql = q.lower()
        items = [r for r in items if ql in (r.get('woa_number') or '').lower() or ql in (r.get('wo_number') or '').lower() or ql in (r.get('facility') or '').lower() or ql in (r.get('program') or '').lower()]
    if start_date:
        items = [r for r in items if (r.get('_sort_date') or '') >= start_date]
    if end_date:
        items = [r for r in items if (r.get('_sort_date') or '') <= end_date]

    return build_export(items, status)

@router.get("/api/accounting/wo-adjustments/{woa_id}/audit")
def api_woa_audit(woa_id: str, force: bool = Query(False)):
    import time as _t
    from threading import Thread as _Thread
    woa_id = sanitize_soql(woa_id)
    full_key = f'{cache.CACHE_VERSION}_woa_audit_{woa_id}'
    data_key = f'{cache.CACHE_VERSION}_woa_data_{woa_id}'

    def _build_and_cache_audit():
        try:
            result = _build_woa_data(woa_id)
            result['cached_at'] = _t.strftime('%Y-%m-%d %H:%M:%S')
            cache.put(data_key, result, ttl=1800)
            cache.disk_put(data_key, result, ttl=86400)
        except Exception as e:
            log.warning(f"Background audit refresh failed for {woa_id}: {e}")

    if not force:
        # L1 or L2 fresh full result (with AI)
        full = cache.get(full_key) or cache.disk_get(full_key, ttl=1800)
        if full:
            if isinstance(full.get('recommendation'), str):
                full['recommendation'] = full['recommendation'].lower()
            return {**full, 'cache_status': 'fresh', 'cached_at': full.get('cached_at', '')}

        # L1 or L2 fresh data-only result
        cached_data = cache.get(data_key) or cache.disk_get(data_key, ttl=3600)
        if cached_data:
            cache.put(data_key, cached_data, ttl=1800)
            to_return = {k: v for k, v in cached_data.items() if not k.startswith('_')}
            return {**to_return, 'cache_status': 'fresh', 'cached_at': cached_data.get('cached_at', '')}

        # STALE: try full result (with AI) first, fall back to data-only
        stale_full = cache.disk_get_stale(full_key)
        stale_data = stale_full or cache.disk_get_stale(data_key)
        stale_key = full_key if stale_full else data_key
        if stale_data:
            if isinstance(stale_data.get('recommendation'), str):
                stale_data['recommendation'] = stale_data['recommendation'].lower()
            cache.put(stale_key, stale_data, ttl=120)
            to_return = {k: v for k, v in stale_data.items() if not k.startswith('_')}
            meta = cache.disk_get_meta(stale_key)
            _raw_cat = meta.get('created_at', stale_data.get('cached_at', ''))
            cached_at = str(_raw_cat).split('.')[0] if _raw_cat else ''
            _Thread(target=_build_and_cache_audit, daemon=True).start()
            return {**to_return, 'cache_status': 'stale', 'cached_at': cached_at}

    # Cold start or force refresh — build synchronously
    result = _build_woa_data(woa_id)
    result['cached_at'] = _t.strftime('%Y-%m-%d %H:%M:%S')
    to_return = {k: v for k, v in result.items() if not k.startswith('_')}
    cache.put(data_key, result, ttl=1800)
    cache.disk_put(data_key, result, ttl=86400)
    return {**to_return, 'cache_status': 'fresh'}


@router.get("/api/accounting/wo-adjustments/{woa_id}/pdf")
def api_woa_pdf(woa_id: str):
    from fastapi.responses import Response as _Resp
    woa_id = sanitize_soql(woa_id)
    full_key = f'{cache.CACHE_VERSION}_woa_audit_{woa_id}'
    data_key = f'{cache.CACHE_VERSION}_woa_data_{woa_id}'
    data = cache.get(full_key) or cache.get(data_key)
    if not data:
        data = _build_woa_data(woa_id)
        cache.put(data_key, data, ttl=1800)
    d = {k: v for k, v in data.items() if not k.startswith('_')}
    pdf = build_woa_pdf(d)
    fname = f'{d.get("woa_number", woa_id)}.pdf'
    return _Resp(content=pdf, media_type='application/pdf',
                 headers={'Content-Disposition': f'inline; filename="{fname}"'})


@router.get("/api/accounting/wo-adjustments/{woa_id}/ai-analysis")
def api_woa_ai_analysis(woa_id: str):
    """AI analysis for a single WOA — called separately so audit data loads first."""
    woa_id = sanitize_soql(woa_id)
    full_key = f'{cache.CACHE_VERSION}_woa_audit_{woa_id}'
    data_key = f'{cache.CACHE_VERSION}_woa_data_{woa_id}'

    # If we already ran the full audit (e.g. from recalculate), return cached AI fields
    full = cache.get(full_key) or cache.disk_get(full_key, ttl=1800)
    if full and full.get('ai_headline') is not None:
        return {k: full[k] for k in ('recommendation', 'confidence', 'ai_summary', 'ai_headline',
                                      'ai_story', 'ai_fraud_signals', 'ai_anomalies',
                                      'ai_what_to_do', 'ask_garage', 'ai_gvw') if k in full}

    # Get data context from cache or rebuild
    data = cache.get(data_key)
    if not data:
        data = _build_woa_data(woa_id)
        cache.put(data_key, data, ttl=1800)

    ctx = data.get('_ai_context') or {}
    gh = data.get('_garage_history')
    ai = call_audit_ai(ctx, gh)

    ai_fields = {
        'ai_recommendation': ai['recommendation'], 'confidence': ai['confidence'],
        'ai_summary': ai['ai_summary'], 'ai_headline': ai.get('headline'),
        'ai_story': ai.get('story'), 'ai_fraud_signals': ai.get('fraud_signals') or [],
        'ai_anomalies': ai.get('anomalies') or [], 'ai_what_to_do': ai.get('what_to_do') or [],
        'ask_garage': ai.get('ask_garage') or [],
    }
    if ai.get('ai_gvw'):
        ai_fields['ai_gvw'] = ai['ai_gvw']

    # Merge into full result and cache — rule engine's recommendation is authoritative.
    # AI assessment goes in ai_recommendation so the UI can show it alongside (aiRecDiffers).
    full_result = {k: v for k, v in data.items() if not k.startswith('_')}
    full_result.update(ai_fields)
    # Ensure rule engine recommendation stays lowercase (belt-and-suspenders vs stale caches)
    if 'recommendation' in full_result:
        full_result['recommendation'] = (full_result['recommendation'] or 'review').lower()
    cache.put(full_key, full_result, ttl=1800)
    cache.disk_put(full_key, full_result, ttl=86400)
    return ai_fields


@router.post("/api/accounting/wo-adjustments/{woa_id}/recalculate")
def api_woa_recalculate(woa_id: str):
    woa_id = sanitize_soql(woa_id)
    full_key = f'{cache.CACHE_VERSION}_woa_audit_{woa_id}'
    data_key = f'{cache.CACHE_VERSION}_woa_data_{woa_id}'
    cache.invalidate(full_key); cache.disk_invalidate(full_key)
    cache.invalidate(data_key)
    result = _build_woa_audit(woa_id)
    cache.put(full_key, result, ttl=1800)
    cache.disk_put(full_key, result, ttl=86400)
    return result


@router.post("/api/accounting/refresh")
def api_accounting_refresh():
    """Bust the WOA list caches so the next request rebuilds from Salesforce."""
    cache.invalidate('accounting_woa_list')
    return {'status': 'ok', 'message': 'WOA list caches cleared'}


@router.get("/api/accounting/rates")
def api_accounting_rates():
    """Public read-only: return accounting reference rates for the audit panel."""
    return {r['code']: r for r in accounting.get_accounting_rates()}


@router.get("/api/accounting/analytics")
def api_accounting_analytics(status: str = Query('open')):
    full = cache.stale_while_revalidate('accounting_woa_list', _build_woa_list, ttl=900, stale_ttl=86400)
    items = full.get('items', [])
    if status == 'open':
        items = [r for r in items if r.get('status') == 'New']
    return _compute_analytics(items)


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
    mem_stats: dict = defaultdict(lambda: {'count': 0, 'approve': 0, 'review': 0})
    svc_stats: dict = defaultdict(lambda: {'count': 0, 'approve': 0, 'review': 0})
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

        program = item.get('program') or 'Unknown'
        svc_type = item.get('service_type') or 'Unknown'
        mem_stats[program]['count'] += 1
        mem_stats[program]['approve' if rec == 'approve' else 'review'] += 1
        svc_stats[svc_type]['count'] += 1
        svc_stats[svc_type]['approve' if rec == 'approve' else 'review'] += 1

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
        'by_program': sorted([
            {'type': t, 'count': s['count'], 'approve': s['approve'], 'review': s['review']}
            for t, s in mem_stats.items()
        ], key=lambda x: x['count'], reverse=True),
        'by_service_type': sorted([
            {'type': t, 'count': s['count'], 'approve': s['approve'], 'review': s['review']}
            for t, s in svc_stats.items()
        ], key=lambda x: x['count'], reverse=True),
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
        full = cache.stale_while_revalidate('accounting_woa_list', _build_woa_list, ttl=900, stale_ttl=86400)
        woa_ids = [r['id'] for r in full.get('items', [])
                   if r.get('status') == 'New'
                   and r.get('code', '').upper() == body.product_filter.upper()][:50]

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


@router.get("/api/accounting/sf-photo/{version_id}")
def sf_photo_proxy(version_id: str):
    """Proxy a Salesforce ContentVersion binary so the frontend can render it as <img>."""
    import requests
    from fastapi.responses import StreamingResponse
    from sf_client import get_auth
    version_id = sanitize_soql(version_id)
    try:
        token, instance = get_auth()
        url = f"{instance}/services/data/{SF_API_VERSION}/sobjects/ContentVersion/{version_id}/VersionData"
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, stream=True, timeout=15)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="SF photo not found")
        content_type = resp.headers.get('Content-Type', 'image/jpeg')
        return StreamingResponse(resp.iter_content(chunk_size=8192), media_type=content_type)
    except HTTPException:
        raise
    except Exception as e:
        log.warning(f"SF photo proxy failed for {version_id}: {e}")
        raise HTTPException(status_code=502, detail="Could not fetch photo from Salesforce")
