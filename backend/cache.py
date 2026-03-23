"""TTL cache with proactive refresh — designed for 1000+ concurrent users.

Architecture:
- L1: In-process memory dict (sub-microsecond, per-worker)
- L2: Disk cache on shared filesystem (5-50ms, shared across all workers/instances)
- Refresher: Background thread proactively refreshes all hot keys on a schedule
  → Users NEVER trigger Salesforce queries. Always served from L1 or L2.

Key behaviors:
1. Non-blocking reads: cached_query() never calls SF. Returns from L1 → L2 → stale → None.
2. Thundering herd: refresh_key() is called by ONE refresher process across the cluster.
3. Graceful degradation: If SF is down, stale data is served. If refresher dies, another takes over.
4. Persistent disk cache: Survives restarts and redeployments (Azure /home is durable storage).
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


# ── L1: In-process memory cache ─────────────────────────────────────────────

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


def cleanup_expired(max_stale_sec: int = 3600):
    """Remove entries that expired more than max_stale_sec ago.

    Stale entries are kept briefly for stale-while-revalidate reads,
    but entries expired over 1 hour ago are safe to purge. Prevents
    unbounded memory growth from parameterized cache keys.
    """
    with _lock:
        now = time.time()
        expired = [k for k, v in _store.items()
                   if now - v['expires'] > max_stale_sec]
        for k in expired:
            del _store[k]
    if expired:
        log.info(f"L1 cleanup: purged {len(expired)} expired entries")


# ── L2: Persistent disk cache ───────────────────────────────────────────────

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


# ── Multi-layer read (L1 → L2 → stale) ──────────────────────────────────────

def get_from_any_layer(key: str, ttl: int = DEFAULT_TTL):
    """Try every cache layer. Returns data or None. Never calls SF.

    Order: L1 fresh → L2 fresh → L1 stale → L2 stale → None
    """
    # L1 fresh
    result = get(key)
    if result is not None:
        return result
    # L2 fresh → promote to L1
    disk_result = disk_get(key, ttl)
    if disk_result is not None:
        put(key, disk_result, ttl)
        return disk_result
    # L1 stale (expired but still in memory)
    stale = get_stale(key)
    if stale is not None:
        return stale
    # L2 stale (expired but still on disk)
    disk_stale = disk_get_stale(key)
    if disk_stale is not None:
        put(key, disk_stale, 60)  # keep stale briefly in L1
        return disk_stale
    return None


# ── User-facing cache query (stale-while-revalidate) ────────────────────────

def cached_query(key: str, query_fn, ttl: int = DEFAULT_TTL):
    """Serve from cache with background re-fetch when expired.

    Behavior:
    - L1 fresh → return instantly (fast path)
    - L2 fresh → promote to L1, return instantly
    - L1/L2 expired → ONE thread re-fetches from SF, ALL others get stale data instantly
    - No cache at all → ONE thread fetches, others wait briefly (cold start)

    This is stale-while-revalidate: users NEVER see a blank screen.
    The refresher proactively expires keys on schedule, and this function
    handles the actual re-fetch with thundering-herd protection.
    """
    # Fast path: L1 fresh
    result = get(key)
    if result is not None:
        return result

    # L2 fresh → promote to L1
    disk_result = disk_get(key, ttl)
    if disk_result is not None:
        put(key, disk_result, ttl)
        return disk_result

    # Cache expired or missing — need to re-fetch.
    # Check if another thread is already fetching this key.
    with _lock:
        # Double-check after lock
        entry = _store.get(key)
        if entry and time.time() < entry['expires']:
            return entry['data']

        if key in _pending:
            # Another thread is already fetching — serve stale data instantly
            stale_entry = _store.get(key)
            if stale_entry:
                return stale_entry['data']
            # No stale data at all — wait briefly (cold start)
            event = _pending[key]
        else:
            event = Event()
            _pending[key] = event
            event = None  # WE are the fetcher

    if event is not None:
        # Another thread is fetching — return stale if available, else wait
        stale = get_stale(key)
        if stale is not None:
            return stale
        event.wait(timeout=15)
        result = get(key)
        if result is not None:
            return result
        stale2 = get_stale(key)
        if stale2 is not None:
            return stale2

    # We're the fetcher — query SF
    try:
        result = query_fn()
        put(key, result, ttl)
        return result
    except Exception as e:
        # Graceful degradation: serve stale data if SF fails
        stale = get_stale(key)
        if stale is not None:
            log.warning(f"SF error for '{key}': {e}. Serving stale cached data.")
            return stale
        log.error(f"SF error for '{key}': {e}. No cached data available.")
        raise
    finally:
        with _lock:
            evt = _pending.pop(key, None)
        if evt:
            evt.set()


def cached_query_persistent(key: str, query_fn, ttl: int = 86400):
    """Like cached_query but also persists to disk. Survives server restarts.

    Flow: L1 → L2 → fetch (cold start only) → store in L1 + L2
    """
    # Fast path: in-memory
    result = get(key)
    if result is not None:
        return result

    # Warm start: check disk
    disk_result = disk_get(key, ttl)
    if disk_result is not None:
        put(key, disk_result, ttl)
        return disk_result

    # Stale fallbacks
    stale = get_stale(key)
    if stale is not None:
        return stale
    disk_stale = disk_get_stale(key)
    if disk_stale is not None:
        put(key, disk_stale, 300)
        return disk_stale

    # Cold start fetch
    try:
        result = query_fn()
        put(key, result, ttl)
        disk_put(key, result, ttl)
        return result
    except Exception as e:
        log.error(f"Cold start persistent fetch failed for '{key}': {e}")
        raise


# ── Refresher-only: proactive cache refresh ──────────────────────────────────

def refresh_key(key: str, query_fn, ttl: int = DEFAULT_TTL, persist: bool = False):
    """Called by the refresher thread to proactively update a cache key.

    NOT called by user requests. This is the only function that intentionally
    calls SF on a schedule.
    """
    try:
        result = query_fn()
        put(key, result, ttl)
        if persist:
            disk_put(key, result, ttl)
        return True
    except Exception as e:
        log.warning(f"Refresher failed for '{key}': {e}")
        return False


# ── Filesystem locks (cross-worker, cross-instance) ─────────────────────────

def fs_lock_acquire(name: str, max_age: int = 1800) -> bool:
    """Acquire a filesystem-based lock. Returns True if acquired.

    Used for background generation tasks that should run in only one worker.
    Lock auto-expires after max_age seconds (default 30 min).
    """
    lock_path = _DISK_DIR / f'.lock_{name}'
    try:
        if lock_path.exists():
            age = time.time() - lock_path.stat().st_mtime
            if age < max_age:
                return False  # Lock is held and fresh
            # Stale lock — take over
            log.info(f"Stale lock '{name}' ({age:.0f}s old) — taking over")
        lock_path.write_text(json.dumps({
            'pid': os.getpid(),
            'time': time.time(),
            'host': os.environ.get('HOSTNAME', 'local'),
        }))
        return True
    except Exception:
        return False


def fs_lock_release(name: str):
    """Release a filesystem lock."""
    lock_path = _DISK_DIR / f'.lock_{name}'
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


# ── Stats ────────────────────────────────────────────────────────────────────

def stats():
    """Return cache statistics for monitoring."""
    with _lock:
        now = time.time()
        total = len(_store)
        alive = sum(1 for e in _store.values() if now < e['expires'])
        stale = total - alive
        pending = len(_pending)
    disk_files = list(_DISK_DIR.glob('*.json'))
    return {
        'total_keys': total,
        'alive': alive,
        'stale': stale,
        'pending_fetches': pending,
        'disk_cached': len(disk_files),
    }
