"""Embed router — sign-in for FleetPulse pages shown inside Salesforce (Canvas).

Salesforce POSTs a Canvas "signed request" to /embed/canvas:
    base64(HMAC-SHA256(consumer_secret, payload_b64)) + "." + payload_b64
where payload_b64 is the base64 CanvasRequest JSON (context.user.email, etc.).

We verify the signature with the Connected App's consumer secret, match the
Salesforce user's email to an existing active FleetPulse user, and create the
same session the password login creates. Password login is unchanged.

The session cookie is set SameSite=None; Secure; Partitioned so the browser
sends it inside the Salesforce iframe (a Lax cookie is never sent cross-site).
Starlette 0.41 (what requirements.txt resolves to) has no `partitioned`
argument, so the header is built by hand.
"""

import base64
import hashlib
import hmac
import html
import json
import logging
import os
from http.cookies import SimpleCookie

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import users
from routers.auth import _sign_cookie

router = APIRouter()
log = logging.getLogger('embed')

COOKIE_NAME = "fslapp_auth"
COOKIE_MAX_AGE = 86400
DEFAULT_EMBED_PATH = "/sa-watchlist"


def embed_cookie_header(value: str, max_age: int = COOKIE_MAX_AGE) -> str:
    """Set-Cookie value for the iframe session (partitioned, cross-site)."""
    c = SimpleCookie()
    c[COOKIE_NAME] = value
    m = c[COOKIE_NAME]
    m["path"] = "/"
    m["max-age"] = max_age
    m["httponly"] = True
    m["secure"] = True
    m["samesite"] = "None"
    return m.OutputString() + "; Partitioned"


def verify_signed_request(signed_request: str, secret: str) -> dict | None:
    """Return the decoded CanvasRequest if the signature is valid, else None."""
    if not signed_request or not secret or "." not in signed_request:
        return None
    sig_b64, payload_b64 = signed_request.split(".", 1)
    expected = base64.b64encode(
        hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    ).decode()
    if not hmac.compare_digest(sig_b64, expected):
        return None
    try:
        data = json.loads(base64.b64decode(payload_b64))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("algorithm") != "HMACSHA256":
        return None
    return data


def _safe_path(path) -> str:
    """Only allow same-site relative paths (no //host or scheme redirects)."""
    if isinstance(path, str) and path.startswith("/") and not path.startswith("//") and "\\" not in path:
        return path
    return DEFAULT_EMBED_PATH


def _message_page(title: str, body: str, status: int) -> HTMLResponse:
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>FleetPulse</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0f172a;color:#e2e8f0;font:15px/1.5 system-ui,-apple-system,sans-serif}}
div{{max-width:440px;padding:24px}}h1{{font-size:18px;margin:0 0 8px}}p{{color:#94a3b8;margin:0}}</style>
</head><body><div><h1>{html.escape(title)}</h1><p>{html.escape(body)}</p></div></body></html>"""
    return HTMLResponse(page, status_code=status)


@router.get("/embed/canvas")
def canvas_get():
    """Reached directly, after a session expires inside the iframe, or when the
    Connected App is set to self-authorize (Salesforce then sends a GET)."""
    return _message_page(
        "Open FleetPulse from Salesforce",
        "Your FleetPulse session inside Salesforce has ended or was not started. "
        "Refresh the Salesforce page to sign in again.",
        401,
    )


@router.post("/embed/canvas")
async def canvas_post(request: Request):
    secret = os.environ.get("SF_CANVAS_SECRET", "")
    if not secret:
        log.error("SF_CANVAS_SECRET is not set — Salesforce embed sign-in disabled")
        return _message_page("Salesforce sign-in is not configured",
                             "Ask a FleetPulse admin to finish the Salesforce setup.", 503)

    form = await request.form()
    data = verify_signed_request(str(form.get("signed_request", "")), secret)
    if not data:
        log.warning("Canvas sign-in rejected: bad signature")
        return _message_page("Sign-in failed", "Salesforce's sign-in could not be verified.", 401)

    context = data.get("context") or {}
    org_id = ((context.get("organization") or {}).get("organizationId") or "")
    expected_org = os.environ.get("SF_CANVAS_ORG_ID", "")
    if expected_org and org_id[:15] != expected_org[:15]:
        log.warning("Canvas sign-in rejected: org %s", org_id)
        return _message_page("Sign-in failed", "This Salesforce org is not allowed.", 403)

    sf_user = context.get("user") or {}
    email = (sf_user.get("email") or "").strip()
    # Sandbox copies append ".invalid" to every user's email (jdoe@nyaaa.com.invalid).
    # SF_CANVAS_ORG_ID locked to production rejects sandbox requests before this point.
    if email.lower().endswith(".invalid"):
        email = email[: -len(".invalid")]
    user = users.find_by_email(email) if email else None
    if not user:
        log.warning("Canvas sign-in: no active FleetPulse user for %s (SF %s)", email, sf_user.get("userId"))
        return _message_page(
            "No FleetPulse access",
            f"There is no active FleetPulse account for {email or 'your Salesforce user'}. "
            "Ask a FleetPulse admin to add you.",
            403,
        )

    dept = user.get("department", "") or ""
    token = users.create_session(user["username"], user["role"], user["name"], dept)
    cookie_value = _sign_cookie(f"{user['username']}:{user['role']}:{token}")

    params = (context.get("environment") or {}).get("parameters") or {}
    target = _safe_path(params.get("path") if isinstance(params, dict) else None)
    target += ("&" if "?" in target else "?") + "embed=1"

    log.info("Canvas sign-in: %s (SF %s) -> %s", user["username"], sf_user.get("userId"), target)
    response = RedirectResponse(target, status_code=303)
    response.headers.append("set-cookie", embed_cookie_header(cookie_value))
    return response
