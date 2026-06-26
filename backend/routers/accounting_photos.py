"""Accounting — photo fetching for WOA audit panel.

All WOs in the accounting audit are contractor WOs. Photo routing:

Primary: Service_Photo__c (Work_Order__c lookup) — used by ALL contractor types,
  both on-platform and Towbook. Photo_URL__c holds the Towbook S3 URL.

Fallback: ContentDocumentLink on WOLI 00000001 (pickup) and 00000002 (drop-off) —
  for facilities that upload via the FSL mobile app (e.g. facility 421).

The dispatch channel (on-platform vs Towbook) does NOT determine photo storage.
"""
import logging
import cache
from sf_client import sf_query_all, sanitize_soql

log = logging.getLogger('accounting')
_SF_BASE = 'https://aaawcny.lightning.force.com'


_SF_DOWNLOAD_PREFIX = f'{_SF_BASE}/sfc/servlet.shepherd/document/download/'


def _normalize_photo_url(raw_url: str, fallback_id: str) -> tuple[str, bool]:
    """Return (display_url, is_direct_image).

    SF download servlet URLs trigger a file-save dialog in Chrome.
    Convert them to the Lightning viewer URL which renders inline.
    Only truly external URLs (non-SF domain) are marked direct=True
    and rendered as <img> thumbnails.
    """
    if not raw_url:
        return f'{_SF_BASE}/{fallback_id}', False

    # SF servlet download → Lightning viewer (no download prompt)
    if raw_url.startswith(_SF_DOWNLOAD_PREFIX):
        doc_id = raw_url[len(_SF_DOWNLOAD_PREFIX):].split('?')[0].strip()
        return f'{_SF_BASE}/lightning/r/ContentDocument/{doc_id}/view', False

    # Any other SF-hosted URL → viewer / record page, not embeddable
    if raw_url.startswith(_SF_BASE) or 'force.com' in raw_url or 'salesforce.com' in raw_url:
        return raw_url, False

    # External URL (Towbook-hosted, etc.) → embeddable as <img>
    return raw_url, True


def fetch_photos(wo_id: str, woli_rows: list, is_fleet: bool) -> dict:
    """Return photos for the audit panel.

    All WOs in the accounting audit are contractor WOs. Contractors use
    Service_Photo__c as their primary photo store regardless of dispatch
    channel (both on-platform and Towbook contractors write here).

    CDL on WOLIs is the fallback for facilities that upload via the FSL
    mobile app instead (e.g. facility 421: numeric Facility_ID but FSL app).

    The is_fleet param is kept for signature compatibility but no longer
    drives routing — photo storage doesn't follow the dispatch channel.
    """
    result = _fetch_towbook_photos(wo_id)
    if result.get('photos'):
        return result

    if woli_rows:
        cdl = _fetch_on_platform_photos(wo_id, woli_rows)
        total = len(cdl.get('pickup_photos', [])) + len(cdl.get('dropoff_photos', []))
        if total > 0:
            log.info(f"WO {wo_id}: no Service_Photo__c found; using CDL fallback ({total} photos)")
            cdl['transitional_fallback'] = True
            return cdl

    return result


def _fetch_towbook_photos(wo_id: str) -> dict:
    """Towbook: direct photo URLs from Photo_URL__c field on Service_Photo__c."""
    cache_key = f'accounting:towbook_photos:{wo_id}'
    try:
        # Only serve from cache when photos actually exist — never cache empty results.
        # cached_query_persistent L1 uses raw keys (not version-prefixed), so stale
        # empty entries survive CACHE_VERSION bumps and cause list/detail mismatches.
        cached = cache.get(cache_key)
        if cached and cached.get('photos'):
            return cached

        rows = sf_query_all(f"""
            SELECT Id, Name, Photo_URL__c, Timestamp__c
            FROM Service_Photo__c
            WHERE Work_Order__c = '{sanitize_soql(wo_id)}'
            ORDER BY Timestamp__c ASC NULLS LAST
            LIMIT 30
        """)
        photos = []
        for r in (rows or []):
            url, direct = _normalize_photo_url(r.get('Photo_URL__c') or '', r.get('Id', ''))
            photos.append({'url': url, 'title': r.get('Name', ''), 'id': r.get('Id'), 'direct': direct})
        result = {'type': 'towbook', 'photos': photos}
        if photos:
            cache.put(cache_key, result, 3600)
        return result
    except Exception as e:
        log.warning(f"Towbook photos fetch failed for WO {wo_id}: {e}")
        return {'type': 'towbook', 'photos': [], 'error': str(e)[:200]}


