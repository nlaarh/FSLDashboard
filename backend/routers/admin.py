"""Admin router — PIN-protected admin panel, cache flush, user management, settings."""

import os, json as _json
from fastapi import APIRouter, HTTPException, Query, Request, Response
import users
import cache
from password_policy import password_policy_error
from sf_client import get_stats as sf_stats, sf_query
from repositories import settings, activity, accounting
from email_templates import welcome_email_url, password_changed_email_url
import time

router = APIRouter()

# ── Admin PIN ────────────────────────────────────────────────────────────────
_ADMIN_PIN = os.getenv('ADMIN_PIN')  # required — no default in source


def _check_pin(request: Request):
    if not _ADMIN_PIN:
        raise HTTPException(status_code=503, detail="ADMIN_PIN not configured on server")
    pin = request.headers.get('X-Admin-Pin', '')
    if pin != _ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Invalid PIN")


# ── Settings persistence ─────────────────────────────────────────────────────

# Shared with routers/misc.py — the save loop below iterates these keys, so a
# flag missing here is silently dropped when an admin saves. Keep one copy.
from feature_flags import DEFAULT_FEATURES as _DEFAULT_FEATURES


def _load_settings():
    try:
        return settings.get_all_settings()
    except Exception:
        return {}

def _save_settings(data: dict):
    for key, value in data.items():
        settings.put_setting(key, value)


# ── Startup time (imported from main at wire-up, but we need our own for status) ──
_start_time = time.time()


# ── Admin Panel API ──────────────────────────────────────────────────────────

@router.post("/api/admin/verify")
def admin_verify(request: Request):
    """Verify admin PIN."""
    _check_pin(request)
    return {"ok": True}


@router.get("/api/admin/status")
def admin_status(request: Request):
    """Full system status: cache + SF health + uptime."""
    _check_pin(request)
    return {
        "cache": cache.stats(),
        "salesforce": sf_stats(),
        "uptime_seconds": round(time.time() - _start_time),
    }


@router.post("/api/admin/flush")
def admin_flush(request: Request, prefix: str = Query('', description="Cache key prefix to flush, empty = all")):
    """Flush cache entries. Empty prefix = flush everything."""
    _check_pin(request)
    cache.invalidate(prefix)
    return {"flushed": prefix or "ALL", "cache_after": cache.stats()}


@router.post("/api/admin/flush/live")
def admin_flush_live(request: Request):
    """Flush only live/operational caches (command center, queue, drivers)."""
    _check_pin(request)
    for p in ['command_center', 'queue_live', 'map_drivers', 'sa_lookup', 'simulate', 'pta_advisor']:
        cache.invalidate(p)
    return {"flushed": "live_caches", "cache_after": cache.stats()}


@router.post("/api/admin/flush/historical")
def admin_flush_historical(request: Request):
    """Flush historical caches (scorecard, performance, decomposition, forecast)."""
    _check_pin(request)
    for p in ['scorecard', 'perf_', 'scorer_', 'decomp_', 'forecast_']:
        cache.invalidate(p)
    return {"flushed": "historical_caches", "cache_after": cache.stats()}


@router.post("/api/admin/flush/static")
def admin_flush_static(request: Request):
    """Flush static reference caches (garages, grids, skills, weather)."""
    _check_pin(request)
    for p in ['garages_list', 'map_grids', 'map_weather', 'skills_', 'ops_garages', 'ops_territories']:
        cache.invalidate(p)
    return {"flushed": "static_caches", "cache_after": cache.stats()}


# ── User Management (PIN-protected) ──────────────────────────────────────────

@router.get("/api/admin/users")
def admin_list_users(request: Request):
    """List all users."""
    _check_pin(request)
    return users.list_users()


