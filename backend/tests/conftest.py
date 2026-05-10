"""Shared test infrastructure — pg_pool mock, helpers, and fixtures."""
from __future__ import annotations

import importlib
import sqlite3
import sys
import time
from contextlib import contextmanager
from unittest.mock import MagicMock

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Module-level pg_pool mock (must run before any test module imports core_users) ──
_fake_pg_pool = MagicMock()
_fake_pg_pool.rows_as_dicts = MagicMock(
    side_effect=lambda cur: [
        dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()
    ]
)


def _make_mock_conn(rows=None, fetchone=None):
    """Build a mock psycopg connection + cursor."""
    conn = MagicMock()
    cur = MagicMock()
    if rows is not None:
        cur.fetchall.return_value = [tuple(r.values()) for r in rows]
        cur.description = [(k,) for k in (rows[0].keys() if rows else [])]
    if fetchone is not None:
        cur.fetchone.return_value = tuple(fetchone.values())
        cur.description = [(k,) for k in fetchone.keys()]
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.commit = MagicMock()
    return conn, cur


@contextmanager
def _default_reader():
    conn, _ = _make_mock_conn()
    yield conn


@contextmanager
def _default_writer():
    conn, _ = _make_mock_conn()
    yield conn


_fake_pg_pool.reader = _default_reader
_fake_pg_pool.writer = _default_writer
sys.modules["pg_pool"] = _fake_pg_pool

if "core_users" in sys.modules:
    importlib.reload(sys.modules["core_users"])


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sqlite_db(monkeypatch):
    """In-memory SQLite database with users and password_reset_tokens tables.
    Also routes db_adapter (used by repositories) to SQLite so all repo calls
    hit the in-memory DB without touching Postgres."""
    import db_adapter
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE users (
            username TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'viewer',
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at REAL,
            department TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE password_reset_tokens (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            pin TEXT NOT NULL,
            expires_at REAL NOT NULL,
            validated INTEGER DEFAULT 0,
            validation_token TEXT,
            validation_expires_at REAL,
            attempts INTEGER DEFAULT 0,
            created_at REAL DEFAULT (strftime('%s', 'now'))
        )
        """
    )
    conn.commit()

    @contextmanager
    def fake_get_db():
        yield conn

    @contextmanager
    def _sqlite_reader():
        yield db_adapter._DbConn(conn, "sqlite")

    @contextmanager
    def _sqlite_writer():
        yield db_adapter._DbConn(conn, "sqlite")

    monkeypatch.setattr("database.get_db", fake_get_db)
    monkeypatch.setattr("db_adapter.reader", _sqlite_reader)
    monkeypatch.setattr("db_adapter.writer", _sqlite_writer)
    yield conn
    conn.close()


@pytest.fixture
def admin_client(monkeypatch):
    from routers import admin

    monkeypatch.setattr(admin, "_ADMIN_PIN", "1234")
    app = FastAPI()
    app.include_router(admin.router)
    return TestClient(app)


@pytest.fixture
def auth_client(monkeypatch, sqlite_db):
    from routers import auth

    monkeypatch.setattr(auth, "_AUTH_SECRET", "testsecret")
    monkeypatch.setattr("users._sessions", {})
    app = FastAPI()
    app.include_router(auth.router)
    return TestClient(app), sqlite_db


@pytest.fixture
def reset_client(monkeypatch, sqlite_db):
    from routers import password_reset as pr
    import repositories.password_reset as pr_repo

    monkeypatch.setattr(pr, "_TURNSTILE_SECRET_KEY", "")
    monkeypatch.setattr(pr, "_AGENTMAIL_API_KEY", "")
    monkeypatch.setattr(pr, "_AGENTMAIL_INBOX", "test@example.com")
    monkeypatch.setattr(pr, "_ADMIN_NOTIFY_EMAIL", "admin@example.com")

    def _create_token(token, username, email, pin, expires_at):
        sqlite_db.execute(
            "INSERT INTO password_reset_tokens (token, username, email, pin, expires_at) VALUES (?, ?, ?, ?, ?)",
            (token, username, email, pin, expires_at),
        )
        sqlite_db.commit()

    def _get_token(token):
        row = sqlite_db.execute(
            "SELECT token, username, email, pin, expires_at, validated, validation_token, validation_expires_at, attempts, created_at FROM password_reset_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _get_token_by_validation(validation_token):
        row = sqlite_db.execute(
            "SELECT token, username, email, pin, expires_at, validated, validation_token, validation_expires_at, attempts, created_at FROM password_reset_tokens WHERE validation_token = ?",
            (validation_token,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _increment_attempts(token):
        sqlite_db.execute(
            "UPDATE password_reset_tokens SET attempts = attempts + 1 WHERE token = ?",
            (token,),
        )
        sqlite_db.commit()

    def _validate_token(token, validation_token, validation_expires_at):
        sqlite_db.execute(
            "UPDATE password_reset_tokens SET validated = 1, validation_token = ?, validation_expires_at = ? WHERE token = ?",
            (validation_token, validation_expires_at, token),
        )
        sqlite_db.commit()

    def _delete_token(token):
        sqlite_db.execute("DELETE FROM password_reset_tokens WHERE token = ?", (token,))
        sqlite_db.commit()

    def _delete_tokens_by_username(username):
        sqlite_db.execute("DELETE FROM password_reset_tokens WHERE username = ?", (username,))
        sqlite_db.commit()

    def _cleanup_expired_tokens():
        sqlite_db.execute("DELETE FROM password_reset_tokens WHERE expires_at < ?", (time.time(),))
        sqlite_db.commit()

    monkeypatch.setattr(pr_repo, "create_token", _create_token)
    monkeypatch.setattr(pr_repo, "get_token", _get_token)
    monkeypatch.setattr(pr_repo, "get_token_by_validation", _get_token_by_validation)
    monkeypatch.setattr(pr_repo, "increment_attempts", _increment_attempts)
    monkeypatch.setattr(pr_repo, "validate_token", _validate_token)
    monkeypatch.setattr(pr_repo, "delete_token", _delete_token)
    monkeypatch.setattr(pr_repo, "delete_tokens_by_username", _delete_tokens_by_username)
    monkeypatch.setattr(pr_repo, "cleanup_expired_tokens", _cleanup_expired_tokens)

    app = FastAPI()
    app.include_router(pr.router)
    return TestClient(app), sqlite_db