def _fetch_on_platform_photos(wo_id: str, woli_rows: list) -> dict:
    """On-Platform (Fleet): ContentDocumentLinks on WOLI 00000001 (pickup) and 00000002 (drop-off)."""
    woli_map = {
        w.get('LineItemNumber'): w.get('Id')
        for w in (woli_rows or [])
        if w.get('LineItemNumber') and w.get('Id')
    }
    woli_01_id = woli_map.get('00000001')
    woli_02_id = woli_map.get('00000002')
    target_ids = [wid for wid in [woli_01_id, woli_02_id] if wid]

    if not target_ids:
        return {
            'type': 'on_platform',
            'pickup_photos': [], 'dropoff_photos': [],
            'woli_01_sf_url': f'{_SF_BASE}/{woli_01_id}' if woli_01_id else None,
            'woli_02_sf_url': f'{_SF_BASE}/{woli_02_id}' if woli_02_id else None,
        }

    id_list = ', '.join(f"'{sanitize_soql(i)}'" for i in target_ids)
    try:
        def _query():
            return sf_query_all(f"""
                SELECT LinkedEntityId, ContentDocumentId,
                       ContentDocument.Title, ContentDocument.FileType,
                       ContentDocument.CreatedDate,
                       ContentDocument.LatestPublishedVersionId
                FROM ContentDocumentLink
                WHERE LinkedEntityId IN ({id_list})
                  AND ContentDocument.FileType IN ('JPG', 'JPEG', 'PNG')
                ORDER BY ContentDocument.CreatedDate ASC
                LIMIT 40
            """)

        cache_key = f"accounting:on_platform_photos:{wo_id}:{':'.join(target_ids)}"
        # Only serve from cache when photos exist — same rationale as towbook path.
        cached = cache.get(cache_key)
        if cached and (cached.get('pickup_photos') or cached.get('dropoff_photos')):
            return cached

        rows = _query()

        def _link(r):
            doc_id = r.get('ContentDocumentId', '')
            version_id = (r.get('ContentDocument') or {}).get('LatestPublishedVersionId', '')
            return {
                'url': f'{_SF_BASE}/lightning/r/ContentDocument/{doc_id}/view',
                'title': (r.get('ContentDocument') or {}).get('Title', ''),
                'doc_id': doc_id,
                'version_id': version_id,
            }

        pickup = [_link(r) for r in (rows or []) if r.get('LinkedEntityId') == woli_01_id]
        dropoff = [_link(r) for r in (rows or []) if r.get('LinkedEntityId') == woli_02_id]
        result = {
            'type': 'on_platform',
            'pickup_photos': pickup,
            'dropoff_photos': dropoff,
            'woli_01_sf_url': f'{_SF_BASE}/{woli_01_id}' if woli_01_id else None,
            'woli_02_sf_url': f'{_SF_BASE}/{woli_02_id}' if woli_02_id else None,
        }
        if pickup or dropoff:
            cache.put(cache_key, result, 3600)
        return result
    except Exception as e:
        log.warning(f"On-platform photos fetch failed for WO {wo_id}: {e}")
        return {
            'type': 'on_platform',
            'pickup_photos': [], 'dropoff_photos': [],
            'woli_01_sf_url': f'{_SF_BASE}/{woli_01_id}' if woli_01_id else None,
            'woli_02_sf_url': f'{_SF_BASE}/{woli_02_id}' if woli_02_id else None,
            'error': str(e)[:200],
        }
