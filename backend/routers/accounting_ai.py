"""Accounting AI endpoints — on-demand analytics story for accountants."""

import logging
from fastapi import APIRouter, Query
import cache
from routers.accounting_audit_ai import build_analytics_story
from routers.accounting import _build_woa_list, _compute_analytics

router = APIRouter()
log = logging.getLogger('accounting')


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
