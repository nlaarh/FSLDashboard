"""Persistent user session tracking for online status and current-month adoption."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import db_adapter

log = logging.getLogger("repo.user_sessions")

SESSION_TTL_SECONDS = 36000  # 10 hours from login


def _month_start_ts(now: float | None = None) -> float:
    dt = datetime.fromtimestamp(now or time.time(), timezone.utc)
    return datetime(dt.year, dt.month, 1, tzinfo=timezone.utc).timestamp()


def _ensure_table() -> None:
    with db_adapter.writer() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                name TEXT DEFAULT '',
                role TEXT DEFAULT '',
                department TEXT DEFAULT '',
                login_time REAL NOT NULL,
                last_seen REAL NOT NULL,
                logout_time REAL,
                expires_at REAL NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_username ON user_sessions(username)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_login ON user_sessions(login_time)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_active ON user_sessions(logout_time, expires_at)")
        db.commit()


def purge_before_current_month(now: float | None = None) -> None:
    """Keep only the current month of session data."""
    try:
        _ensure_table()
        cutoff = _month_start_ts(now)
        with db_adapter.writer() as db:
            db.execute(
                "DELETE FROM user_sessions WHERE COALESCE(logout_time, expires_at) < %s",
                (cutoff,),
            )
            db.commit()
    except Exception:
        log.exception("Failed to purge old user sessions")


def record_login(token: str, username: str, name: str, role: str, department: str = "") -> None:
    try:
        _ensure_table()
        now = time.time()
        with db_adapter.writer() as db:
            db.execute(
                """
                INSERT INTO user_sessions
                    (token, username, name, role, department, login_time, last_seen, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (token, username, name, role, department, now, now, now + SESSION_TTL_SECONDS),
            )
            db.commit()
        purge_before_current_month(now)
    except Exception:
        log.exception("Failed to record user login")


def get_session(token: str) -> dict | None:
    try:
        _ensure_table()
        now = time.time()
        with db_adapter.reader() as db:
            db.execute(
                """
                SELECT token, username, name, role, department, login_time, last_seen, logout_time, expires_at
                FROM user_sessions
                WHERE token = %s AND logout_time IS NULL AND expires_at > %s
                """,
                (token, now),
            )
            return db.fetchone()
    except Exception:
        log.exception("Failed to get persistent session")
        return None


def touch_session(token: str) -> None:
    try:
        _ensure_table()
        now = time.time()
        with db_adapter.writer() as db:
            db.execute(
                """UPDATE user_sessions
                   SET last_seen = %s, expires_at = %s
                   WHERE token = %s AND logout_time IS NULL""",
                (now, now + SESSION_TTL_SECONDS, token),
            )
            db.commit()
    except Exception:
        log.exception("Failed to touch persistent session")


def close_session(token: str) -> None:
    try:
        _ensure_table()
        now = time.time()
        with db_adapter.writer() as db:
            db.execute(
                "UPDATE user_sessions SET logout_time = %s, last_seen = %s WHERE token = %s AND logout_time IS NULL",
                (now, now, token),
            )
            db.commit()
    except Exception:
        log.exception("Failed to close persistent session")


def list_active_sessions() -> list[dict]:
    try:
        _ensure_table()
        now = time.time()
        with db_adapter.reader() as db:
            db.execute(
                """
                SELECT username, name, role, department, login_time, last_seen
                FROM (
                    SELECT
                        username, name, role, department, login_time, last_seen,
                        ROW_NUMBER() OVER (PARTITION BY username ORDER BY last_seen DESC) AS rn
                    FROM user_sessions
                    WHERE logout_time IS NULL AND expires_at > %s
                ) active_sessions
                WHERE rn = 1
                ORDER BY last_seen DESC
                """,
                (now,),
            )
            rows = db.fetchall()
        return sorted(
            [
                {
                    "user": row["username"],
                    "name": row.get("name") or row["username"],
                    "role": row.get("role") or "",
                    "department": row.get("department") or "",
                    "login_time": row["login_time"],
                    "last_seen": row["last_seen"],
                    "idle_min": round((now - row["last_seen"]) / 60),
                }
                for row in rows
            ],
            key=lambda x: x["last_seen"],
            reverse=True,
        )
    except Exception:
        log.exception("Failed to list active user sessions")
        return []


def adoption_report(user_rows: list[dict]) -> dict:
    """Return all users with current-month login status and time-in-system."""
    _ensure_table()
    now = time.time()
    month_start = _month_start_ts(now)
    with db_adapter.reader() as db:
        db.execute(
            """
            SELECT username, login_time, last_seen, logout_time, expires_at
            FROM user_sessions
            WHERE login_time >= %s OR COALESCE(logout_time, expires_at) >= %s
            """,
            (month_start, month_start),
        )
        sessions = db.fetchall()

    by_user: dict[str, dict] = {}
    for row in user_rows:
        by_user[row["username"]] = {
            "username": row["username"],
            "name": row.get("name") or row["username"],
            "role": row.get("role") or "",
            "department": row.get("department") or "",
            "active": bool(row.get("active", True)),
            "status": "not_logged_in",
            "last_login": None,
            "last_seen": None,
            "active_since": None,
            "session_count": 0,
            "minutes_this_month": 0,
            "sf_last_login": row.get("sf_last_login"),
        }

    for sess in sessions:
        username = sess["username"]
        if username not in by_user:
            continue
        item = by_user[username]
        login_time = float(sess["login_time"])
        logout_time = sess.get("logout_time")
        expires_at = float(sess["expires_at"])
        end_time = float(logout_time) if logout_time is not None else min(now, expires_at)
        start_time = max(login_time, month_start)
        if end_time > start_time:
            item["minutes_this_month"] += round((end_time - start_time) / 60)
        item["session_count"] += 1
        if item["last_login"] is None or login_time > item["last_login"]:
            item["last_login"] = login_time
        if sess.get("last_seen") and (item["last_seen"] is None or sess["last_seen"] > item["last_seen"]):
            item["last_seen"] = sess["last_seen"]
        if logout_time is None and expires_at > now:
            item["status"] = "logged_in"
            if item["active_since"] is None or login_time < item["active_since"]:
                item["active_since"] = login_time

    rows = sorted(by_user.values(), key=lambda r: (r["status"] != "logged_in", r["name"].lower()))
    return {
        "month_start": month_start,
        "generated_at": now,
        "rows": rows,
    }
