"""Unified database adapter — single interface for SQLite and Postgres.

Routers and repositories import `db_adapter` only.  This module decides
which backend to use based on the `DB_PRIMARY` env var (default: postgres).

Usage:
    with db_adapter.reader() as db:
        rows = db.execute("SELECT ...").fetchall()

    with db_adapter.writer() as db:
        db.execute("INSERT ...", params)

`db.execute()` accepts `%s` placeholders regardless of backend.
For SQLite the adapter transparently rewrites them to `?`.
"""

import os
import logging
from contextlib import contextmanager
from typing import Iterator

log = logging.getLogger("db_adapter")

_DB_PRIMARY = os.environ.get("DB_PRIMARY", "postgres")


# ── Connection wrappers ──────────────────────────────────────────────────────

class _DbConn:
    """Thin wrapper that normalises SQLite vs psycopg behaviour."""

    def __init__(self, raw_conn, backend: str):
        self._conn = raw_conn
        self.backend = backend
        self._cur = None

    # ── public API used by repositories ──────────────────────────────────────

    def execute(self, sql: str, params=()):
        """Run SQL.  Accepts `%s` placeholders on both backends."""
        if self.backend == "sqlite":
            sql = sql.replace("%s", "?")
        self._cur = self._conn.cursor()
        self._cur.execute(sql, params)
        return self

    def fetchall(self) -> list[dict]:
        if self._cur is None:
            return []
        if self.backend == "postgres":
            cols = [d[0] for d in self._cur.description] if self._cur.description else []
            return [dict(zip(cols, row)) for row in self._cur.fetchall()]
        # sqlite3.Row is already dict-like
        return [dict(r) for r in self._cur.fetchall()]

    def fetchone(self) -> dict | None:
        rows = self.fetchall()
        return rows[0] if rows else None

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def lastrowid(self) -> int | None:
        if self.backend == "sqlite":
            return self._cur.lastrowid if self._cur else None
        # Postgres: rely on RETURNING id instead
        return None

    @property
    def rowcount(self) -> int:
        if self._cur is None:
            return 0
        return self._cur.rowcount


# ── Readers / Writers ────────────────────────────────────────────────────────

@contextmanager
def reader() -> Iterator[_DbConn]:
    """Read-only connection — Postgres only."""
    import pg_pool
    with pg_pool.reader() as conn:
        conn.execute("SET search_path = core, public")
        yield _DbConn(conn, "postgres")


@contextmanager
def writer() -> Iterator[_DbConn]:
    """Read-write connection — Postgres only."""
    import pg_pool
    with pg_pool.writer() as conn:
        conn.execute("SET search_path = core, public")
        yield _DbConn(conn, "postgres")


def health_check() -> dict:
    """Quick connectivity test for Postgres."""
    result = {"primary": _DB_PRIMARY, "postgres": False}
    try:
        import pg_pool
        with pg_pool.reader() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        result["postgres"] = True
    except Exception as e:
        result["postgres_error"] = str(e)
    return result