@router.post("/api/admin/users")
def admin_create_user(request: Request, body: dict):
    """Create a new user."""
    _check_pin(request)
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")
    name = body.get("name", "").strip()
    role = body.get("role", "viewer")
    if not username or not password or not name:
        raise HTTPException(status_code=400, detail="username, password, and name are required")
    password_error = password_policy_error(password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)
    email = body.get("email", "").strip()
    phone = body.get("phone", "").strip()
    valid_roles = ("superadmin", "admin", "manager", "officer", "supervisor", "viewer", "finance", "ers", "executive", "ers-manager", "ers-supervisor", "ers-director", "ers-member-relations", "contractor")
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"role must be one of: {', '.join(valid_roles)}")
    department = body.get("department", "").strip().lower()
    valid_depts = ("", "ers", "finance", "executive")
    if department not in valid_depts:
        raise HTTPException(status_code=400, detail=f"department must be one of: ers, finance, executive (or empty)")
    raw_garages = body.get("garages", [])
    if not isinstance(raw_garages, list):
        raw_garages = []
    garages = [g for g in raw_garages if isinstance(g, dict) and "id" in g and "name" in g]
    try:
        result = users.create_user(username, password, name, role, email=email, phone=phone, department=department, garages=garages)
        email = welcome_email_url(
            username=username,
            name=name,
            email=email or "",
            password=password,
            role=role,
            department=department,
        )
        result["welcome_email_url"] = email["url"]
        result["email_subject"] = email["subject"]
        result["email_body"] = email["body"]
        result["email_to"] = email["to"]
        return result
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/api/admin/users/{username}")
def admin_update_user(request: Request, username: str, body: dict):
    """Update a user."""
    _check_pin(request)
    password = body.get("password") or None
    if password:
        password_error = password_policy_error(password)
        if password_error:
            raise HTTPException(status_code=400, detail=password_error)
    garages = body.get("garages")  # None means "don't change"; [] means "clear all"; list means "replace"
    if garages is not None and not isinstance(garages, list):
        garages = None
    try:
        result = users.update_user(
            username,
            name=body.get("name"),
            role=body.get("role"),
            department=body.get("department"),
            password=password,
            active=body.get("active"),
            email=body.get("email"),
            phone=body.get("phone"),
            garages=garages,
        )
        if password:
            email = password_changed_email_url(
                username=username,
                name=result.get("name", username),
                email=result.get("email", ""),
                password=password,
            )
            result["password_changed_email_url"] = email["url"]
            result["email_subject"] = email["subject"]
            result["email_body"] = email["body"]
            result["email_to"] = email["to"]
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/api/admin/users/{username}")
def admin_delete_user(request: Request, username: str):
    """Soft-delete a user (deactivates, does not purge). Recoverable via restore endpoint."""
    _check_pin(request)
    try:
        users.delete_user(username)
        return {"ok": True, "note": "User deactivated (not purged). Use /restore to recover."}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/admin/users/{username}/restore")
def admin_restore_user(request: Request, username: str):
    """Restore a soft-deleted user (sets active=1)."""
    _check_pin(request)
    try:
        user = users.restore_user(username)
        return {"ok": True, "user": user}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/admin/users/{username}/impersonate")
def admin_impersonate(request: Request, username: str, response: Response):
    """Superadmin-only: set httponly cookie as target user for support/verification."""
    _check_pin(request)
    from routers.auth import _verify_cookie, _sign_cookie
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    caller = payload.split(":")[0]
    caller_user = users.get_user(caller)
    if not caller_user or caller_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin can impersonate users")
    target = users.get_user(username)
    if not target or not target.get("active"):
        raise HTTPException(status_code=404, detail="User not found or inactive")
    if target.get("role") == "superadmin":
        raise HTTPException(status_code=400, detail="Cannot impersonate another superadmin")
    # Store caller's current cookie so they can return without re-logging in
    origin_cookie = cookie  # the signed superadmin cookie value
    token = users.create_session(username, target["role"], target.get("name", username), target.get("department", ""))
    cookie_payload = f"{username}:{target['role']}:{token}"
    cookie_value = _sign_cookie(cookie_payload)
    # Set the new httponly cookie — this replaces the superadmin session in the browser
    response.set_cookie("fslapp_auth", cookie_value, httponly=True, samesite="lax", max_age=86400)
    activity.log_activity(user=caller, action="impersonate", detail=f"Logged in as {target.get('name', username)} ({target['role']})")
    return {
        "username": username,
        "name": target.get("name", username),
        "role": target["role"],
        "origin_cookie": origin_cookie,
    }


@router.post("/api/admin/impersonate/return")
def admin_impersonate_return(body: dict, response: Response):
    """Restore the original superadmin session after impersonation."""
    from routers.auth import _verify_cookie
    origin_cookie = body.get("origin_cookie", "")
    if not origin_cookie or not _verify_cookie(origin_cookie):
        raise HTTPException(status_code=400, detail="Invalid origin cookie")
    response.set_cookie("fslapp_auth", origin_cookie, httponly=True, samesite="lax", max_age=86400)
    return {"ok": True}


@router.post("/api/admin/users/seed-restore")
def admin_seed_restore(request: Request):
    """Re-run seed_users() to restore any missing seed users from SEED_PASS_* env vars."""
    _check_pin(request)
    import io, logging
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger('users').addHandler(handler)
    try:
        users.seed_users()
    finally:
        logging.getLogger('users').removeHandler(handler)
    return {"ok": True, "log": buf.getvalue() or "All seed users already present."}


@router.post("/api/admin/users/restore-missing")
def admin_restore_backup(request: Request):
    """Restore missing rows in Postgres core.* from the latest Azure Blob backup.
    Uses ON CONFLICT DO NOTHING — never overwrites existing Postgres data."""
    _check_pin(request)
    import db_backup
    ok = db_backup.restore_latest()
    if not ok:
        raise HTTPException(status_code=503, detail="No backup found or restore failed")
    return {"ok": True, "source": "azure_blob"}


@router.get("/api/admin/users/mirror-status")
def admin_backup_info(request: Request):
    """Show sync status of Postgres core.users and file fallback."""
    _check_pin(request)
    import user_backup
    return user_backup.backup_info()


