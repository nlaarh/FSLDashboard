"""Centralized feature permissions — single source of truth.
Future: move FEATURE_ROLES to DB so admin can assign dynamically.
"""

FEATURE_ROLES = {
    "garage.revenue_performance": {"superadmin", "admin", "executive", "ers-director"},
    "reporting.user_adoption":    {"superadmin", "admin", "executive"},
    "admin.panel":                {"superadmin", "admin"},
    "admin.impersonate":          {"superadmin"},
}


def get_user_features(role: str) -> list[str]:
    return [f for f, roles in FEATURE_ROLES.items() if role in roles]


def can_access(role: str, feature: str) -> bool:
    return role in FEATURE_ROLES.get(feature, set())


def require_feature(feature: str, request) -> None:
    """Raise 401/403 if request user lacks the feature. No-op if request is None (direct Python call)."""
    if request is None:
        return
    from fastapi import HTTPException
    from routers.auth import _verify_cookie
    import users as _users
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = payload.split(":")[0]
    role = (_users.get_user(username) or {}).get("role") or ""
    if not can_access(role, feature):
        raise HTTPException(status_code=403, detail="Access restricted")
