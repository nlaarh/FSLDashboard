"""Auth router — login page, login/logout/me endpoints.

HTML page templates and their route handlers live in auth_pages.py (keeps this file
under the 600-line ceiling).
"""

import logging
import os, hashlib, hmac, secrets, time, threading
from fastapi import APIRouter, HTTPException, Request, Response
import users
from permissions import get_user_features
from sf_client import sf_query_all

# Page routes are registered on this router via auth_pages.router; main.py must
# include both routers.  We do NOT re-export the page router here to avoid
# circular imports — main.py imports routers.auth_pages separately.

router = APIRouter()
log = logging.getLogger('auth')

# ── Login rate limiter ────────────────────────────────────────────────────────
_rate_lock = threading.Lock()
_rate_attempts: dict[str, list[float]] = {}  # ip -> [timestamps]
_RATE_WINDOW = 60    # seconds
_RATE_MAX    = 15    # max attempts per window per IP


def _rate_check(ip: str) -> bool:
    """Return True if the IP is within the allowed rate. False = block."""
    now = time.time()
    with _rate_lock:
        ts = _rate_attempts.get(ip, [])
        ts = [t for t in ts if now - t < _RATE_WINDOW]
        if len(ts) >= _RATE_MAX:
            _rate_attempts[ip] = ts
            return False
        ts.append(now)
        _rate_attempts[ip] = ts
        return True


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get('x-forwarded-for', '')
    return forwarded.split(',')[0].strip() or request.client.host


# ── Auth helpers ──────────────────────────────────────────────────────────────
_AUTH_SECRET = os.environ.get("AUTH_SECRET", secrets.token_hex(32))
_DEV_AUTO_LOGIN = os.environ.get("DEV_AUTO_LOGIN", "false").lower() == "true"

_PUBLIC_PATHS = {"/login", "/forgot-password", "/reset-password", "/api/auth/login", "/api/auth/forgot-password", "/api/auth/verify-reset-pin", "/api/auth/reset-password", "/api/health", "/api/features", "/favicon.ico"}

# Paths finance-department users may call (everything else → 403)
_FINANCE_ALLOWED = ('/api/auth/', '/api/accounting/', '/api/health', '/api/features')


def _finance_ok(path: str) -> bool:
    return any(path.startswith(p) for p in _FINANCE_ALLOWED)


def _get_department(username: str) -> str:
    """Return the user's department string, '' if not set or not found."""
    u = users.get_user(username)
    return (u or {}).get('department', '') or ''


def _get_role(username: str) -> str:
    """Return the user's role string, '' if not set or not found."""
    u = users.get_user(username)
    return (u or {}).get('role', '') or ''


# Paths that ers-supervisor role is blocked from
_SUPERVISOR_BLOCKED = ('/api/accounting/', '/api/admin/')

# Roles allowed to access the full admin panel
_ADMIN_ROLES = ('superadmin', 'admin')

# Roles allowed read/write access to reference data only (no PIN required)
_REFERENCE_ROLES = ('executive', 'ers-director')


def _supervisor_blocked(path: str) -> bool:
    return any(path.startswith(p) for p in _SUPERVISOR_BLOCKED)


def _admin_allowed(role: str) -> bool:
    return role in _ADMIN_ROLES


def _reference_allowed(role: str, path: str) -> bool:
    return role in _REFERENCE_ROLES and path.startswith('/api/admin/reference/')


def _sign_cookie(payload: str) -> str:
    sig = hmac.new(_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_cookie(cookie: str) -> str | None:
    if not cookie or "." not in cookie:
        return None
    payload, sig = cookie.rsplit(".", 1)
    expected = hmac.new(_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return payload
    return None


def get_request_username(request: Request) -> str | None:
    """Extract the username from the fslapp_auth cookie. Returns None if not authenticated."""
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        return payload.split(":")[0]
    return None


# ── Garage-names cache (contractor territory lookup) ─────────────────────────
# Keyed by frozenset of territory IDs to avoid redundant SF calls.
_garage_names_cache: dict[frozenset, list[dict]] = {}


def _get_garage_names(territory_ids: list[str]) -> list[dict]:
    """Return [{id, name}, ...] for the given territory IDs.

    Only called for contractor users who have territories. Results are cached
    in-memory per unique territory set for the lifetime of the process.
    """
    if not territory_ids:
        return []
    key = frozenset(territory_ids)
    if key in _garage_names_cache:
        return _garage_names_cache[key]
    ids_str = ', '.join(f"'{t}'" for t in territory_ids)
    try:
        rows = sf_query_all(
            f"SELECT Id, Name FROM ServiceTerritory WHERE Id IN ({ids_str})"
        )
        result = [{'id': r['Id'], 'name': r['Name']} for r in (rows or [])]
    except Exception:
        log.exception("Failed to fetch garage names for territories %s", territory_ids)
        result = []
    _garage_names_cache[key] = result
    return result


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.post("/api/auth/login")
def admin_login(request: Request, creds: dict, response: Response):
    if not _rate_check(_get_ip(request)):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a minute.")
    user = users.authenticate(creds.get("username", ""), creds.get("password", ""))
    if user:
        dept = user.get("department", "")
        token = users.create_session(user["username"], user["role"], user["name"], dept)
        payload = f"{user['username']}:{user['role']}:{token}"
        response.set_cookie("fslapp_auth", _sign_cookie(payload), httponly=True, samesite="lax", max_age=86400)
        return {"ok": True, "user": user["username"], "name": user["name"], "role": user["role"], "department": dept}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/api/auth/me")
def auth_me(request: Request):
    # Azure Easy Auth
    principal = request.headers.get("x-ms-client-principal-name")
    if principal:
        return {"user": principal, "method": "sso", "role": "admin", "name": principal,
                "features": get_user_features("admin"), "garage_names": []}
    # Admin cookie
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        parts = payload.split(":")
        username = parts[0]
        role = parts[1] if len(parts) > 1 else "admin"
        name = username
        email = ""
        department = ""
        # Try to get session info for richer data
        if len(parts) > 2:
            sess = users.get_session(parts[2])
            if sess:
                name = sess.get("name", username)
                role = sess.get("role", role)
                department = sess.get("department", "")
        # Get email + department + territories from user record (authoritative; also handles old sessions without dept)
        user_record = users.get_user(username)
        territories: list = []
        if user_record:
            email = user_record.get("email", "")
            if not department:
                department = user_record.get("department", "")
            territories = user_record.get("territories") or []
        # Resolve territory IDs to names — only for contractor users
        garage_names = _get_garage_names(territories) if role == "contractor" and territories else []
        return {
            "user": username, "name": name, "role": role,
            "email": email, "department": department,
            "territories": territories,
            "garage_names": garage_names,
            "method": "admin",
            "features": get_user_features(role),
        }
    if _DEV_AUTO_LOGIN:
        return {"user": "dev", "name": "Developer", "role": "admin", "email": "",
                "department": "", "method": "local", "features": get_user_features("admin"),
                "garage_names": []}
    raise HTTPException(status_code=401, detail="Not authenticated")


@router.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        parts = payload.split(":")
        if len(parts) > 2:
            users.destroy_session(parts[2])
    response.delete_cookie("fslapp_auth")
    return {"ok": True}
