"""SQLite database extensions — bonus tiers, accounting rates, watchlist, activity log, WOA reviews."""
import json
import time
import os
import logging
from pathlib import Path
from database import get_db

log = logging.getLogger('database')


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

    from database import get_setting, put_setting
    for key, value in settings.items():
        existing = get_setting(key)
        if existing is None:
            put_setting(key, value)
            log.info(f"Migrated setting: {key}")

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
