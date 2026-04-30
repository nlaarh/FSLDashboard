"""Accounting AI endpoints — on-demand analytics story and aging breakdown."""

import logging
from datetime import date as _date
from collections import defaultdict
from fastapi import APIRouter, Query
import cache
from routers.accounting_audit_ai import build_analytics_story
from routers.accounting import _build_woa_list, _compute_analytics

router = APIRouter()
log = logging.getLogger('accounting')

_AGING_BUCKETS = [
    ('0–15d',  0,  15),
    ('16–30d', 16, 30),
    ('31–45d', 31, 45),
    ('46–60d', 46, 60),
    ('61–90d', 61, 90),
    ('90+d',   91, 99999),
]
_BUCKET_KEYS = [b[0] for b in _AGING_BUCKETS]


@router.get("/api/accounting/analytics/aging")
def api_accounting_aging(status: str = Query('open')):
    """Per-garage WOA aging breakdown — counts and $ exposure by age bucket."""
    cache_key = f'accounting_aging_{status}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    full = cache.stale_while_revalidate('accounting_woa_list', _build_woa_list, ttl=900, stale_ttl=3600)
    items = full.get('items', [])
    if status == 'open':
        items = [r for r in items if r.get('status') == 'New']

    today = _date.today()
    fac_data: dict = defaultdict(lambda: {
        'facility': '',
        'total': 0,
        'oldest_days': 0,
        'total_usd': 0.0,
        'cells': {k: {'count': 0, 'usd': 0.0, 'woas': []} for k in _BUCKET_KEYS},
    })

    for item in items:
        sort_date = item.get('_sort_date', '')
        if not sort_date:
            continue
        try:
            age = (today - _date.fromisoformat(sort_date[:10])).days
        except Exception:
            continue

        facility = item.get('facility') or 'Unknown'
        fd = fac_data[facility]
        fd['facility'] = facility
        fd['total'] += 1
        if age > fd['oldest_days']:
            fd['oldest_days'] = age
        usd = item.get('estimated_usd') or 0.0
        fd['total_usd'] += usd

        bucket_key = _BUCKET_KEYS[-1]
        for bk, lo, hi in _AGING_BUCKETS:
            if lo <= age <= hi:
                bucket_key = bk
                break

        cell = fd['cells'][bucket_key]
        cell['count'] += 1
        cell['usd'] += usd
        cell['woas'].append({
            'id': item.get('id'),
            'woa_number': item.get('woa_number'),
            'code': item.get('code'),
            'estimated_usd': round(usd, 2),
            'age_days': age,
            'recommendation': item.get('recommendation'),
        })

    facilities = sorted(fac_data.values(), key=lambda x: x['oldest_days'], reverse=True)
    for f in facilities:
        f['total_usd'] = round(f['total_usd'], 2)
        for cell in f['cells'].values():
            cell['usd'] = round(cell['usd'], 2)
            cell['woas'].sort(key=lambda w: w['age_days'], reverse=True)

    result = {'as_of': today.isoformat(), 'buckets': _BUCKET_KEYS, 'facilities': facilities}
    cache.put(cache_key, result, ttl=900)
    return result


@router.get("/api/accounting/analytics/ai-insights")
def api_accounting_ai_insights(status: str = Query('open')):
    """Generate an on-demand accountant narrative from current analytics data.
    Cached for 30 minutes so repeated clicks are instant.
    """
    cache_key = f'accounting_ai_insights_{status}'

    cached = cache.get(cache_key)
    if cached:
        return cached

    full = cache.stale_while_revalidate(
        'accounting_woa_list',
        lambda: _build_woa_list(),
        ttl=900, stale_ttl=3600,
    )
    items = full.get('items', [])
    if status == 'open':
        items = [r for r in items if r.get('status') == 'New']
    analytics = _compute_analytics(items)
    result = build_analytics_story(analytics)
    cache.put(cache_key, result, ttl=1800)
    return result
