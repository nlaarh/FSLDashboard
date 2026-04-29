"""SQLite database module — single persistent store for settings, cache, and config.

On Azure: /home/fslapp/fslapp.db (persistent across deploys)
Locally: ~/.fslapp/fslapp.db

Tables:
- settings: key-value config (API keys, preferences)
- cache: persistent L2 cache (replaces disk JSON files)
- bonus_tiers: configurable contractor bonus rules
- accounting_rates: admin-editable audit thresholds and included-miles reference data
"""

import sqlite3
import json
import time
import os
import logging
from pathlib import Path
from contextlib import contextmanager

log = logging.getLogger('database')

_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_DB_DIR = Path('/home/fslapp') if _ON_AZURE else Path(os.path.expanduser('~/.fslapp'))
_DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(_DB_DIR / 'fslapp.db')

_DEFAULT_BONUS_TIERS = [
    (98, 4.0, '≥98%', 1),
    (96, 3.0, '≥96%', 2),
    (94, 2.0, '≥94%', 3),
    (92, 1.0, '≥92%', 4),
]

# (code, label, value, unit, notes, category)
_DEFAULT_ACCOUNTING_RATES = [
    ('er_included_b',      'Basic ER Miles Included',     4.0,   'mi',  'Basic (B) coverage — en route miles included before overage', 'ER Miles Included'),
    ('er_included_p',      'Plus ER Miles Included',      8.0,   'mi',  'Plus (P) coverage — en route miles included before overage', 'ER Miles Included'),
    ('er_included_pp',     'Premier ER Miles Included',   100.0, 'mi',  'Premier (P+) coverage — effectively unlimited', 'ER Miles Included'),
    ('tow_included_b',     'Basic Tow Miles Included',    3.0,   'mi',  'Basic (B) coverage — tow miles included', 'Tow Miles Included'),
    ('tow_included_p',     'Plus Tow Miles Included',     100.0, 'mi',  'Plus (P) coverage — tow miles included', 'Tow Miles Included'),
    ('tow_included_pp',    'Premier Tow Miles Included',  200.0, 'mi',  'Premier (P+) coverage — tow miles included', 'Tow Miles Included'),
    ('mileage_pay_pct',    'Mileage Pay Threshold',       130.0, '%',   'ER/tow ≤ this % of Google baseline = approve without review', 'Audit Thresholds'),
    ('mileage_review_pct', 'Mileage Review Threshold',    150.0, '%',   'ER/tow ≤ this % = request docs; > this = flag for denial', 'Audit Thresholds'),
    ('time_pay_pct',       'Time Pay Threshold',          120.0, '%',   'Time products (E1/E2/MI) ≤ this % of on-scene = approve', 'Audit Thresholds'),
    ('tl_flag_usd',              'Toll Flag Amount',              30.0,  '$',   'Toll claims above this amount require receipt verification note', 'Audit Thresholds'),
    ('materiality_threshold_usd','Materiality Threshold',         10.0,  '$',   'Adjustments with estimated dollar impact below this amount are flagged as low-materiality (auto-approve signal)', 'Audit Thresholds'),
    ('e1_time_cap_min',          'E1 Time Cap',                   60.0,  'min', 'Maximum payable minutes for E1 Extrication per call', 'Time Caps'),
    ('er_rate_per_mile',         'ER Rate per Mile',               1.75, '$/mi','Estimated unit cost for ER (Enroute Miles) — used for materiality dollar estimate', 'Reference Rates'),
    ('tow_rate_per_mile',        'Tow Rate per Mile',             15.0,  '$/mi','Estimated unit cost for TW tow miles — used for materiality dollar estimate', 'Reference Rates'),
    ('e1_rate_per_min',          'E1/MI Rate per Min',             0.75, '$/min','Estimated unit cost for E1/E2/MI time products — used for materiality dollar estimate', 'Reference Rates'),
]


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist. Called once at startup."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);

            CREATE TABLE IF NOT EXISTS bonus_tiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                min_pct REAL NOT NULL,
                bonus_per_sa REAL NOT NULL,
                label TEXT,
                sort_order INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT (datetime('now')),
                user TEXT,
                action TEXT NOT NULL,
                endpoint TEXT,
                method TEXT DEFAULT 'GET',
                status_code INTEGER,
                duration_ms REAL,
                ip TEXT,
                user_agent TEXT,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_log_timestamp ON activity_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_log_user ON activity_log(user);

            CREATE TABLE IF NOT EXISTS watchlist_manual (
                sa_number TEXT PRIMARY KEY,
                sa_id TEXT,
                added_by TEXT DEFAULT '',
                added_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'viewer',
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS woa_reviews (
                woa_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                note TEXT DEFAULT '',
                reviewer TEXT DEFAULT '',
                reviewed_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS accounting_rates (
                code TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                value REAL NOT NULL DEFAULT 0,
                unit TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                category TEXT DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS opt_sync_audit (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at        TEXT NOT NULL,
                finished_at       TEXT,
                status            TEXT NOT NULL,
                runs_found        INTEGER DEFAULT 0,
                runs_inserted     INTEGER DEFAULT 0,
                runs_skipped      INTEGER DEFAULT 0,
                runs_failed       INTEGER DEFAULT 0,
                verdicts_inserted INTEGER DEFAULT 0,
                rows_purged       INTEGER DEFAULT 0,
                error_detail      TEXT,
                duration_ms       INTEGER
            );
        """)

        # Seed default bonus tiers if empty
        row = conn.execute("SELECT COUNT(*) cnt FROM bonus_tiers").fetchone()
        if row['cnt'] == 0:
            for min_pct, bonus, label, sort in _DEFAULT_BONUS_TIERS:
                conn.execute(
                    "INSERT INTO bonus_tiers (min_pct, bonus_per_sa, label, sort_order) VALUES (?, ?, ?, ?)",
                    (min_pct, bonus, label, sort),
                )
            log.info("Seeded default bonus tiers")

        # Seed default accounting rates if empty
        row = conn.execute("SELECT COUNT(*) cnt FROM accounting_rates").fetchone()
        if row['cnt'] == 0:
            for code, label, value, unit, notes, category in _DEFAULT_ACCOUNTING_RATES:
                conn.execute(
                    "INSERT INTO accounting_rates (code, label, value, unit, notes, category) VALUES (?, ?, ?, ?, ?, ?)",
                    (code, label, value, unit, notes, category),
                )
            log.info("Seeded default accounting rates")

        # Cleanup expired cache rows
        deleted = conn.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),)).rowcount
        if deleted:
            log.info(f"Cleaned up {deleted} expired cache rows")

        # Purge activity logs older than 30 days
        purged = conn.execute("DELETE FROM activity_log WHERE timestamp < datetime('now', '-30 days')").rowcount
        if purged:
            log.info(f"Purged {purged} activity log entries older than 30 days")

    log.info(f"Database initialized at {DB_PATH}")


# ── Settings CRUD ─────────────────────────────────────────────────────────────

def get_setting(key: str, default=None):
    """Get a setting value. Returns parsed JSON or default."""
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row:
            try:
                return json.loads(row['value'])
            except (json.JSONDecodeError, TypeError):
                return row['value']
    return default


def put_setting(key: str, value):
    """Set a setting value (stored as JSON)."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            (key, json.dumps(value)),
        )


def get_all_settings() -> dict:
    """Get all settings as a dict."""
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        result = {}
        for row in rows:
            try:
                result[row['key']] = json.loads(row['value'])
            except (json.JSONDecodeError, TypeError):
                result[row['key']] = row['value']
        return result


def delete_setting(key: str):
    """Delete a setting."""
    with get_db() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


# ── Cache CRUD ────────────────────────────────────────────────────────────────

def cache_get(key: str):
    """Get a cached value if not expired. Returns parsed JSON or None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT data FROM cache WHERE key = ? AND expires_at > ?",
            (key, time.time()),
        ).fetchone()
        if row:
            try:
                return json.loads(row['data'])
            except (json.JSONDecodeError, TypeError):
                return None
    return None


def cache_get_stale(key: str):
    """Get cached value even if expired (fallback)."""
    with get_db() as conn:
        row = conn.execute("SELECT data FROM cache WHERE key = ?", (key,)).fetchone()
        if row:
            try:
                return json.loads(row['data'])
            except (json.JSONDecodeError, TypeError):
                return None
    return None


def cache_put(key: str, data, ttl: int = 300):
    """Store data in cache with TTL."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, data, expires_at, created_at) VALUES (?, ?, ?, datetime('now'))",
            (key, json.dumps(data), time.time() + ttl),
        )


def cache_get_meta(key: str) -> dict:
    """Get cache entry metadata (created_at, expires_at). Returns {} if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT created_at, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row:
            return {'created_at': row['created_at'], 'expires_at': row['expires_at']}
    return {}


def cache_delete(key: str):
    """Delete a specific cache entry."""
    with get_db() as conn:
        conn.execute("DELETE FROM cache WHERE key = ?", (key,))


def cache_delete_prefix(prefix: str) -> int:
    """Delete all cache entries matching a prefix. Returns count deleted."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM cache WHERE key LIKE ?", (f"{prefix}%",))
        return cursor.rowcount


