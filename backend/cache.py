"""TTL cache with proactive refresh — designed for 1000+ concurrent users.

Architecture:
- L1: In-process memory dict (sub-microsecond, per-worker)
- L2: SQLite persistent cache (5-50ms, shared across all workers/instances)
- Refresher: Background thread proactively refreshes all hot keys on a schedule
  → Users NEVER trigger Salesforce queries. Always served from L1 or L2.

Key behaviors:
1. Non-blocking reads: cached_query() never calls SF. Returns from L1 → L2 → stale → None.
2. Thundering herd: refresh_key() is called by ONE refresher process across the cluster.
3. Graceful degradation: If SF is down, stale data is served. If refresher dies, another takes over.
4. Persistent L2 cache: Survives restarts and redeployments (SQLite on Azure /home).
"""

import time, logging, os, json
from threading import Lock, Event
from pathlib import Path

log = logging.getLogger('cache')

# ── Cache version — bump this when response shapes change to auto-invalidate ──
CACHE_VERSION = 'v4'

_store = {}
_lock = Lock()
_pending = {}  # key -> Event (prevents duplicate fetches)
DEFAULT_TTL = 300  # 5 minutes


def _vkey(key: str) -> str:
    """Prefix cache key with version for auto-invalidation."""
    return f"{CACHE_VERSION}:{key}"


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
    """Clear L1 entries matching prefix. Also clears L2 (SQLite)."""
    with _lock:
        keys = [k for k in _store if k.startswith(prefix)]
        for k in keys:
            del _store[k]
    # Also clear L2
    try:
        import database
        database.cache_delete_prefix(_vkey(prefix))
    except Exception:
        pass


def cleanup_expired(max_stale_sec: int = 3600):
    """Remove L1 entries that expired more than max_stale_sec ago."""
    with _lock:
        now = time.time()
        expired = [k for k, v in _store.items()
                   if now - v['expires'] > max_stale_sec]
        for k in expired:
            del _store[k]
    if expired:
        log.info(f"L1 cleanup: purged {len(expired)} expired entries")


# ── L2: SQLite persistent cache ──────────────────────────────────────────────

def disk_get(key: str, ttl: int = 86400):
    """Read from L2 SQLite cache. Returns data if fresh, else None."""
    try:
        import database
        return database.cache_get(_vkey(key))
    except Exception:
        return None


def disk_get_stale(key: str):
    """Read from L2 even if expired (fallback)."""
    try:
        import database
        return database.cache_get_stale(_vkey(key))
    except Exception:
        return None


def disk_put(key: str, data, ttl: int = 86400):
    """Write to L2 SQLite cache."""
    try:
        import database
        database.cache_put(_vkey(key), data, ttl)
    except Exception as e:
        log.warning(f'Failed to write L2 cache for {key}: {e}')


def disk_get_meta(key: str) -> dict:
    """Get cache entry metadata (created_at). Returns {} if not found."""
    try:
        import database
        return database.cache_get_meta(_vkey(key))
    except Exception:
        return {}


def disk_invalidate(key: str):
    """Remove a specific L2 cache entry."""
    try:
        import database
        database.cache_delete(_vkey(key))
    except Exception:
        pass


# ── Multi-layer read (L1 → L2 → stale) ──────────────────────────────────────

def get_from_any_layer(key: str, ttl: int = DEFAULT_TTL):
    """Try every cache layer. Returns data or None. Never calls SF."""
    result = get(key)
    if result is not None:
        return result
    disk_result = disk_get(key, ttl)
    if disk_result is not None:
        put(key, disk_result, ttl)
        return disk_result
    stale = get_stale(key)
    if stale is not None:
        return stale
    disk_stale = disk_get_stale(key)
    if disk_stale is not None:
        put(key, disk_stale, 60)
        return disk_stale
    return None


# ── User-facing cache query (stale-while-revalidate) ────────────────────────

def cached_query(key: str, query_fn, ttl: int = DEFAULT_TTL):
    """Serve from cache with background re-fetch when expired.

    L1 fresh → L2 fresh → ONE thread re-fetches, others get stale → cold start wait.
    """
    result = get(key)
    if result is not None:
        return result

    disk_result = disk_get(key, ttl)
    if disk_result is not None:
        put(key, disk_result, ttl)
        return disk_result

    with _lock:
        entry = _store.get(key)
        if entry and time.time() < entry['expires']:
            return entry['data']

        if key in _pending:
            stale_entry = _store.get(key)
            if stale_entry:
                return stale_entry['data']
            event = _pending[key]
        else:
            event = Event()
            _pending[key] = event
            event = None

    if event is not None:
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

    try:
        result = query_fn()
        put(key, result, ttl)
        return result
    except Exception as e:
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


