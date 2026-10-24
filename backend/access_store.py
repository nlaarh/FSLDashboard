"""Reads the editable access settings (feature roles, extra user roles) with a short cache.

Never raises: a missing table, a broken connection or an unknown role value means "use the code
defaults" (no row for a feature, no extra roles), so nobody is locked out. Failures are re-tried after 5 s.
"""

import json
import logging
import threading
import time

from repositories import access as repo

log = logging.getLogger("access_store")

_TTL_OK = 30
_TTL_FAILED = 5

_lock = threading.Lock()
_state: dict = {"features": {}, "extras": {}, "ok": True, "expires": 0.0}


def invalidate() -> None:
    with _lock:
        _state["expires"] = 0.0


def _load() -> dict:
    from permissions import ROLES
    features, extras = {}, {}
    for row in repo.read_feature_rows():
        roles = json.loads(row["roles"])
        if not isinstance(roles, list) or any(r not in ROLES for r in roles):
            log.warning("access_store: feature %s has an invalid role list; using the code default", row["feature"])
            continue
        features[row["feature"]] = set(roles)
    for row in repo.read_extra_rows():
        if row["role"] in ROLES:
            extras.setdefault(row["username"], set()).add(row["role"])
        else:
            log.warning("access_store: ignoring unknown extra role %r for %s", row["role"], row["username"])
    return {"features": features, "extras": extras}


def _snapshot() -> dict:
    with _lock:
        if time.monotonic() < _state["expires"]:
            return _state
        was_ok = _state["ok"]
        try:
            _state.update(_load(), ok=True, expires=time.monotonic() + _TTL_OK)
        except Exception as e:
            if was_ok:
                log.warning("access_store: tables unreadable (%s); using code defaults", e)
            _state.update(features={}, extras={}, ok=False, expires=time.monotonic() + _TTL_FAILED)
        return _state


def feature_roles(feature: str, default: set) -> tuple[set, str]:
    """(roles, 'db' | 'default') for one feature."""
    stored = _snapshot()["features"].get(feature)
    return (set(stored), "db") if stored is not None else (set(default), "default")


def extra_roles(username: str) -> set:
    return set(_snapshot()["extras"].get(username, ()))


def is_fallback() -> bool:
    return not _snapshot()["ok"]
