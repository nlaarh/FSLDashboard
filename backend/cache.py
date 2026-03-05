"""Simple TTL cache for Salesforce query results."""

import time
from threading import Lock

_store = {}
_lock = Lock()
DEFAULT_TTL = 300  # 5 minutes


def get(key: str):
    with _lock:
        entry = _store.get(key)
        if entry and time.time() < entry['expires']:
            return entry['data']
        if entry:
            del _store[key]
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
    """Run query_fn only if result not cached."""
    result = get(key)
    if result is not None:
        return result
    result = query_fn()
    put(key, result, ttl)
    return result
