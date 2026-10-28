"""Sign in with Microsoft (Entra ID, AAA tenant only).

Standard OpenID Connect code flow: /api/auth/sso/login sends the browser to Microsoft,
Microsoft sends it back to /api/auth/sso/callback with a one-time code, we swap the code
for the user's ID token and sign them in as the FleetPulse user with the same email.
No FleetPulse account with that email → no access (we never create users here).

Settings (Azure app settings / .env):
  SSO_TenantId  — AAA's Microsoft tenant ID
  SSO_UserName  — the FleetPulse app registration's Application (client) ID
  SSO_API       — that app registration's client secret value
  SSO_REDIRECT_URI (optional) — override the callback URL; default is https://<host>/api/auth/sso/callback
"""

import base64
import json
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import users
from routers.auth import _sign_cookie, _verify_cookie

router = APIRouter()
log = logging.getLogger('auth_sso')

_STATE_COOKIE = "fslapp_sso"
_STATE_TTL = 600  # seconds the user has to finish the Microsoft sign-in


def _config() -> tuple[str, str, str] | None:
    tenant = os.environ.get("SSO_TenantId", "").strip()
    client_id = os.environ.get("SSO_UserName", "").strip()
    secret = os.environ.get("SSO_API", "").strip()
    return (tenant, client_id, secret) if tenant and client_id and secret else None


def sso_enabled() -> bool:
    return _config() is not None


def _redirect_uri(request: Request) -> str:
    override = os.environ.get("SSO_REDIRECT_URI", "").strip()
    if override:
        return override
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    scheme = "http" if host.startswith(("localhost", "127.0.0.1")) else "https"
    return f"{scheme}://{host}/api/auth/sso/callback"


def _fail(reason: str) -> RedirectResponse:
    resp = RedirectResponse(f"/login?sso_error={reason}", status_code=302)
    resp.delete_cookie(_STATE_COOKIE)
    return resp


def _decode_claims(id_token: str) -> dict:
    """Read the ID token's claims. It comes straight from Microsoft's token endpoint over
    HTTPS in exchange for our client secret, so the signature check is optional
    (OpenID Connect Core 3.1.3.7); we still check audience, tenant, expiry and nonce."""
    body = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


@router.get("/api/auth/sso/login")
def sso_login(request: Request):
    cfg = _config()
    if not cfg:
        return _fail("not_configured")
    tenant, client_id, _ = cfg
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": _redirect_uri(request),
        "response_mode": "query",
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
    }
    resp = RedirectResponse(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}", status_code=302)
    secure = _redirect_uri(request).startswith("https")
    resp.set_cookie(_STATE_COOKIE, _sign_cookie(f"{state}:{nonce}:{int(time.time())}"),
                    httponly=True, secure=secure, samesite="lax", max_age=_STATE_TTL)
    return resp


@router.get("/api/auth/sso/callback")
def sso_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    cfg = _config()
    if not cfg:
        return _fail("not_configured")
    if error:
        log.info(f"[sso] Microsoft returned error: {error}")
        return _fail("cancelled")
    tenant, client_id, secret = cfg

    saved = _verify_cookie(request.cookies.get(_STATE_COOKIE, ""))
    parts = saved.split(":") if saved else []
    if len(parts) != 3 or not code or not secrets.compare_digest(parts[0], state) \
            or time.time() - int(parts[2]) > _STATE_TTL:
        return _fail("expired")
    nonce = parts[1]

    try:
        r = requests.post(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", data={
            "client_id": client_id, "client_secret": secret, "grant_type": "authorization_code",
            "code": code, "redirect_uri": _redirect_uri(request), "scope": "openid profile email",
        }, timeout=15)
        tokens = r.json()
        claims = _decode_claims(tokens["id_token"])
    except Exception as e:
        log.warning(f"[sso] token exchange failed: {e}")
        return _fail("microsoft")

    if claims.get("aud") != client_id or claims.get("tid") != tenant \
            or claims.get("nonce") != nonce or claims.get("exp", 0) < time.time():
        log.warning("[sso] ID token failed checks (aud/tid/nonce/exp)")
        return _fail("microsoft")

    # Work email first, then the Microsoft login name (they can differ for some staff).
    emails = [e.strip() for e in (claims.get("email"), claims.get("preferred_username")) if e and "@" in e]
    user = next((u for u in map(users.find_by_email, emails) if u), None)
    email = emails[0] if emails else ""
    if not user:
        log.info(f"[sso] no active FleetPulse user for {email!r}")
        return _fail("no_account")

    dept = user.get("department", "") or ""
    token = users.create_session(user["username"], user["role"], user["name"], dept)
    resp = RedirectResponse("/", status_code=302)
    secure = _redirect_uri(request).startswith("https")
    resp.set_cookie("fslapp_auth", _sign_cookie(f"{user['username']}:{user['role']}:{token}"),
                    httponly=True, secure=secure, samesite="lax", max_age=86400)
    resp.delete_cookie(_STATE_COOKIE)
    log.info(f"[sso] {user['username']} signed in with Microsoft")
    return resp