def cache_cleanup():
    """Remove all expired cache entries."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
        return cursor.rowcount


def cache_stats() -> dict:
    """Return cache statistics."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) cnt FROM cache").fetchone()['cnt']
        alive = conn.execute("SELECT COUNT(*) cnt FROM cache WHERE expires_at > ?", (time.time(),)).fetchone()['cnt']
        return {
            'total_keys': total,
            'alive': alive,
            'stale': total - alive,
        }


# ── Bonus Tiers CRUD ─────────────────────────────────────────────────────────

def get_bonus_tiers() -> list:
    """Get all bonus tiers sorted by min_pct descending (highest first)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, min_pct, bonus_per_sa, label, sort_order FROM bonus_tiers ORDER BY min_pct DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def set_bonus_tiers(tiers: list):
    """Replace all bonus tiers. Each tier: {min_pct, bonus_per_sa, label}."""
    with get_db() as conn:
        conn.execute("DELETE FROM bonus_tiers")
        for i, t in enumerate(tiers):
            conn.execute(
                "INSERT INTO bonus_tiers (min_pct, bonus_per_sa, label, sort_order) VALUES (?, ?, ?, ?)",
                (t['min_pct'], t['bonus_per_sa'], t.get('label', f"≥{t['min_pct']}%"), i),
            )


def bonus_for_pct(pct) -> tuple:
    """Return (bonus_per_sa, tier_label) for a given Technician Totally Satisfied %.
    Reads tiers from DB. Returns (0, '<lowest%') if below all tiers."""
    if pct is None:
        return 0, 'N/A'
    tiers = get_bonus_tiers()
    for t in tiers:  # sorted descending by min_pct
        if pct >= t['min_pct']:
            return t['bonus_per_sa'], t['label']
    lowest = tiers[-1]['min_pct'] if tiers else 92
    return 0, f'<{lowest}%'


# ── Accounting Rates CRUD ─────────────────────────────────────────────────────

def get_accounting_rates() -> list:
    """Get all accounting reference rates, ordered by category then code."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT code, label, value, unit, notes, category, updated_at FROM accounting_rates ORDER BY category, code"
        ).fetchall()
        return [dict(row) for row in rows]


