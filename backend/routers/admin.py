"""Admin router — PIN-protected admin panel, cache flush, user management, settings."""

import os, json as _json
from fastapi import APIRouter, HTTPException, Query, Request
import users
import cache
from sf_client import get_stats as sf_stats
import time

router = APIRouter()

# ── Admin PIN ────────────────────────────────────────────────────────────────
_ADMIN_PIN = os.getenv('ADMIN_PIN', '121838')


def _check_pin(request: Request):
    pin = request.headers.get('X-Admin-Pin', '')
    if pin != _ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Invalid PIN")


# ── Settings persistence ─────────────────────────────────────────────────────

_DEFAULT_FEATURES = {
    'pta_advisor': True,
    'onroute': True,
    'matrix': True,
    'chat': True,
}


def _load_settings():
    try:
        import database
        return database.get_all_settings()
    except Exception:
        return {}

def _save_settings(settings: dict):
    import database
    for key, value in settings.items():
        database.put_setting(key, value)


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
    email = body.get("email", "").strip()
    phone = body.get("phone", "").strip()
    valid_roles = ("superadmin", "admin", "manager", "officer", "supervisor", "viewer")
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"role must be one of: {', '.join(valid_roles)}")
    try:
        return users.create_user(username, password, name, role, email=email, phone=phone)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/api/admin/users/{username}")
def admin_update_user(request: Request, username: str, body: dict):
    """Update a user."""
    _check_pin(request)
    try:
        return users.update_user(
            username,
            name=body.get("name"),
            role=body.get("role"),
            password=body.get("password") or None,
            active=body.get("active"),
            email=body.get("email"),
            phone=body.get("phone"),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/api/admin/users/{username}")
def admin_delete_user(request: Request, username: str):
    """Delete a user."""
    _check_pin(request)
    try:
        users.delete_user(username)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
            'api_key': cb.get('api_key', ''),
            'primary_model': cb.get('primary_model', ''),
            'fallback_model': cb.get('fallback_model', ''),
        }
    if 'help_video_url' in body:
        settings['help_video_url'] = (body['help_video_url'] or '').strip()
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
    import database
    return database.get_bonus_tiers()


@router.put("/api/admin/bonus-tiers")
def api_set_bonus_tiers(request: Request, body: list):
    """Replace bonus tiers. Body: [{min_pct, bonus_per_sa, label}, ...]"""
    _check_pin(request)
    import database
    for t in body:
        if 'min_pct' not in t or 'bonus_per_sa' not in t:
            raise HTTPException(400, "Each tier needs min_pct and bonus_per_sa")
    database.set_bonus_tiers(body)
    return database.get_bonus_tiers()


# ── Activity Log ─────────────────────────────────────────────────────────────

@router.get("/api/admin/activity-log")
def api_get_activity_log(request: Request, limit: int = 100, user: str = None, action: str = None):
    """Get recent activity log entries."""
    _check_pin(request)
    import database
    return database.get_activity_log(limit=limit, user=user, action=action)


@router.delete("/api/admin/activity-log")
def api_clear_activity_log(request: Request):
    """Clear all activity log entries."""
    _check_pin(request)
    import database
    with database.get_db() as conn:
        count = conn.execute("DELETE FROM activity_log").rowcount
    return {"cleared": count}


@router.get("/api/admin/activity-stats")
def api_get_activity_stats(request: Request):
    """Get activity log summary stats."""
    _check_pin(request)
    import database
    return database.get_activity_stats()
