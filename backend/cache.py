"""TTL cache with thundering-herd protection and graceful degradation.

Designed for 25+ concurrent dispatchers hitting the same Salesforce data.

Key behaviors:
1. Thundering herd: When cache expires, ONE thread fetches, others get stale data instantly.
2. Graceful degradation: If SF is down, serve stale cached data instead of crashing.
3. Stale-while-revalidate: Expired data is kept in memory as a fallback.
4. Persistent disk cache: For expensive/static queries that should survive restarts.
"""

import time, logging, json, os
from threading import Lock, Event
from pathlib import Path

log = logging.getLogger('cache')

_store = {}
_lock = Lock()
_pending = {}  # key -> Event (prevents duplicate fetches)
DEFAULT_TTL = 300  # 5 minutes

# Persistent disk cache directory
# On Azure App Service, /home is backed by Azure Storage and persists across
# restarts AND redeployments. Locally, use ~/.fslapp/cache.
_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_DISK_DIR = Path('/home/fslapp/cache') if _ON_AZURE else Path(os.path.expanduser('~/.fslapp/cache'))
_DISK_DIR.mkdir(parents=True, exist_ok=True)


def get(key: str):
    with _lock:
        entry = _store.get(key)
        if entry and time.time() < entry['expires']:
            return entry['data']
    return None


def get_stale(key: str):
    """Return cached data even if expired (for graceful degradation)."""
    with _lock:
        entry = _store.get(key)
        if entry:
            return entry['data']
    return None


def put(key: str, data, ttl: int = DEFAULT_TTL):
    with _lock:
        _store[key] = {'data': data, 'expires': time.time() + ttl}


def invalidate(prefix: str = ''):
    with _lock:
        keys = [k for k in _store if k.startswith(prefix)]
        for k in keys:
            del _store[k]


def cached_query(key: str, query_fn, ttl: int = DEFAULT_TTL):
    """Run query_fn only if result not cached. Thundering-herd safe.

    If 25 dispatchers hit the same endpoint simultaneously:
    - First request fetches from Salesforce
    - Other 24 get stale data instantly (no blocking!)
    - Zero duplicate Salesforce queries

    If Salesforce is down (circuit breaker open, timeout, error):
    - Returns stale cached data if available
    - Only raises if there's no cached data at all
    """
    # Fast path: fresh cache hit
    result = get(key)
    if result is not None:
        return result

    # Check if another thread is already fetching this key
    with _lock:
        # Double-check after acquiring lock
        entry = _store.get(key)
        if entry and time.time() < entry['expires']:
            return entry['data']

        if key in _pending:
            # Another thread is already fetching — serve stale data immediately
            # instead of blocking. This prevents the entire server from hanging
            # when a single SF query is slow (critical with --workers 1).
            stale_entry = _store.get(key)
            if stale_entry:
                return stale_entry['data']
            # No stale data at all — wait briefly (10s max)
            event = _pending[key]
        else:
            event = Event()
            _pending[key] = event
            event = None  # Signal that WE should do the fetch

    if event is not None:
        # Only reach here if no stale data exists — wait briefly
        event.wait(timeout=10)
        result = get(key)
        if result is not None:
            return result
        stale = get_stale(key)
        if stale is not None:
            return stale
        # Still nothing — fall through to fetch ourselves

    # We're the fetcher
    try:
        result = query_fn()
        put(key, result, ttl)
        return result
    except Exception as e:
        # GRACEFUL DEGRADATION: If SF fails, serve stale data
        stale = get_stale(key)
        if stale is not None:
            log.warning(f"SF error for '{key}': {e}. Serving stale cached data.")
            return stale
        # No stale data — re-raise so the API returns an error
        log.error(f"SF error for '{key}': {e}. No cached data available.")
        raise
    finally:
        with _lock:
            evt = _pending.pop(key, None)
        if evt:
            evt.set()  # Wake up all waiting threads


def stats():
    """Return cache statistics for monitoring."""
    with _lock:
        now = time.time()
        total = len(_store)
        alive = sum(1 for e in _store.values() if now < e['expires'])
        stale = total - alive
        pending = len(_pending)
    # Count disk cache files
    disk_files = list(_DISK_DIR.glob('*.json'))
    return {
        'total_keys': total,
        'alive': alive,
        'stale': stale,
        'pending_fetches': pending,
        'disk_cached': len(disk_files),
    }


# ── Persistent disk cache ────────────────────────────────────────────────────

def _disk_path(key: str) -> Path:
    safe = key.replace('/', '_').replace('\\', '_').replace(' ', '_')
    return _DISK_DIR / f'{safe}.json'


def disk_get(key: str, ttl: int = 86400):
    """Read from disk cache. Returns data if fresh (within ttl seconds), else None."""
    path = _disk_path(key)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        if time.time() < raw.get('expires', 0):
            return raw['data']
        # Expired but still on disk — return as stale fallback
        return None
    except Exception:
        return None


def disk_get_stale(key: str):
    """Read from disk cache even if expired (fallback)."""
    path = _disk_path(key)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        return raw.get('data')
    except Exception:
        return None


def disk_put(key: str, data, ttl: int = 86400):
    """Write to disk cache with TTL (default 24 hours)."""
    path = _disk_path(key)
    try:
        path.write_text(json.dumps({
            'data': data,
            'expires': time.time() + ttl,
            'cached_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }))
    except Exception as e:
        log.warning(f'Failed to write disk cache for {key}: {e}')


def disk_invalidate(key: str):
    """Remove a specific disk cache entry."""
    path = _disk_path(key)
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def cached_query_persistent(key: str, query_fn, ttl: int = 86400):
    """Like cached_query but also persists to disk. Survives server restarts.

    Flow:
    1. Check in-memory cache (fast path)
    2. Check disk cache (warm start after restart)
    3. Fetch from Salesforce, store in both memory + disk
    """
    # Fast path: in-memory
    result = get(key)
    if result is not None:
        return result

    # Warm start: check disk
    disk_result = disk_get(key, ttl)
    if disk_result is not None:
        put(key, disk_result, ttl)  # Promote to memory
        return disk_result

    # Fetch fresh — use same thundering-herd logic
    try:
        result = query_fn()
        put(key, result, ttl)
        disk_put(key, result, ttl)
        return result
    except Exception as e:
        # Try stale from disk
        stale = disk_get_stale(key)
        if stale is not None:
            log.warning(f"SF error for '{key}': {e}. Serving stale disk cache.")
            put(key, stale, 300)  # Keep stale in memory briefly
            return stale
        raise