def get_accounting_rates_dict() -> dict:
    """Get accounting rates as {code: value} for quick lookup in audit logic."""
    with get_db() as conn:
        rows = conn.execute("SELECT code, value FROM accounting_rates").fetchall()
        return {row['code']: row['value'] for row in rows}


def set_accounting_rate(code: str, value: float) -> dict:
    """Update the value for a single accounting rate. Returns the updated row."""
    with get_db() as conn:
        conn.execute(
            "UPDATE accounting_rates SET value = ?, updated_at = datetime('now') WHERE code = ?",
            (value, code),
        )
        row = conn.execute(
            "SELECT code, label, value, unit, notes, category, updated_at FROM accounting_rates WHERE code = ?",
            (code,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown accounting rate code: {code}")
        return dict(row)


# ── Migration: settings.json → SQLite ─────────────────────────────────────────

def migrate_settings_json():
    """One-time migration: read settings.json, insert into SQLite, rename to .bak."""
    json_path = Path(os.path.expanduser('~/.fslapp/settings.json'))
    if not json_path.exists():
        return

    try:
        with open(json_path) as f:
            settings = json.load(f)
    except Exception as e:
        log.warning(f"Failed to read settings.json for migration: {e}")
        return

    # Insert each top-level key as a setting
    for key, value in settings.items():
        existing = get_setting(key)
        if existing is None:  # don't overwrite if already migrated
            put_setting(key, value)
            log.info(f"Migrated setting: {key}")

    # Rename to .bak
    bak_path = json_path.with_suffix('.json.bak')
    try:
        json_path.rename(bak_path)
        log.info(f"Renamed settings.json → settings.json.bak")
    except Exception as e:
        log.warning(f"Could not rename settings.json: {e}")


# ── Manual Watchlist ──────────────────────────────────────────────────────────

def _ensure_watchlist_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist_manual (
            sa_number TEXT PRIMARY KEY,
            sa_id TEXT,
            added_by TEXT DEFAULT '',
            added_at TEXT DEFAULT (datetime('now'))
        )
    """)

def watchlist_add(sa_number: str, sa_id: str = '', added_by: str = ''):
    with get_db() as conn:
        _ensure_watchlist_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO watchlist_manual (sa_number, sa_id, added_by) VALUES (?, ?, ?)",
            (sa_number, sa_id, added_by),
        )

def watchlist_remove(sa_number: str):
    with get_db() as conn:
        _ensure_watchlist_table(conn)
        conn.execute("DELETE FROM watchlist_manual WHERE sa_number = ?", (sa_number,))

def watchlist_list() -> list:
    with get_db() as conn:
        _ensure_watchlist_table(conn)
        rows = conn.execute("SELECT sa_number, sa_id, added_by, added_at FROM watchlist_manual ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in rows]

def watchlist_has(sa_number: str) -> bool:
    with get_db() as conn:
        _ensure_watchlist_table(conn)
        row = conn.execute("SELECT 1 FROM watchlist_manual WHERE sa_number = ?", (sa_number,)).fetchone()
        return row is not None


# ── Activity Log ──────────────────────────────────────────────────────────────

def log_activity(user: str = None, action: str = '', endpoint: str = None,
                 method: str = 'GET', status_code: int = None, duration_ms: float = None,
                 ip: str = None, user_agent: str = None, detail: str = None):
    """Log an activity event. Fire-and-forget — never raises."""
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO activity_log (user, action, endpoint, method, status_code, duration_ms, ip, user_agent, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user, action, endpoint, method, status_code, duration_ms, ip, user_agent, detail),
            )
    except Exception:
        pass  # never crash the request for logging


def get_activity_log(limit: int = 100, user: str = None, action: str = None) -> list:
    """Get recent activity log entries."""
    with get_db() as conn:
        query = "SELECT * FROM activity_log WHERE 1=1"
        params = []
        if user:
            query += " AND user = ?"
            params.append(user)
        if action:
            query += " AND action LIKE ?"
            params.append(f"%{action}%")
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_activity_stats() -> dict:
    """Get activity log summary stats."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) cnt FROM activity_log").fetchone()['cnt']
        today = conn.execute("SELECT COUNT(*) cnt FROM activity_log WHERE timestamp >= datetime('now', '-1 day')").fetchone()['cnt']
        users = conn.execute("SELECT COUNT(DISTINCT user) cnt FROM activity_log WHERE user IS NOT NULL").fetchone()['cnt']
        slow = conn.execute("SELECT COUNT(*) cnt FROM activity_log WHERE duration_ms > 5000").fetchone()['cnt']
        return {'total_entries': total, 'last_24h': today, 'unique_users': users, 'slow_queries': slow}


# ── WOA Review Decisions ──────────────────────────────────────────────────────

def get_woa_review(woa_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT woa_id, status, note, reviewer, reviewed_at FROM woa_reviews WHERE woa_id = ?",
            (woa_id,),
        ).fetchone()
        return dict(row) if row else None


def set_woa_review(woa_id: str, status: str, note: str = '', reviewer: str = '') -> dict:
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO woa_reviews (woa_id, status, note, reviewer, reviewed_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (woa_id, status, note or '', reviewer or ''),
        )
    return {'woa_id': woa_id, 'status': status, 'note': note, 'reviewer': reviewer}


def get_woa_reviews_batch(woa_ids: list) -> dict:
    if not woa_ids:
        return {}
    placeholders = ','.join('?' * len(woa_ids))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT woa_id, status, note, reviewer, reviewed_at FROM woa_reviews WHERE woa_id IN ({placeholders})",
            woa_ids,
        ).fetchall()
    return {row['woa_id']: dict(row) for row in rows}


# ── Optimizer Sync Audit ──────────────────────────────────────────────────────

def write_sync_audit(
    started_at: str,
    finished_at: str,
    status: str,
    runs_found: int = 0,
    runs_inserted: int = 0,
    runs_skipped: int = 0,
    runs_failed: int = 0,
    verdicts_inserted: int = 0,
    rows_purged: int = 0,
    error_detail: str | None = None,
    duration_ms: int = 0,
):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO opt_sync_audit
               (started_at, finished_at, status, runs_found, runs_inserted,
                runs_skipped, runs_failed, verdicts_inserted, rows_purged,
                error_detail, duration_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (started_at, finished_at, status, runs_found, runs_inserted,
             runs_skipped, runs_failed, verdicts_inserted, rows_purged,
             error_detail, duration_ms)
        )


def get_sync_audit(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, started_at, finished_at, status, runs_found, runs_inserted,
                      runs_skipped, runs_failed, verdicts_inserted, rows_purged,
                      error_detail, duration_ms
               FROM opt_sync_audit
               ORDER BY id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
    return [dict(row) for row in rows]
