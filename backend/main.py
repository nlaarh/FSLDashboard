"""FSL App — FastAPI backend. All data live from Salesforce with proactive caching.

Scalability: Designed for 1000+ concurrent users.
- Proactive refresher keeps all hot cache keys warm on a schedule
- Users always served from cache (L1 memory or L2 disk) — never wait for SF
- SF sees constant ~10-15 calls/min regardless of user count
"""

import os, sys, time, threading
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'), override=False)  # apidev/.env
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=False)  # backend/.env

from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

# Auth helpers needed by middleware
from routers.auth import _verify_cookie, _PUBLIC_PATHS
import cache
import refresher
import database

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
    dispatch_drill, dispatch_trends, dispatch_satisfaction, satisfaction_garage,
    issues, pta, chatbot, data_quality, matrix,
    tracking, misc, insights, sa_report, garages_scorecard,
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(garages.router)
app.include_router(command_center.router)
app.include_router(ops.router)
app.include_router(map_router.router)
app.include_router(dispatch_drill.router)
app.include_router(dispatch_trends.router)
app.include_router(dispatch_satisfaction.router)
app.include_router(satisfaction_garage.router)
app.include_router(issues.router)
app.include_router(pta.router)
app.include_router(chatbot.router)
app.include_router(data_quality.router)
app.include_router(matrix.router)
app.include_router(tracking.router)
app.include_router(misc.router)
app.include_router(sa_report.router)
app.include_router(garages_scorecard.router)
app.include_router(insights.router)


# ── Startup: proactive cache refresher ──────────────────────────────────────

_start_time = time.time()


def _nightly_trends_refresh():
    """Refresh 30-day trends and current month trends at 12:05 AM ET daily.

    These are too heavy for the regular refresher (~45K rows, 4 parallel queries).
    They run once daily and are disk-cached for 24h.
    """
    import logging
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    log = logging.getLogger('nightly')
    ET = ZoneInfo('America/New_York')
    while True:
        try:
            now_et = datetime.now(ET)
            target = now_et.replace(hour=0, minute=5, second=0, microsecond=0)
            if target <= now_et:
                target += timedelta(days=1)
            sleep_sec = (target - now_et).total_seconds()
            log.info(f"Nightly trends refresh scheduled in {sleep_sec/3600:.1f}h ({target.date()})")
            time.sleep(sleep_sec)

            # Use filesystem lock so only one worker runs this
            if not cache.fs_lock_acquire('nightly_trends', max_age=3600):
                log.info("Nightly trends: another worker is handling it")
                time.sleep(3600)
                continue

            try:
                # 30-day trends
                log.info("Nightly: refreshing 30-day trends...")
                cache.disk_invalidate('insights_trends_30d')
                cache.invalidate('insights_trends_30d')
                dispatch_trends.api_trends()
                for _i in range(120):
                    time.sleep(10)
                    if cache.get('insights_trends_30d'):
                        log.info("Nightly: 30-day trends complete.")
                        break

                # Current month trends
                current_month = datetime.now(ET).strftime('%Y-%m')
                cache_key = f'insights_trends_month_{current_month}'
                log.info(f"Nightly: refreshing monthly trends for {current_month}...")
                cache.disk_invalidate(cache_key)
                cache.invalidate(cache_key)
                dispatch_trends._generate_month_trends(current_month)
                log.info(f"Nightly: monthly trends complete for {current_month}.")

                # Current month satisfaction overview (picks up new surveys)
                sat_key = f'satisfaction_overview_{current_month}'
                log.info(f"Nightly: refreshing satisfaction overview for {current_month}...")
                cache.disk_invalidate(sat_key)
                cache.invalidate(sat_key)
                result = dispatch_satisfaction._generate_satisfaction_overview(current_month)
                cache.put(sat_key, result, 43200)
                cache.disk_put(sat_key, result, 43200)
                log.info(f"Nightly: satisfaction overview complete for {current_month}.")
            finally:
                cache.fs_lock_release('nightly_trends')

        except Exception as e:
            log.warning(f"Nightly trends refresh failed: {e}")
            cache.fs_lock_release('nightly_trends')
            time.sleep(300)


@app.on_event("startup")
async def startup():
    # Initialize SQLite database (settings, cache, bonus_tiers)
    database.init_db()
    database.migrate_settings_json()

    # Start proactive cache refresher (replaces _warmup_cache)
    # The refresher handles leader election — safe to call from all workers
    refresher.start()

    # Nightly heavy trends refresh (too heavy for regular refresher)
    threading.Thread(target=_nightly_trends_refresh, daemon=True).start()

    # Startup trends check: if disk cache is stale, trigger immediate refresh
    def _startup_trends_check():
        time.sleep(15)
        if not cache.disk_get('insights_trends_30d'):
            import logging
            logging.getLogger('startup').info("Trends cache stale/missing — triggering refresh")
            dispatch_trends.api_trends()
    threading.Thread(target=_startup_trends_check, daemon=True).start()


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
