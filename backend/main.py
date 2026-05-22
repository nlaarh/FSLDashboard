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
from routers.auth import _verify_cookie, _PUBLIC_PATHS, _get_department, _get_role, _finance_ok, _supervisor_blocked, _admin_allowed
import cache
import refresher
import users as _users
from repositories import settings, activity

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="FSL App", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173", "https://fslapp-nyaaa.azurewebsites.net"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pool exhaustion handler — return 503 with Retry-After instead of 500 ────

try:
    from psycopg_pool import PoolTimeout as _PoolTimeout

    @app.exception_handler(_PoolTimeout)
    async def _pool_timeout_handler(request: Request, exc: _PoolTimeout):
        return JSONResponse(
            status_code=503,
            content={"detail": "Server busy — please retry in a moment"},
            headers={"Retry-After": "2"},
        )
except ImportError:
    pass  # psycopg_pool not available in test env


# ── Auth middleware ──────────────────────────────────────────────────────────

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Always allow public paths, static assets, and tracking pages
    if path in _PUBLIC_PATHS or path.startswith("/assets/"):
        return await call_next(request)
    if path.startswith("/track/") or (path.startswith("/api/track/") and request.method == "GET"):
        return await call_next(request)
    if path == "/api/admin/impersonate/return":
        return await call_next(request)
    # Azure Easy Auth: only trust this header when running in Azure App Service
    if request.headers.get("x-ms-client-principal") and os.environ.get("WEBSITE_SITE_NAME"):
        return await call_next(request)
    # Admin cookie
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        # Access control by department and role
        parts = payload.split(":")
        username = parts[0]
        if len(parts) > 2:
            _users.keep_alive(parts[2])  # extend expires_at in user_sessions (throttled 1/min)
        dept = _get_department(username)
        if dept == 'finance' and path.startswith('/api/') and not _finance_ok(path):
            return JSONResponse(status_code=403, content={"detail": "Access restricted to Accounting only"})
        role = _get_role(username)
        if role == 'ers-supervisor' and path.startswith('/api/') and _supervisor_blocked(path):
            return JSONResponse(status_code=403, content={"detail": "Access restricted"})
        if path.startswith('/api/admin/') and not _admin_allowed(role):
            return JSONResponse(status_code=403, content={"detail": "Admin access restricted"})
        return await call_next(request)
    # Local dev: no auth needed
    if os.environ.get("WEBSITE_SITE_NAME") is None:
        return await call_next(request)
    # Not authenticated — API calls get 401; page requests get the SPA so React renders <Landing />
    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    return await call_next(request)


@app.middleware("http")
async def activity_log_middleware(request: Request, call_next):
    """Log API requests with timing, user, and endpoint."""
    import time as _time
    path = request.url.path
    # Only log API calls, not static assets
    if not path.startswith("/api/"):
        return await call_next(request)
    # Skip noisy endpoints and binary downloads (middleware corrupts binary responses)
    if path in ("/api/admin/status", "/api/admin/sessions", "/api/ops/brief") or '/export' in path:
        return await call_next(request)

    start = _time.time()
    response = await call_next(request)
    duration_ms = round((_time.time() - start) * 1000, 1)

    # Extract user from cookie
    user = None
    cookie = request.cookies.get("fslapp_auth")
    if cookie:
        payload = _verify_cookie(cookie)
        if payload:
            parts = payload.split(":")
            user = parts[0] if parts else None

    # Fire-and-forget — daemon thread keeps this off the async event loop
    # and off the writer pool critical path for the response.
    threading.Thread(
        target=activity.log_activity,
        kwargs=dict(
            user=user,
            action='api_request',
            endpoint=path,
            method=request.method,
            status_code=response.status_code,
            duration_ms=duration_ms,
            ip=request.client.host if request.client else None,
            user_agent=(request.headers.get('user-agent') or '')[:200],
        ),
        daemon=True,
    ).start()

    return response


# ── Register all routers ─────────────────────────────────────────────────────

