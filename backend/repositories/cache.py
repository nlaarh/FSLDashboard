import json
import logging
import time

import db_adapter

log = logging.getLogger("repo.cache")


def cache_get(key: str) -> str | None:
    """Get a cached value if not expired. Returns parsed JSON or None."""
    with db_adapter.reader() as db:
        row = db.execute(
            "SELECT data FROM cache WHERE key = %s AND expires_at > %s",
            (key, time.time()),
        ).fetchone()
        if row:
            try:
                return json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                return None
    return None


def cache_put(key: str, data: str, ttl: int = 300):
    """Store data in cache with TTL."""
    with db_adapter.writer() as db:
        db.execute(
            "INSERT INTO cache (key, data, expires_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, expires_at = EXCLUDED.expires_at",
            (key, json.dumps(data), time.time() + ttl),
        )


def cache_delete(key: str):
    """Delete a specific cache entry."""
    with db_adapter.writer() as db:
        db.execute("DELETE FROM cache WHERE key = %s", (key,))


def cache_delete_prefix(prefix: str) -> int:
    """Delete all cache entries matching a prefix. Returns count deleted."""
    with db_adapter.writer() as db:
        db.execute("DELETE FROM cache WHERE key LIKE %s", (f"{prefix}%",))
        return db.rowcount


def cache_get_meta(key: str) -> dict | None:
    """Get cache entry metadata (created_at, expires_at). Returns {} if not found."""
    with db_adapter.reader() as db:
        row = db.execute(
            "SELECT created_at, expires_at FROM cache WHERE key = %s", (key,)
        ).fetchone()
        if row:
            return {"created_at": row["created_at"], "expires_at": row["expires_at"]}
    return {}


def cache_delete_stale() -> int:
    """Remove expired cache entries. Returns count deleted."""
    with db_adapter.writer() as db:
        db.execute("DELETE FROM cache WHERE expires_at < %s", (time.time(),))
        db.commit()
        return db.rowcount


def cache_stats() -> dict:
    """Return cache statistics."""
    with db_adapter.reader() as db:
        total_row = db.execute("SELECT COUNT(*) AS cnt FROM cache").fetchone()
        alive_row = db.execute(
            "SELECT COUNT(*) AS cnt FROM cache WHERE expires_at > %s",
            (time.time(),),
        ).fetchone()
        total = total_row["cnt"] if total_row else 0
        alive = alive_row["cnt"] if alive_row else 0
        return {
            "total_keys": total,
            "alive": alive,
            "stale": total - alive,
        }
