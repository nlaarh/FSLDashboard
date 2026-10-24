"""Access matrix API: which roles may use which feature, and which roles each user holds.

Only a superadmin (primary role, read fresh from the database) may call these. Stored under
/api/admin/access/ so the admin middleware applies as well.
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request

import access_store
import users
from permissions import (EXCLUSIVE_ROLES, FEATURE_META, FEATURE_ROLES, HARD_DENY, LOCKED_FEATURES, ROLES,
                         feature_roles, get_user_features)
from repositories import access as repo
from repositories import activity
from repositories import users as user_repo
from routers.auth import get_request_username

router = APIRouter()
log = logging.getLogger("admin_access")

_TABLES_MISSING = "Access tables are not installed yet (run migrations/roles_matrix.py --apply)."


def _require_superadmin(request: Request) -> str:
    username = get_request_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = user_repo.get_user(username)  # fresh read, not the 60 s cache
    if not user or user.get("role") != "superadmin" or not user.get("active"):
        raise HTTPException(status_code=403, detail="Only a superadmin can change access")
    return username


def _bad(detail: str):
    raise HTTPException(status_code=400, detail=detail)


def _matrix() -> dict:
    features = []
    for key, default in FEATURE_ROLES.items():
        label, description, group = FEATURE_META[key]
        roles, source = (set(default), "default") if key in LOCKED_FEATURES else access_store.feature_roles(key, default)
        features.append({"key": key, "group": group, "label": label, "description": description,
                         "locked": key in LOCKED_FEATURES, "lock_reason": LOCKED_FEATURES.get(key, ""),
                         "warning": "Contractors are always refused here." if key in HARD_DENY else "",
                         "roles": sorted(roles), "default_roles": sorted(default),
                         "source": source})
    return {"roles": list(ROLES), "exclusive_roles": sorted(EXCLUSIVE_ROLES), "features": features,
            "fallback": access_store.is_fallback()}


def _effective(username: str) -> dict:
    roles = (users.get_user(username) or {}).get("roles", [])
    return {"roles": roles, "features": get_user_features(roles)}


@router.get("/api/admin/access/matrix")
def get_matrix(request: Request):
    _require_superadmin(request)
    return _matrix()


@router.put("/api/admin/access/features")
def put_features(request: Request, body: dict):
    actor = _require_superadmin(request)
    changes = body.get("changes")
    if not isinstance(changes, dict) or not changes:
        _bad("changes must be a non-empty object")
    before = {k: sorted(feature_roles(k)) for k in changes if k in FEATURE_ROLES}
    cleaned = {}
    for key, roles in changes.items():
        if key not in FEATURE_ROLES:
            _bad(f"Unknown feature: {key}")
        if key in LOCKED_FEATURES:
            _bad(f"{key} is locked in code and cannot be changed")
        if roles is None:
            cleaned[key] = None
            continue
        if not isinstance(roles, list) or any(r not in ROLES for r in roles):
            _bad(f"roles for {key} must be a list of known roles")
        if set(roles) & HARD_DENY.get(key, set()):
            _bad(f"{', '.join(sorted(set(roles) & HARD_DENY[key]))} can never have {key}")
        if "superadmin" not in roles:
            _bad(f"superadmin must keep {key}")
        cleaned[key] = sorted(set(roles))
    try:
        repo.save_features(cleaned, actor)
    except Exception:
        log.exception("save_features failed")
        raise HTTPException(status_code=503, detail=_TABLES_MISSING)
    access_store.invalidate()
    for key, roles in cleaned.items():
        after = sorted(FEATURE_ROLES[key]) if roles is None else roles
        activity.log_activity(user=actor, action="access_feature_change", method="PUT", detail=json.dumps(
            {"feature": key, "before": before[key], "after": after, "reset": roles is None}))
    return _matrix()


@router.get("/api/admin/access/users")
def list_users(request: Request, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
               q: str = "", role: str = ""):
    _require_superadmin(request)
    try:
        total, rows = repo.list_users_page(page, page_size, q.strip(), role)
    except Exception:
        log.exception("list_users_page failed")
        raise HTTPException(status_code=503, detail=_TABLES_MISSING)
    return {"total": total, "page": page, "page_size": page_size,
            "users": [{"username": r["username"], "name": r["name"], "active": r["active"],
                       "department": r["department"], "primary": r["role"], "extra": r["extra"]} for r in rows]}


@router.put("/api/admin/access/users")
def put_users(request: Request, body: dict):
    actor = _require_superadmin(request)
    changes = body.get("changes")
    if not isinstance(changes, list) or not changes:
        _bad("changes must be a non-empty list")
    plan = []
    for c in changes:
        username = c.get("username") if isinstance(c, dict) else None
        current = user_repo.get_user(username) if username else None
        if not current:
            _bad(f"Unknown user: {username}")
        primary = c.get("primary") or current["role"]
        extra = c.get("extra", [])
        if not isinstance(extra, list):
            _bad("extra must be a list of roles")
        unknown = [r for r in [primary, *extra] if r not in ROLES]
        if unknown:
            _bad(f"Unknown role: {', '.join(unknown)}")
        extra = set(extra) - {primary}
        # Restricted roles are never swapped in or out here: a bulk tick must not turn a contractor into a manager.
        # Changing a restricted user's primary role is done on purpose in Users & Sessions (admin.py update user).
        if primary != current["role"] and EXCLUSIVE_ROLES & {primary, current["role"]}:
            _bad(f"{username}: the restricted role {', '.join(sorted(EXCLUSIVE_ROLES & {primary, current['role']}))} "
                 "cannot be added or removed here. Change it in Users & Sessions.")
        if (EXCLUSIVE_ROLES & ({primary} | extra)) and extra:
            _bad(f"{username}: {', '.join(sorted(EXCLUSIVE_ROLES & ({primary} | extra)))} cannot be combined with another role")
        plan.append((username, current["role"], primary, extra))
    demoted = {u for u, old, new, _ in plan if old == "superadmin" and new != "superadmin"}
    if demoted and repo.count_active_superadmins(demoted) == 0:
        _bad("Cannot remove the last superadmin")
    try:
        # Primary and extra roles of every changed user, in one transaction: all or nothing.
        repo.save_user_roles([(username, new, extra) for username, _, new, extra in plan], actor)
    except Exception:
        log.exception("set_extra_roles failed")
        raise HTTPException(status_code=503, detail=_TABLES_MISSING)
    result = {}
    for username, old, new, extra in plan:
        users.invalidate_user_roles(username, primary_changed=new != old)
        activity.log_activity(user=actor, action="access_user_change", method="PUT", detail=json.dumps(
            {"username": username, "primary": [old, new], "extra": sorted(extra)}))
        result[username] = _effective(username)
    return {"changed": result}


@router.get("/api/admin/access/users/{username}/effective")
def get_effective(request: Request, username: str):
    _require_superadmin(request)
    if not user_repo.get_user(username):
        raise HTTPException(status_code=404, detail="User not found")
    return _effective(username)
