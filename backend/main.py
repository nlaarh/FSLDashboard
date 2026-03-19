"""FSL App — FastAPI backend. All data live from Salesforce with in-memory caching."""

import os, sys, time, threading
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=False)

from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

# Auth helpers needed by middleware
from routers.auth import _verify_cookie, _PUBLIC_PATHS

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="FSL App", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173", "https://fslapp-nyaaa.azurewebsites.net"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth middleware ──────────────────────────────────────────────────────────

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Always allow public paths, static assets, and tracking pages
    if path in _PUBLIC_PATHS or path.startswith("/assets/"):
        return await call_next(request)
    if path.startswith("/track/") or (path.startswith("/api/track/") and request.method == "GET"):
        return await call_next(request)
    # Azure Easy Auth: if SSO is active, this header is set by Azure
    if request.headers.get("x-ms-client-principal"):
        return await call_next(request)
    # Admin cookie
    cookie = request.cookies.get("fslapp_auth")
    if cookie and _verify_cookie(cookie):
        return await call_next(request)
    # Local dev: no auth needed
    if os.environ.get("WEBSITE_SITE_NAME") is None:
        return await call_next(request)
    # Not authenticated → redirect to login
    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    return RedirectResponse("/login")


# ── Register all routers ─────────────────────────────────────────────────────

from routers import (
    auth, admin, garages, command_center, ops, map as map_router,
    dispatch_routes, issues, pta, chatbot, data_quality, matrix,
    tracking, misc, insights, sa_report,
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(garages.router)
app.include_router(command_center.router)
app.include_router(ops.router)
app.include_router(map_router.router)
app.include_router(dispatch_routes.router)
app.include_router(issues.router)
app.include_router(pta.router)
app.include_router(chatbot.router)
app.include_router(data_quality.router)
app.include_router(matrix.router)
app.include_router(tracking.router)
app.include_router(misc.router)
app.include_router(sa_report.router)
app.include_router(insights.router)


# ── Cache warmup on startup ─────────────────────────────────────────────────

_start_time = time.time()


def _warmup_cache():
    """Pre-fetch ALL key endpoints so first users never wait for cold SF queries."""
    import logging
    log = logging.getLogger('warmup')
    try:
        log.info("Cache warmup starting (full)...")

        warmup_fns = [
            ("garages_list", lambda: garages.list_garages()),
            ("ops_garages", lambda: __import__('ops').get_ops_garages()),
            ("ops_territories", lambda: __import__('ops').get_ops_territories()),
            ("command_center", lambda: command_center.command_center()),
            ("ops_brief", lambda: ops.ops_brief()),
            ("map_grids", lambda: map_router.get_map_grids()),
            ("map_drivers", lambda: map_router.get_map_drivers()),
            ("pta_advisor", lambda: pta.pta_advisor()),
            # trends_30d excluded from warmup — too heavy for startup (4 parallel SF queries, 45K+ rows)
            # It uses cached_query_persistent so first request triggers it, then cached to disk for 24h
        ]

        for name, fn in warmup_fns:
            try:
                fn()
                log.info(f"  {name}: cached")
            except Exception as e:
                log.warning(f"  {name} warmup failed: {e}")

        log.info("Cache warmup complete.")
    except Exception as e:
        log.warning(f"Cache warmup error: {e}")


def _nightly_trends_refresh():
    """Refresh 30-day trends at 12:05 AM ET daily."""
    import logging
    from datetime import datetime, timezone, timedelta
    from zoneinfo import ZoneInfo
    log = logging.getLogger('nightly')
    ET = ZoneInfo('America/New_York')
    while True:
        try:
            now_et = datetime.now(ET)
            # Next 00:05 ET
            target = now_et.replace(hour=0, minute=5, second=0, microsecond=0)
            if target <= now_et:
                target += timedelta(days=1)
            sleep_sec = (target - now_et).total_seconds()
            log.info(f"Nightly trends refresh scheduled in {sleep_sec/3600:.1f}h ({target.date()})")
            time.sleep(sleep_sec)
            log.info("Nightly trends refresh starting...")
            cache.disk_invalidate('insights_trends_30d')
            cache.invalidate('insights_trends_30d')
            dispatch_routes.api_trends()  # starts bg thread
            # Poll up to 20 min for the bg thread to populate cache
            for _i in range(120):
                time.sleep(10)
                if cache.get('insights_trends_30d'):
                    log.info("Nightly trends refresh complete.")
                    break
            else:
                raise RuntimeError("Trends bg thread did not complete in 20 min")
        except Exception as e:
            log.warning(f"Nightly trends refresh failed: {e}")
            time.sleep(300)  # Retry in 5 min on failure


def _nightly_month_trends_refresh():
    """Pre-generate current month trends at 3:00 AM ET daily.

    Only refreshes the current month (data is still accumulating).
    Past months are cached for 7 days and don't change, so they're
    generated on first request and then served from disk cache.
    """
    import logging
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    log = logging.getLogger('nightly_month')
    ET = ZoneInfo('America/New_York')
    while True:
        try:
            now_et = datetime.now(ET)
            target = now_et.replace(hour=3, minute=0, second=0, microsecond=0)
            if target <= now_et:
                target += timedelta(days=1)
            sleep_sec = (target - now_et).total_seconds()
            log.info(f"Monthly trends refresh scheduled in {sleep_sec/3600:.1f}h ({target.date()} 3:00 AM ET)")
            time.sleep(sleep_sec)

            # Refresh current month only
            current_month = datetime.now(ET).strftime('%Y-%m')
            cache_key = f'insights_trends_month_{current_month}'
            log.info(f"Monthly trends refresh starting for {current_month}...")
            cache.disk_invalidate(cache_key)
            cache.invalidate(cache_key)
            dispatch_routes._generate_month_trends(current_month)
            log.info(f"Monthly trends refresh complete for {current_month}.")
        except Exception as e:
            log.warning(f"Monthly trends refresh failed: {e}")
            time.sleep(300)


@app.on_event("startup")
async def startup_warmup():
    # Start nightly trends refresh threads
    threading.Thread(target=_nightly_trends_refresh, daemon=True).start()
    threading.Thread(target=_nightly_month_trends_refresh, daemon=True).start()

    # If disk cache is stale/missing on startup, trigger immediate background refresh
    # (covers deploys that happen after 12:05 AM — nightly thread won't fire until tomorrow)
    def _startup_trends_check():
        time.sleep(15)  # let warmup finish first
        if not cache.disk_get('insights_trends_30d'):
            import logging
            logging.getLogger('startup').info("Trends cache stale/missing — triggering immediate refresh on startup")
            dispatch_routes.api_trends()
    threading.Thread(target=_startup_trends_check, daemon=True).start()

    if os.environ.get("WEBSITE_SITE_NAME"):  # Only on Azure
        import random
        delay = random.uniform(0, 5)

        def _delayed_warmup():
            time.sleep(delay)
            _warmup_cache()
        threading.Thread(target=_delayed_warmup, daemon=True).start()


# ── Serve React SPA ─────────────────────────────────────────────────────────

_static_dir = Path(__file__).resolve().parent / "static"

if _static_dir.is_dir():
    _assets_dir = _static_dir / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React SPA — any non-API route returns index.html."""
        file_path = _static_dir / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_static_dir / "index.html")
