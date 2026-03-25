"""Proactive cache refresher — keeps all hot cache keys warm on a schedule.

Users NEVER trigger Salesforce queries. The refresher runs in one background
thread and refreshes all frequently-accessed endpoints on a timer.

Leader election: Only ONE process across all Gunicorn workers and Azure instances
runs the refresher. Uses a filesystem lock on the shared /home directory.
If the leader dies, another worker takes over within 2 cycles.

SF call budget: ~10-15 calls/min constant, regardless of user count.
"""

import os, time, threading, logging
from pathlib import Path

import cache

log = logging.getLogger('refresher')

# Lock file for leader election — only one refresher runs across all workers/instances
_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_LOCK_DIR = Path('/home/fslapp/cache') if _ON_AZURE else Path(os.path.expanduser('~/.fslapp/cache'))
_LOCK_FILE = _LOCK_DIR / '.refresher_leader.lock'
_LEADER_STALE_AGE = 60    # seconds before a leader lock is considered stale


# ── Refresh schedule ─────────────────────────────────────────────────────────
# Each entry: (interval_sec, cache_key, endpoint_fn, ttl, persist_to_disk)
#
# Strategy: To refresh a key, we invalidate L1 then call the endpoint function.
# The endpoint hits cached_query() which sees an L1 miss, falls through to
# cold-start, queries SF, and repopulates the cache. Clean and simple.

def _get_schedule():
    """Build the refresh schedule. Called once after all modules are imported."""
    from dispatch import get_live_queue
    from ops import get_ops_territories, get_ops_garages, _get_priority_matrix
    from routers.command_center import command_center
    from routers.ops import ops_brief
    from routers.map import get_map_grids, get_map_drivers, get_map_weather
    from routers.misc import gps_health, scheduler_insights
    from routers.garages import list_garages
    from routers.pta import pta_advisor

    return [
        # (interval, cache_key, endpoint_fn, persist_to_disk)
        # Note: async endpoints (onroute_list) are excluded — can't call from sync thread.
        # They use cached_query() with short TTLs and handle themselves fine.

        # ── Real-time (30s) ──
        (30,   'queue_live',               get_live_queue,                  False),

        # ── Live dashboards (60s) ──
        (60,   'ops_brief',               ops_brief,                        False),
        (60,   'scheduler_insights_today', scheduler_insights,              False),

        # ── Operational views (120s) ──
        (120,  'command_center_24',       lambda: command_center(hours=24), False),
        (120,  'command_center_4',        lambda: command_center(hours=4),  False),
        (120,  'ops_territories',         get_ops_territories,              False),
        (120,  'map_drivers',             get_map_drivers,                  False),

        # ── Reference data (600s) ──
        (600,  'garages_list',            list_garages,                     True),
        (600,  'ops_garages',             get_ops_garages,                  True),
        (600,  'priority_matrix',         _get_priority_matrix,             True),

        # ── Slow-changing (900s+) ──
        (900,  'map_weather',             get_map_weather,                  True),
        (900,  'pta_advisor',             pta_advisor,                      True),

        # ── Heavy / static (3600s) ──
        (3600, 'map_grids',              get_map_grids,                    True),
        (300,  'gps_health',             gps_health,                       False),  # 5 min — drivers log in/out
    ]


# ── Leader election ──────────────────────────────────────────────────────────

def _try_become_leader() -> bool:
    """Try to become the refresher leader. Returns True if this process is leader."""
    try:
        if _LOCK_FILE.exists():
            age = time.time() - _LOCK_FILE.stat().st_mtime
            if age < _LEADER_STALE_AGE:
                # Check if it's our own lock (we're already leader)
                try:
                    lock_data = _LOCK_FILE.read_text()
                    if str(os.getpid()) in lock_data:
                        return True
                except Exception:
                    pass
                return False  # Another process is leader
            # Stale lock — take over
            log.info(f"Refresher leader lock stale ({age:.0f}s) — taking over")

        _LOCK_FILE.write_text(f'{os.getpid()}:{time.time()}')
        return True
    except Exception as e:
        log.warning(f"Leader election error: {e}")
        return False


def _renew_leadership():
    """Update lock file timestamp to signal we're still alive."""
    try:
        _LOCK_FILE.write_text(f'{os.getpid()}:{time.time()}')
    except Exception:
        pass


# ── Refresh logic ────────────────────────────────────────────────────────────

def _refresh_one(key: str, endpoint_fn, interval: int, persist: bool) -> bool:
    """Force-refresh a cache key on the refresher's schedule.

    Strategy: EXPIRE the L1 entry (don't delete it). The stale data stays
    in _store so any concurrent user request gets stale data instantly —
    NO blank screen, NO blink.

    Then call the endpoint function. Its internal cached_query() sees the
    expired entry, one thread (us) re-fetches from SF, and the cache is
    atomically updated with fresh data. Other users see stale → fresh
    with zero interruption.
    """
    try:
        # Mark L1 as expired — stale data stays available for other readers
        with cache._lock:
            entry = cache._store.get(key)
            if entry:
                entry['expires'] = 0
        # Call the endpoint — cached_query sees expired, re-fetches from SF
        # Other concurrent requests get stale data instantly (no blink)
        result = endpoint_fn()
        # Persist to L2 disk for cross-worker sharing
        if persist and result is not None:
            cache.disk_put(key, result, interval)
        return True
    except Exception as e:
        log.warning(f"Refresh failed for '{key}': {e}")
        return False


# ── Refresh loop ─────────────────────────────────────────────────────────────

def _refresh_loop():
    """Main refresh loop. Runs forever in a daemon thread."""
    # Wait for app to fully start
    time.sleep(8)

    try:
        schedule = _get_schedule()
    except Exception as e:
        log.error(f"Failed to build refresh schedule: {e}")
        return

    log.info(f"Refresher ready: {len(schedule)} keys to keep warm. PID={os.getpid()}")

    # Track last refresh time for each key
    last_refreshed = {entry[1]: 0.0 for entry in schedule}
    cycle = 0

    while True:
        try:
            # Leader election: check every cycle
            if not _try_become_leader():
                time.sleep(10)
                continue

            now = time.time()
            refreshed = []

            for interval, key, fn, persist in schedule:
                elapsed = now - last_refreshed[key]
                # Refresh on schedule — always force-fetch fresh data from SF
                if elapsed >= interval:
                    if _refresh_one(key, fn, interval, persist):
                        refreshed.append(key)
                    last_refreshed[key] = time.time()
                    # Small sleep between SF calls to avoid bursts
                    time.sleep(0.5)

            _renew_leadership()

            if cycle % 30 == 0:
                log.info(f"Refresher cycle {cycle}: {len(refreshed)} keys refreshed")
                cache.cleanup_expired()  # Purge stale L1 entries to prevent memory growth

            cycle += 1
            time.sleep(10)  # Check every 10 seconds for fine-grained scheduling

        except Exception as e:
            log.error(f"Refresher loop error: {e}")
            time.sleep(30)


# ── Public API ───────────────────────────────────────────────────────────────

_started = False


def start():
    """Start the refresher in a background daemon thread.

    Safe to call from multiple workers — only one becomes leader.
    Called from main.py on startup.
    """
    global _started
    if _started:
        return
    _started = True

    thread = threading.Thread(target=_refresh_loop, daemon=True, name='cache-refresher')
    thread.start()
    log.info(f"Refresher thread launched (PID={os.getpid()})")
