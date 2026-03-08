"""TTL cache with thundering-herd protection and graceful degradation.

Designed for 25+ concurrent dispatchers hitting the same Salesforce data.

Key behaviors:
1. Thundering herd: When cache expires, ONE thread fetches, others wait.
2. Graceful degradation: If SF is down, serve stale cached data instead of crashing.
3. Stale-while-revalidate: Expired data is kept in memory as a fallback.
"""

import time, logging
from threading import Lock, Event

log = logging.getLogger('cache')

_store = {}
_lock = Lock()
_pending = {}  # key -> Event (prevents duplicate fetches)
DEFAULT_TTL = 300  # 5 minutes


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
    - Other 24 wait on an Event and get the same result
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
            event = _pending[key]
        else:
            event = Event()
            _pending[key] = event
            event = None  # Signal that WE should do the fetch

    if event is not None:
        # Wait for the other thread to finish (up to 120s)
        event.wait(timeout=120)
        result = get(key)
        if result is not None:
            return result
        # Other thread may have failed — try stale
        stale = get_stale(key)
        if stale is not None:
            return stale
        # No data at all — fall through to fetch ourselves

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
    return {
        'total_keys': total,
        'alive': alive,
        'stale': stale,
        'pending_fetches': pending,
    }