def cached_query_persistent(key: str, query_fn, ttl: int = 86400, max_stale_hours: int = 0):
    """Like cached_query but persists to L2 SQLite. Survives restarts.

    If max_stale_hours > 0: auto-regenerates when data is older than that,
    regardless of TTL. Used for data that should refresh nightly but never
    expire (satisfaction, garage scorecards). Returns cached_at in result if
    query_fn returns a dict.
    """
    NEVER_EXPIRE = 365 * 86400

    result = get(key)
    if result is not None and max_stale_hours == 0:
        return result

    disk_result = disk_get(key, NEVER_EXPIRE if max_stale_hours else ttl)

    # Check staleness if max_stale_hours is set
    if disk_result is not None and max_stale_hours > 0:
        meta = disk_get_meta(key)
        created_at = meta.get('created_at', '')
        is_stale = True
        if created_at:
            try:
                from datetime import datetime as _dt
                ct = _dt.strptime(created_at, '%Y-%m-%d %H:%M:%S')
                age_hours = (_dt.now() - ct).total_seconds() / 3600
                is_stale = age_hours > max_stale_hours
            except Exception:
                is_stale = True
        if not is_stale:
            # Fresh enough — serve from cache
            if result is None:
                put(key, disk_result, NEVER_EXPIRE)
            return disk_result
        # Stale — fall through to regenerate
        log.info(f"Cache '{key}' stale ({created_at}, >{max_stale_hours}h) — regenerating")
    elif disk_result is not None:
        put(key, disk_result, ttl)
        return disk_result

    # Stale fallbacks (serve old data while regenerating would block)
    if max_stale_hours == 0:
        stale = get_stale(key)
        if stale is not None:
            return stale
        disk_stale = disk_get_stale(key)
        if disk_stale is not None:
            put(key, disk_stale, 300)
            return disk_stale

    # Fetch fresh data
    try:
        result = query_fn()
        if isinstance(result, dict):
            result['cached_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        effective_ttl = NEVER_EXPIRE if max_stale_hours else ttl
        put(key, result, effective_ttl)
        disk_put(key, result, effective_ttl)
        return result
    except Exception as e:
        # Graceful degradation — serve stale if available
        stale = disk_result or get_stale(key) or disk_get_stale(key)
        if stale is not None:
            log.warning(f"Regen failed for '{key}': {e}. Serving stale data.")
            put(key, stale, 300)
            return stale
        log.error(f"Persistent fetch failed for '{key}': {e}")
        raise


# ── Refresher-only: proactive cache refresh ──────────────────────────────────

def refresh_key(key: str, query_fn, ttl: int = DEFAULT_TTL, persist: bool = False):
    """Called by the refresher thread to proactively update a cache key."""
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
# Keep filesystem-based locks — SQLite row-level locking isn't ideal for
# long-running background tasks across multiple workers.

_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_LOCK_DIR = Path('/home/fslapp/locks') if _ON_AZURE else Path(os.path.expanduser('~/.fslapp/locks'))
_LOCK_DIR.mkdir(parents=True, exist_ok=True)

def fs_lock_acquire(name: str, max_age: int = 1800) -> bool:
    """Acquire a filesystem-based lock. Returns True if acquired."""
    lock_path = _LOCK_DIR / f'.lock_{name}'
    try:
        if lock_path.exists():
            age = time.time() - lock_path.stat().st_mtime
            if age < max_age:
                return False
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
    lock_path = _LOCK_DIR / f'.lock_{name}'
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
    try:
        import database
        db_stats = database.cache_stats()
    except Exception:
        db_stats = {'total_keys': 0, 'alive': 0, 'stale': 0}
    return {
        'l1_total': total,
        'l1_alive': alive,
        'l1_stale': stale,
        'l1_pending': pending,
        'l2_total': db_stats['total_keys'],
        'l2_alive': db_stats['alive'],
        'l2_stale': db_stats['stale'],
    }
