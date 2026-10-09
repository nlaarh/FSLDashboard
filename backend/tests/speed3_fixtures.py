"""Shared test fixtures for speed batch 3: a throwaway in-memory SQLite that holds the four new tables.
Never a real database: db_adapter is pointed at it for the length of one test."""

import sqlite3
from contextlib import contextmanager

import pytest


@pytest.fixture
def speed3_sqlite(monkeypatch):
    import db_adapter
    import speed3_db
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row

    @contextmanager
    def _conn():
        yield db_adapter._DbConn(conn, 'sqlite')

    monkeypatch.setattr('db_adapter.reader', _conn)
    monkeypatch.setattr('db_adapter.writer', _conn)
    monkeypatch.setattr(speed3_db, '_ready', set())
    assert all(speed3_db.ensure_schema(group) for group in speed3_db._GROUPS)
    yield conn
    conn.close()


def flags(monkeypatch, **on):
    """Switch speed batch 3 flags for one test without touching the settings table."""
    import feature_flags
    base = {k: False for k in ('replay_gps_store', 'daily_facts', 'revenue_semijoin')}
    base.update(on)
    monkeypatch.setattr(feature_flags, 'effective_features', lambda: dict(base))