@router.get("/api/admin/sessions")
def admin_list_sessions(request: Request):
    """List active sessions (who's logged in)."""
    _check_pin(request)
    return users.list_sessions()


# ── Settings ─────────────────────────────────────────────────────────────────

@router.get("/api/admin/settings")
def admin_get_settings(request: Request):
    """Get app settings. PIN-protected."""
    _check_pin(request)
    settings = _load_settings()
    settings.setdefault('pta_refresh_interval', 900)
    return settings


@router.put("/api/admin/settings")
def admin_update_settings(request: Request, body: dict):
    """Update app settings. PIN-protected."""
    _check_pin(request)
    settings = _load_settings()
    if 'pta_refresh_interval' in body:
        val = int(body['pta_refresh_interval'])
        if val < 60 or val > 3600:
            raise HTTPException(status_code=400, detail="Interval must be 60-3600 seconds")
        settings['pta_refresh_interval'] = val
    if 'chatbot' in body:
        cb = body['chatbot']
        settings['chatbot'] = {
            'enabled': cb.get('enabled', False),
            'provider': cb.get('provider', 'openai'),
            'primary_model': cb.get('primary_model', ''),
            'fallback_model': cb.get('fallback_model', ''),
        }
    # Optimizer chat has its own provider + model (keys shared with above)
    if 'optimizer_chat' in body:
        oc = body['optimizer_chat']
        settings['optimizer_chat'] = {
            'provider': oc.get('provider', 'anthropic'),
            'model': oc.get('model', ''),
        }
    if 'help_video_url' in body:
        settings['help_video_url'] = (body['help_video_url'] or '').strip()
    if 'accounting' in body:
        acct = body['accounting']
        settings['accounting'] = {
            'audit_prompt': acct.get('audit_prompt', ''),
        }
    if 'features' in body:
        feat = body['features']
        settings.setdefault('features', _DEFAULT_FEATURES.copy())
        for k in _DEFAULT_FEATURES:
            if k in feat:
                settings['features'][k] = bool(feat[k])
    _save_settings(settings)
    return settings


# ── Bonus Tiers ──────────────────────────────────────────────────────────────

@router.get("/api/admin/bonus-tiers")
def api_get_bonus_tiers(request: Request):
    """Get configurable bonus tiers for contractor garages."""
    _check_pin(request)
    return accounting.get_bonus_tiers()


@router.put("/api/admin/bonus-tiers")
def api_set_bonus_tiers(request: Request, body: list):
    """Replace bonus tiers. Body: [{min_pct, bonus_per_sa, label}, ...]"""
    _check_pin(request)
    for t in body:
        if 'min_pct' not in t or 'bonus_per_sa' not in t:
            raise HTTPException(400, "Each tier needs min_pct and bonus_per_sa")
    accounting.set_bonus_tiers(body)
    return accounting.get_bonus_tiers()


# ── Accounting Rates ─────────────────────────────────────────────────────────

@router.get("/api/admin/accounting-rates")
def api_get_accounting_rates(request: Request):
    """Get all accounting reference rates (included miles, audit thresholds)."""
    _check_pin(request)
    return accounting.get_accounting_rates()


@router.put("/api/admin/accounting-rates/{code}")
def api_set_accounting_rate(request: Request, code: str, body: dict):
    """Update the value for a single accounting rate."""
    _check_pin(request)
    if 'value' not in body:
        raise HTTPException(400, "body must include 'value'")
    try:
        val = float(body['value'])
    except (TypeError, ValueError):
        raise HTTPException(400, "'value' must be a number")
    try:
        return accounting.set_accounting_rate(code, val)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ── Activity Log ─────────────────────────────────────────────────────────────

@router.get("/api/admin/activity-log")
def api_get_activity_log(request: Request, limit: int = 100, user: str = None, action: str = None):
    """Get recent activity log entries."""
    _check_pin(request)
    return activity.get_activity_log(limit=limit, user=user, action=action)


@router.delete("/api/admin/activity-log")
def api_clear_activity_log(request: Request):
    """Clear all activity log entries."""
    _check_pin(request)
    from repositories import activity as _activity_repo
    count = _activity_repo.clear_activity_log()
    return {"cleared": count}


@router.get("/api/admin/activity-stats")
def api_get_activity_stats(request: Request):
    """Get activity log summary stats."""
    _check_pin(request)
    return activity.get_activity_stats()


# ── Territories List ──────────────────────────────────────────────────────────

@router.get("/api/admin/territories-list")
def admin_territories_list(request: Request):
    """Return all active Salesforce Service Territories. Used to assign contractors."""
    _check_pin(request)
    try:
        result = sf_query(
            "SELECT Id, Name FROM ServiceTerritory WHERE IsActive = true ORDER BY Name"
        )
        records = result.get("records", []) if isinstance(result, dict) else []
        territories = [{"id": r["Id"], "name": r["Name"]} for r in records]
        return {"territories": territories}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Salesforce query failed: {e}")