from routers import (
    auth, admin, garages, garages_performance, garages_revenue, command_center, ops,
    map as map_router,
    dispatch_drill, dispatch_drill_detail, dispatch_trends, dispatch_trends_monthly,
    dispatch_satisfaction, satisfaction_garage, satisfaction_day, satisfaction_scorecard,
    issues, pta, chatbot, data_quality, matrix,
    tracking, misc, misc_diagnostics, insights, insights_health, sa_report,
    garages_scorecard, garages_export, live_dispatch, watchlist, watchlist_assist, accounting,
    accounting_reviews, accounting_ai, optimizer, optimizer_chat, reporting,
    garages_revenue_export, password_reset, dispatch_score, admin_reference,
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(garages.router)
app.include_router(command_center.router)
app.include_router(ops.router)
app.include_router(map_router.router)
app.include_router(dispatch_drill.router)
app.include_router(dispatch_drill_detail.router)
app.include_router(dispatch_trends.router)
app.include_router(dispatch_satisfaction.router)
app.include_router(satisfaction_garage.router)
app.include_router(satisfaction_day.router)
app.include_router(issues.router)
app.include_router(pta.router)
app.include_router(chatbot.router)
app.include_router(data_quality.router)
app.include_router(matrix.router)
app.include_router(tracking.router)
app.include_router(misc.router)
app.include_router(misc_diagnostics.router)
app.include_router(sa_report.router)
app.include_router(garages_scorecard.router)
app.include_router(garages_export.router)
app.include_router(garages_performance.router)
app.include_router(garages_revenue.router)
app.include_router(garages_revenue_export.router)
app.include_router(insights.router)
app.include_router(insights_health.router)
app.include_router(dispatch_trends_monthly.router)
app.include_router(satisfaction_scorecard.router)
app.include_router(live_dispatch.router)
app.include_router(watchlist.router)
app.include_router(watchlist_assist.router)
app.include_router(accounting.router)
app.include_router(accounting_reviews.router)
app.include_router(accounting_ai.router)
app.include_router(optimizer.router)
app.include_router(optimizer_chat.router)
app.include_router(reporting.router)
app.include_router(password_reset.router)
app.include_router(dispatch_score.router)
app.include_router(admin_reference.router)


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
                dispatch_trends_monthly._generate_month_trends(current_month)
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

                # Satisfaction scorecard (reads from cached overviews — zero SF queries)
                log.info("Nightly: refreshing satisfaction scorecard...")
                cache.invalidate(satisfaction_scorecard.CACHE_KEY)
                cache.disk_invalidate(satisfaction_scorecard.CACHE_KEY)
                result = satisfaction_scorecard.generate_scorecard()
                cache.put(satisfaction_scorecard.CACHE_KEY, result, 86400)
                cache.disk_put(satisfaction_scorecard.CACHE_KEY, result, 86400)
                log.info("Nightly: satisfaction scorecard complete.")
            finally:
                cache.fs_lock_release('nightly_trends')

        except Exception as e:
            log.warning(f"Nightly trends refresh failed: {e}")
            cache.fs_lock_release('nightly_trends')
            time.sleep(300)


def _scrub_sensitive_db_keys():
    """Remove any sensitive API keys that may have been stored in the DB.
    Keys are now read exclusively from environment variables."""
    for key in ('anthropic_api_key', 'openai_api_key', 'google_maps'):
        settings.delete_setting(key)
    cb = settings.get_setting('chatbot')
    if cb and isinstance(cb, dict) and 'api_key' in cb:
        cb.pop('api_key')
        settings.put_setting('chatbot', cb)


def _ensure_cache_table():
    """Create core.cache table if it doesn't exist — missing from original schema migration."""
    try:
        import db_adapter
        with db_adapter.writer() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key        TEXT PRIMARY KEY,
                    data       TEXT NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS cache_expires_idx ON cache (expires_at)")
        import logging
        logging.getLogger('startup').info("core.cache table ensured")
    except Exception as e:
        import logging
        logging.getLogger('startup').warning("Could not ensure cache table: %s", e)


_DISPATCHER_SEED = [
    ('Amanda',   'Grover',       'agrover@nyaaa.com',       'Dispatcher'),
    ('Catherine','Alger',        'calger@nyaaa.com',        'Supervisor'),
    ('Chantele', 'Ross',         'cross@nyaaa.com',         'Dispatcher'),
    ('Chris',    'MacNeil',      'cmacneil@nyaaa.com',      'Manager'),
    ('Daniel',   'Fisher',       'dfisher@nyaaa.com',       'Manager'),
    ('Debbie',   'Taylor',       'dtaylor@nyaaa.com',       'Dispatcher'),
    ('Deborah',  'Kalenda',      'dkalenda@nyaaa.com',      'Dispatcher'),
    ('Deonna',   'Massey',       'dmassey@nyaaa.com',       'Dispatcher'),
    ('Diana',    'Oakes',        'doakes@nyaaa.com',        'Dispatcher'),
    ('Domingo',  'Santiago',     'dsantiago@nyaaa.com',     'Dispatcher'),
    ('Janice',   'Sims',         'jsims@nyaaa.com',         'Dispatcher'),
    ('Jay',      'Miller',       'jay.miller@nyaaa.com',    'Dispatcher'),
    ('Jeremy',   'Harrington',   'jharrington@nyaaa.com',   'Manager'),
    ('Jon',      'Carroll',      'jcarroll@nyaaa.com',      'Manager'),
    ('Joseph',   'Hoefner',      'jhoefner@nyaaa.com',      'Dispatcher'),
    ('Justine',  'Semple',       'jsemple@nyaaa.com',       'Dispatcher'),
    ('Kateri',   'Filippi',      'kfilippi@nyaaa.com',      'Dispatcher'),
    ('Kathleen', 'Reeve',        'kreeve@nyaaa.com',        'Dispatcher'),
    ('Katie',    'Tamez',        'ktamez@nyaaa.com',        'Dispatcher'),
    ('Kenneth',  'White',        'kwhite@nyaaa.com',        'Dispatcher'),
    ('Kristin',  'Jackson',      'kjackson@nyaaa.com',      'Dispatcher'),
    ('Kristen',  'Hartman',      'khartman@nyaaa.com',      'Supervisor'),
    ('Lynn',     'Pilarski',     'lpilarski@nyaaa.com',     'Dispatcher'),
    ('Mark',     'Mika',         'mmika@nyaaa.com',         'Manager'),
    ('Marisa',   'Tanner',       'mtanner@nyaaa.com',       'Dispatcher'),
    ('Marneen',  'Carter',       'mcarter@nyaaa.com',       'Dispatcher'),
    ('Mary',     'Trichilo',     'mtrichilo@nyaaa.com',     'Supervisor'),
    ('Matthew',  'Spencer',      'mspencer@nyaaa.com',      'Dispatcher'),
    ('Michael',  'Martinick',    'mmartinick@nyaaa.com',    'Supervisor'),
    ('Paige',    'White',        'pwhite@nyaaa.com',        'Dispatcher'),
    ('Robert',   'Lyle',         'rlyle@nyaaa.com',         'Manager'),
    ('Robert',   'Prendergast',  'rprendergast@nyaaa.com',  'Manager'),
    ('Samantha', 'Hendrix',      'shendrix@nyaaa.com',      'Dispatcher'),
    ('Shawn',    'Gancasz',      'sgancasz@nyaaa.com',      'Assistant Manager'),
    ('Stephen',  'Horn',         'shorn@nyaaa.com',         'Manager'),
    ('Todd',     'Coulter',      'tcoulter@nyaaa.com',      'Manager'),
    ('Tyler',    'LaFave',       'tlafave@nyaaa.com',       'Dispatcher'),
]

# Known SF IDs, channels, and observer flags — sourced from verified registry
_DISPATCHER_SF_SEED = [
    ('jharrington@nyaaa.com',  '005Pb0000009r4FIAQ', 'Fleet',      False),
    ('jcarroll@nyaaa.com',     '005Pb0000009r4LIAQ', 'Fleet',      False),
    ('calger@nyaaa.com',       '005Pb0000009qjBIAQ', 'Towbook',    False),
    ('khartman@nyaaa.com',     '005Pb0000009qjDIAQ', 'Towbook',    False),
    ('sgancasz@nyaaa.com',     '005Pb0000009r4CIAQ', 'Mixed',      False),
    ('dkalenda@nyaaa.com',     '005Pb0000009qjGIAQ', 'Towbook',    False),
    ('mtrichilo@nyaaa.com',    '005Pb0000009qjUIAQ', 'Supervisor', False),
    ('cmacneil@nyaaa.com',     '005Pb0000009qjbIAA', 'Overnight',  False),
    ('shorn@nyaaa.com',        '005Pb0000009qjaIAA', 'Overnight',  False),
    ('rprendergast@nyaaa.com', '005Pb0000009qjgIAA', None,         True),
    ('tcoulter@nyaaa.com',     '005Pb0000009qjXIAQ', None,         True),
    ('mmika@nyaaa.com',        '005Pb0000009qjcIAA', None,         True),
    ('rlyle@nyaaa.com',        '005Pb00000qNc6gIAC', None,         True),
]


_NEW_ACCOUNTING_RATES = [
    ('em_rate_per_mile',  'EM Extra Tow Mileage per Mile',  2.0,  '$/mi',  'Confirmed from SF WOLI data (248 records, consistent $2.00/mi)', 'Reference Rates'),
    ('ba_rate_per_call',  'BA Base Rate per Call',         40.0,  '$/call','Estimated flat fee for BA (Base Rate) — from ERS_Work_Order_Cost__c sample', 'Reference Rates'),
    ('mh_rate_per_call',  'MH Medium/Heavy Rate per Call', 20.0,  '$/call','Estimated flat surcharge for MH — from ERS_Work_Order_Cost__c sample', 'Reference Rates'),
]


def _ensure_accounting_rates_rows():
    """Insert missing reference rate rows into an existing deployment."""
    try:
        import logging
        import db_adapter
        with db_adapter.writer() as db:
            for code, label, value, unit, notes, category in _NEW_ACCOUNTING_RATES:
                db.execute(
                    """
                    INSERT INTO accounting_rates (code, label, value, unit, notes, category)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (code) DO NOTHING
                    """,
                    (code, label, value, unit, notes, category),
                )
        logging.getLogger('startup').info("accounting_rates rows ensured")
    except Exception as e:
        import logging
        logging.getLogger('startup').warning("Could not ensure accounting_rates rows: %s", e)


def _ensure_dispatchers_table():
    """Create core.dispatchers table with sf_user_id/channel/observer and seed roster."""
    try:
        import db_adapter
        with db_adapter.writer() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS dispatchers (
                    id         SERIAL PRIMARY KEY,
                    first_name TEXT NOT NULL,
                    last_name  TEXT NOT NULL,
                    email      TEXT UNIQUE NOT NULL,
                    position   TEXT NOT NULL,
                    sf_user_id TEXT,
                    channel    TEXT,
                    observer   BOOLEAN NOT NULL DEFAULT FALSE,
                    active     BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            # Add columns that may be absent from earlier schema version
            for col_ddl in (
                "ALTER TABLE dispatchers ADD COLUMN IF NOT EXISTS sf_user_id TEXT",
                "ALTER TABLE dispatchers ADD COLUMN IF NOT EXISTS channel TEXT",
                "ALTER TABLE dispatchers ADD COLUMN IF NOT EXISTS observer BOOLEAN NOT NULL DEFAULT FALSE",
            ):
                db.execute(col_ddl)

            for first, last, email, position in _DISPATCHER_SEED:
                db.execute("""
                    INSERT INTO dispatchers (first_name, last_name, email, position)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                """, (first, last, email, position))

            # Seed SF IDs and channels; always set observer flag from authoritative list
            for email, sf_id, channel, observer in _DISPATCHER_SF_SEED:
                db.execute("""
                    UPDATE dispatchers
                    SET sf_user_id = COALESCE(sf_user_id, %s),
                        channel    = COALESCE(channel, %s),
                        observer   = %s
                    WHERE email = %s
                """, (sf_id, channel, observer, email))

            # dfisher excluded from dispatch scoring per spec
            db.execute("UPDATE dispatchers SET observer = TRUE WHERE email = 'dfisher@nyaaa.com'")

        import logging
        logging.getLogger('startup').info(
            "dispatchers table ensured (%d rows, %d sf_ids seeded)",
            len(_DISPATCHER_SEED), len(_DISPATCHER_SF_SEED),
        )
    except Exception as e:
        import logging
        logging.getLogger('startup').warning("Could not ensure dispatchers table: %s", e)


@app.on_event("startup")
async def startup():
    _ensure_cache_table()
    _ensure_dispatchers_table()
    _ensure_accounting_rates_rows()

    import users
    users.seed_users()

    # Purge any sensitive API keys previously stored in DB — now env-var only
    _scrub_sensitive_db_keys()

    # Start proactive cache refresher (replaces _warmup_cache)
    # The refresher handles leader election — safe to call from all workers
    refresher.start()

    # Optimizer blob sync — disabled until DuckDB is re-enabled
    # import optimizer_blob_sync
    # optimizer_blob_sync.start()

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
        return FileResponse(_static_dir / "index.html",
                            headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
