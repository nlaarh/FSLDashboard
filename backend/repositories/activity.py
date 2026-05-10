"""Activity log repository."""

import logging
from datetime import datetime, timedelta, timezone

import db_adapter

log = logging.getLogger("repo.activity")


def log_activity(
    user: str = None,
    action: str = "",
    endpoint: str = None,
    method: str = "GET",
    status_code: int = None,
    duration_ms: float = None,
    ip: str = None,
    user_agent: str = None,
    detail: str = None,
):
    """Log an activity event. Fire-and-forget — never raises."""
    try:
        with db_adapter.writer() as db:
            db.execute(
                """
                INSERT INTO activity_log ("user", action, endpoint, method, status_code, duration_ms, ip, user_agent, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (user, action, endpoint, method, status_code, duration_ms, ip, user_agent, detail),
            )
    except Exception:
        log.exception("Failed to log activity")


def get_activity_log(limit: int = 100, user: str = None, action: str = None) -> list[dict]:
    """Get recent activity log entries."""
    with db_adapter.reader() as db:
        query = "SELECT * FROM activity_log WHERE 1=1"
        params = []
        if user:
            query += ' AND "user" = %s'
            params.append(user)
        if action:
            query += " AND action LIKE %s"
            params.append(f"%{action}%")
        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        db.execute(query, params)
        rows = db.fetchall()
    return rows


def clear_activity_log() -> int:
    """Delete all activity log entries. Returns number of rows deleted."""
    with db_adapter.writer() as db:
        db.execute("DELETE FROM activity_log")
        db.commit()
        return db.rowcount


def get_activity_stats() -> dict:
    """Get activity log summary stats."""
    threshold = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

    with db_adapter.reader() as db:
        db.execute("SELECT COUNT(*) cnt FROM activity_log")
        total = db.fetchone()["cnt"]

        db.execute("SELECT COUNT(*) cnt FROM activity_log WHERE timestamp >= %s", (threshold,))
        today = db.fetchone()["cnt"]

        db.execute('SELECT COUNT(DISTINCT "user") cnt FROM activity_log WHERE "user" IS NOT NULL')
        users = db.fetchone()["cnt"]

        db.execute("SELECT COUNT(*) cnt FROM activity_log WHERE duration_ms > %s", (5000,))
        slow = db.fetchone()["cnt"]

    return {
        "total_entries": total,
        "last_24h": today,
        "unique_users": users,
        "slow_queries": slow,
    }
