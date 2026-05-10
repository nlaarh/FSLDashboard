"""Tests for user migration from SQLite to PostgreSQL.

Covers:
  - Postgres CRUD (core_users.py)
  - Dual-run mode (users.py)
  - users.py public API
  - Admin endpoints
  - Auth flow
  - Password reset flow
"""

from __future__ import annotations

import hashlib
import hmac
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


# ── Module-level pg_pool mock (must run before core_users is imported) ───────
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


# ── Fixtures ─────────────────────────────────────────────────────────────────


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

    # Monkeypatch password_reset repository to use SQLite (with ? placeholders)
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
        if row is None:
            return None
        return dict(row)

    def _get_token_by_validation(validation_token):
        row = sqlite_db.execute(
            "SELECT token, username, email, pin, expires_at, validated, validation_token, validation_expires_at, attempts, created_at FROM password_reset_tokens WHERE validation_token = ?",
            (validation_token,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

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


# ── 1. core_users.py interface ───────────────────────────────────────────────


class TestCoreUsers:
    def test_functions_exist_and_callable(self):
        import core_users

        assert callable(core_users.get_user)
        assert callable(core_users.get_user_with_hash)
        assert callable(core_users.find_by_email)
        assert callable(core_users.list_users)
        assert callable(core_users.create_user)
        assert callable(core_users.update_user)
        assert callable(core_users.update_password_hash)
        assert callable(core_users.delete_user)
        assert callable(core_users.restore_user)

    def test_get_user_returns_correct_shape(self, monkeypatch):
        import core_users

        row = {
            "username": "alice",
            "name": "Alice",
            "role": "admin",
            "email": "alice@example.com",
            "phone": "555-1234",
            "password_hash": "h",
            "salt": "s",
            "active": 1,
            "created_at": 1.0,
            "department": "executive",
        }
        conn, cur = _make_mock_conn(rows=[row])

        @contextmanager
        def fake_reader():
            yield conn

        monkeypatch.setattr("pg_pool.reader", fake_reader)
        user = core_users.get_user("alice")
        assert user == {
            "username": "alice",
            "name": "Alice",
            "role": "admin",
            "email": "alice@example.com",
            "active": True,
            "department": "executive",
        }

    def test_get_user_with_hash_includes_password_fields(self, monkeypatch):
        import core_users

        row = {
            "username": "alice",
            "name": "Alice",
            "role": "admin",
            "email": "alice@example.com",
            "phone": "",
            "password_hash": "h",
            "salt": "s",
            "active": 1,
            "created_at": 1.0,
            "department": "",
        }
        conn, cur = _make_mock_conn(rows=[row])

        @contextmanager
        def fake_reader():
            yield conn

        monkeypatch.setattr("pg_pool.reader", fake_reader)
        result = core_users.get_user_with_hash("alice")
        assert result is not None
        assert result["password_hash"] == "h"
        assert result["salt"] == "s"

    def test_find_by_email_is_case_insensitive(self, monkeypatch):
        import core_users

        row = {
            "username": "alice",
            "name": "Alice",
            "role": "admin",
            "email": "Alice@Example.COM",
            "phone": "",
            "password_hash": "h",
            "salt": "s",
            "active": 1,
            "created_at": 1.0,
            "department": "",
        }
        conn, cur = _make_mock_conn(rows=[row])

        @contextmanager
        def fake_reader():
            yield conn

        monkeypatch.setattr("pg_pool.reader", fake_reader)
        assert core_users.find_by_email("alice@example.com") is not None
        assert core_users.find_by_email("ALICE@EXAMPLE.COM") is not None

    def test_list_users_returns_all(self, monkeypatch):
        import core_users

        rows = [
            {
                "username": "alice",
                "name": "Alice",
                "role": "admin",
                "email": "",
                "phone": "",
                "password_hash": "h",
                "salt": "s",
                "active": 1,
                "created_at": 1.0,
                "department": "",
            },
            {
                "username": "bob",
                "name": "Bob",
                "role": "viewer",
                "email": "",
                "phone": "",
                "password_hash": "h",
                "salt": "s",
                "active": 0,
                "created_at": 2.0,
                "department": "",
            },
        ]
        conn, cur = _make_mock_conn(rows=rows)

        @contextmanager
        def fake_reader():
            yield conn

        monkeypatch.setattr("pg_pool.reader", fake_reader)
        users = core_users.list_users()
        assert len(users) == 2
        assert users[0]["username"] == "alice"
        assert users[1]["active"] is False

    def test_create_user_inserts_row(self, monkeypatch):
        import core_users

        conn, cur = _make_mock_conn()

        @contextmanager
        def fake_writer():
            yield conn

        monkeypatch.setattr("pg_pool.writer", fake_writer)
        core_users.create_user(
            "carol", "Carol", "manager", "c@example.com", "", "h", "s", 1, 1.0, "ers"
        )
        cur = conn.cursor.return_value.__enter__.return_value
        assert cur.execute.called
        calls = [c[0][0] for c in cur.execute.call_args_list]
        assert any("INSERT INTO users" in sql for sql in calls)

    def test_update_user_updates_fields(self, monkeypatch):
        import core_users

        existing = {
            "username": "alice",
            "name": "Alice",
            "role": "admin",
            "email": "",
            "phone": "",
            "password_hash": "h",
            "salt": "s",
            "active": 1,
            "created_at": 1.0,
            "department": "",
        }
        conn, cur = _make_mock_conn(rows=[existing])

        @contextmanager
        def fake_writer():
            yield conn

        @contextmanager
        def fake_reader():
            yield conn

        monkeypatch.setattr("pg_pool.writer", fake_writer)
        monkeypatch.setattr("pg_pool.reader", fake_reader)
        result = core_users.update_user("alice", name="Alice Smith", role="superadmin")
        # Mock doesn't persist changes; verify UPDATE was issued with correct params
        cursor = conn.cursor.return_value.__enter__.return_value
        calls = [c[0] for c in cursor.execute.call_args_list]
        update_calls = [c for c in calls if "UPDATE users" in c[0]]
        assert len(update_calls) > 0
        params = update_calls[0][1]
        assert "Alice Smith" in params
        assert "superadmin" in params
        # Result shape should be a dict
        assert isinstance(result, dict)
        assert result["username"] == "alice"

    def test_update_user_with_password_uses_bcrypt(self, monkeypatch):
        import core_users

        existing = {
            "username": "alice",
            "name": "Alice",
            "role": "admin",
            "email": "",
            "phone": "",
            "password_hash": "oldhash",
            "salt": "oldsalt",
            "active": 1,
            "created_at": 1.0,
            "department": "",
        }
        conn, cur = _make_mock_conn(rows=[existing])

        @contextmanager
        def fake_writer():
            yield conn

        @contextmanager
        def fake_reader():
            yield conn

        monkeypatch.setattr("pg_pool.writer", fake_writer)
        monkeypatch.setattr("pg_pool.reader", fake_reader)
        result = core_users.update_user("alice", password="NewPass123!")
        cur = conn.cursor.return_value.__enter__.return_value
        calls = [c[0] for c in cur.execute.call_args_list]
        update_calls = [c for c in calls if "UPDATE users" in c[0]]
        assert len(update_calls) > 0
        params = update_calls[0][1]
        assert any(isinstance(p, str) and p.startswith("$2b$") for p in params)

    def test_update_password_hash_direct(self, monkeypatch):
        import core_users

        existing = {
            "username": "alice",
            "name": "Alice",
            "role": "admin",
            "email": "",
            "phone": "",
            "password_hash": "oldhash",
            "salt": "oldsalt",
            "active": 1,
            "created_at": 1.0,
            "department": "",
        }
        conn, cur = _make_mock_conn(rows=[existing])

        @contextmanager
        def fake_writer():
            yield conn

        monkeypatch.setattr("pg_pool.writer", fake_writer)
        core_users.update_password_hash("alice", "newhash", "bcrypt")
        cur = conn.cursor.return_value.__enter__.return_value
        calls = [c[0] for c in cur.execute.call_args_list]
        update_calls = [c for c in calls if "UPDATE users" in c[0]]
        assert len(update_calls) > 0
        params = update_calls[0][1]
        assert "newhash" in params
        assert "bcrypt" in params

    def test_delete_user_sets_active_zero(self, monkeypatch):
        import core_users

        existing = {
            "username": "alice",
            "name": "Alice",
            "role": "admin",
            "email": "",
            "phone": "",
            "password_hash": "h",
            "salt": "s",
            "active": 1,
            "created_at": 1.0,
            "department": "",
        }
        conn, cur = _make_mock_conn(rows=[existing])

        @contextmanager
        def fake_writer():
            yield conn

        monkeypatch.setattr("pg_pool.writer", fake_writer)
        monkeypatch.setattr("pg_pool.reader", fake_writer)
        core_users.delete_user("alice")
        cur = conn.cursor.return_value.__enter__.return_value
        calls = [c[0] for c in cur.execute.call_args_list]
        update_calls = [c for c in calls if "UPDATE users" in c[0]]
        assert any(
            "active = %s" in c[0] and c[1][0] == 0 for c in update_calls
        )

    def test_restore_user_sets_active_one(self, monkeypatch):
        import core_users

        existing = {
            "username": "alice",
            "name": "Alice",
            "role": "admin",
            "email": "",
            "phone": "",
            "password_hash": "h",
            "salt": "s",
            "active": 0,
            "created_at": 1.0,
            "department": "",
        }
        conn, cur = _make_mock_conn(rows=[existing])

        @contextmanager
        def fake_writer():
            yield conn

        monkeypatch.setattr("pg_pool.writer", fake_writer)
        monkeypatch.setattr("pg_pool.reader", fake_writer)
        result = core_users.restore_user("alice")
        # Mock doesn't persist changes; verify UPDATE was issued
        cursor = conn.cursor.return_value.__enter__.return_value
        calls = [c[0] for c in cursor.execute.call_args_list]
        update_calls = [c for c in calls if "UPDATE users" in c[0]]
        assert any(
            "active = %s" in c[0] and c[1][0] == 1 for c in update_calls
        )
        assert isinstance(result, dict)
        assert result["username"] == "alice"


# ── 2. users.py dual-run toggle ──────────────────────────────────────────────


# ── 3. users.py public API ───────────────────────────────────────────────────


class TestUsersPublicApi:
    def _seed_user(self, sqlite_db, username, password, role="viewer", active=1, email=""):
        h = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
        sqlite_db.execute(
            "INSERT INTO users (username, name, role, email, phone, password_hash, salt, active, created_at, department) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (username, username.title(), role, email, "", h, "bcrypt", active, time.time(), ""),
        )
        sqlite_db.commit()
        return h

    def test_authenticate_with_bcrypt(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "Secret123!", role="admin")
        result = users_mod.authenticate("alice", "Secret123!")
        assert result is not None
        assert result["username"] == "alice"
        assert result["role"] == "admin"

    def test_authenticate_wrong_password(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "Secret123!")
        result = users_mod.authenticate("alice", "wrongpassword")
        assert result is None

    def test_authenticate_inactive_user(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "Secret123!", active=0)
        result = users_mod.authenticate("alice", "Secret123!")
        assert result is None

    def test_get_user(self, monkeypatch, sqlite_db):
        import users as users_mod

        self._seed_user(sqlite_db, "alice", "Secret123!", role="admin", email="alice@example.com")
        user = users_mod.get_user("alice")
        assert user is not None
        assert user["username"] == "alice"
        assert user["name"] == "Alice"
        assert user["role"] == "admin"
        assert user["email"] == "alice@example.com"
        assert user["active"] is True

    def test_get_user_missing(self, monkeypatch, sqlite_db):
        import users as users_mod

        user = users_mod.get_user("nobody")
        assert user is None

    def test_list_users(self, monkeypatch, sqlite_db):
        import users as users_mod

        self._seed_user(sqlite_db, "alice", "pass1", role="admin")
        self._seed_user(sqlite_db, "bob", "pass2", role="viewer")
        users = users_mod.list_users()
        assert isinstance(users, list)
        assert len(users) == 2
        usernames = [u["username"] for u in users]
        assert "alice" in usernames
        assert "bob" in usernames

    def test_create_user(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        result = users_mod.create_user(
            "carol", "Secret123!", "Carol", role="manager", email="c@example.com"
        )
        assert result["username"] == "carol"
        assert result["name"] == "Carol"
        assert result["role"] == "manager"
        assert result["email"] == "c@example.com"
        row = sqlite_db.execute(
            "SELECT * FROM users WHERE username = ?", ("carol",)
        ).fetchone()
        assert row is not None
        assert row["active"] == 1

    def test_create_user_duplicate_raises(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        users_mod.create_user("carol", "Secret123!", "Carol")
        with pytest.raises(ValueError, match="already exists"):
            users_mod.create_user("carol", "Secret123!", "Carol")

    def test_update_user_fields(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "Secret123!")
        result = users_mod.update_user(
            "alice", name="Alice Smith", role="superadmin", email="alice@new.com"
        )
        assert result["name"] == "Alice Smith"
        assert result["role"] == "superadmin"
        assert result["email"] == "alice@new.com"

    def test_update_user_password(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "OldPass123!")
        result = users_mod.update_user("alice", password="NewPass123!")
        assert result is not None
        auth = users_mod.authenticate("alice", "NewPass123!")
        assert auth is not None
        auth_old = users_mod.authenticate("alice", "OldPass123!")
        assert auth_old is None

    def test_delete_user_soft_deletes(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "Secret123!")
        users_mod.delete_user("alice")
        row = sqlite_db.execute(
            "SELECT active FROM users WHERE username = ?", ("alice",)
        ).fetchone()
        assert row["active"] == 0

    def test_delete_user_invalidates_sessions(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "Secret123!", role="admin")
        token = users_mod.create_session("alice", "admin", "Alice")
        monkeypatch.setattr(
            users_mod, "_sessions", {token: {"user": "alice", "role": "admin", "name": "Alice"}}
        )
        users_mod.delete_user("alice")
        assert token not in users_mod._sessions

    def test_restore_user_reactivates(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "Secret123!")
        sqlite_db.execute("UPDATE users SET active = 0 WHERE username = ?", ("alice",))
        sqlite_db.commit()
        result = users_mod.restore_user("alice")
        assert result["active"] is True
        row = sqlite_db.execute(
            "SELECT active FROM users WHERE username = ?", ("alice",)
        ).fetchone()
        assert row["active"] == 1

    def test_check_password_against_user_true(self, monkeypatch, sqlite_db):
        import users as users_mod

        self._seed_user(sqlite_db, "alice", "Secret123!")
        assert users_mod.check_password_against_user("alice", "Secret123!") is True

    def test_check_password_against_user_false(self, monkeypatch, sqlite_db):
        import users as users_mod

        self._seed_user(sqlite_db, "alice", "Secret123!")
        assert users_mod.check_password_against_user("alice", "wrongpassword") is False

    def test_find_by_email(self, monkeypatch, sqlite_db):
        import users as users_mod

        self._seed_user(sqlite_db, "alice", "pass", email="Alice@Example.COM")
        result = users_mod.find_by_email("alice@example.com")
        assert result is not None
        assert result["username"] == "alice"


# ── 4. Admin router ──────────────────────────────────────────────────────────


class TestAdminEndpoints:
    def test_get_users_lists_all(self, admin_client, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        h = bcrypt.hashpw("pass".encode(), bcrypt.gensalt(rounds=12)).decode()
        sqlite_db.execute(
            "INSERT INTO users (username, name, role, email, phone, password_hash, salt, active, created_at, department) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("alice", "Alice", "admin", "", "", h, "bcrypt", 1, time.time(), ""),
        )
        sqlite_db.commit()
        r = admin_client.get("/api/admin/users", headers={"X-Admin-Pin": "1234"})
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["username"] == "alice"

    def test_post_users_creates_user(self, admin_client, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        r = admin_client.post(
            "/api/admin/users",
            headers={"X-Admin-Pin": "1234"},
            json={
                "username": "bob",
                "name": "Bob",
                "password": "ValidPass123!",
                "role": "viewer",
                "email": "bob@example.com",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "bob"
        row = sqlite_db.execute(
            "SELECT * FROM users WHERE username = ?", ("bob",)
        ).fetchone()
        assert row is not None
        assert row["active"] == 1

    def test_put_users_updates_user(self, admin_client, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        h = bcrypt.hashpw("OldPass123!".encode(), bcrypt.gensalt(rounds=12)).decode()
        sqlite_db.execute(
            "INSERT INTO users (username, name, role, email, phone, password_hash, salt, active, created_at, department) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("alice", "Alice", "admin", "", "", h, "bcrypt", 1, time.time(), ""),
        )
        sqlite_db.commit()
        r = admin_client.put(
            "/api/admin/users/alice",
            headers={"X-Admin-Pin": "1234"},
            json={"name": "Alice Smith", "password": "NewPass1234!"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Alice Smith"
        assert users_mod.authenticate("alice", "NewPass1234!") is not None

    def test_delete_users_soft_deletes(self, admin_client, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        h = bcrypt.hashpw("pass".encode(), bcrypt.gensalt(rounds=12)).decode()
        sqlite_db.execute(
            "INSERT INTO users (username, name, role, email, phone, password_hash, salt, active, created_at, department) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("alice", "Alice", "admin", "", "", h, "bcrypt", 1, time.time(), ""),
        )
        sqlite_db.commit()
        r = admin_client.delete("/api/admin/users/alice", headers={"X-Admin-Pin": "1234"})
        assert r.status_code == 200
        row = sqlite_db.execute(
            "SELECT active FROM users WHERE username = ?", ("alice",)
        ).fetchone()
        assert row["active"] == 0

    def test_restore_user_reactivates(self, admin_client, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        h = bcrypt.hashpw("pass".encode(), bcrypt.gensalt(rounds=12)).decode()
        sqlite_db.execute(
            "INSERT INTO users (username, name, role, email, phone, password_hash, salt, active, created_at, department) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("alice", "Alice", "admin", "", "", h, "bcrypt", 0, time.time(), ""),
        )
        sqlite_db.commit()
        r = admin_client.post(
            "/api/admin/users/alice/restore", headers={"X-Admin-Pin": "1234"}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["user"]["active"] is True
        row = sqlite_db.execute(
            "SELECT active FROM users WHERE username = ?", ("alice",)
        ).fetchone()
        assert row["active"] == 1

    def test_restore_missing_endpoint_shape(self, admin_client, monkeypatch):
        """Restore-missing now calls Azure Blob backup. Just verify shape."""
        import db_backup

        monkeypatch.setattr(db_backup, "restore_latest", lambda: True)
        r = admin_client.post(
            "/api/admin/users/restore-missing", headers={"X-Admin-Pin": "1234"}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "source" in data


# ── 5. Auth router ───────────────────────────────────────────────────────────


class TestAuthFlow:
    def _seed_user(self, sqlite_db, username, password, role="viewer"):
        h = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
        sqlite_db.execute(
            "INSERT INTO users (username, name, role, email, phone, password_hash, salt, active, created_at, department) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (username, username.title(), role, "", "", h, "bcrypt", 1, time.time(), ""),
        )
        sqlite_db.commit()

    def test_login_correct_password_sets_cookie(self, auth_client, monkeypatch, sqlite_db):
        client, _ = auth_client
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "Secret123!", role="admin")
        r = client.post(
            "/api/auth/login", json={"username": "alice", "password": "Secret123!"}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["user"] == "alice"
        assert data["role"] == "admin"
        # Cookie should be set
        assert "fslapp_auth" in r.cookies or any(
            "fslapp_auth" in str(v) for v in r.headers.values()
        )

    def test_login_wrong_password(self, auth_client, monkeypatch, sqlite_db):
        client, _ = auth_client
        import users as users_mod

        self._seed_user(sqlite_db, "alice", "Secret123!")
        r = client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong"}
        )
        assert r.status_code == 401

    def test_me_returns_current_user(self, auth_client, monkeypatch, sqlite_db):
        client, _ = auth_client
        import users as users_mod
        import routers.auth as auth_mod

        self._seed_user(sqlite_db, "alice", "Secret123!", role="admin")
        token = users_mod.create_session("alice", "admin", "Alice")
        payload = f"alice:admin:{token}"
        sig = hmac.new(
            auth_mod._AUTH_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        cookie = f"{payload}.{sig}"
        r = client.get("/api/auth/me", cookies={"fslapp_auth": cookie})
        assert r.status_code == 200
        data = r.json()
        assert data["user"] == "alice"
        assert data["role"] == "admin"
        assert data["method"] == "admin"

    def test_me_without_cookie_returns_dev(self, auth_client):
        client, _ = auth_client
        r = client.get("/api/auth/me")
        # Dev auto-login is disabled by default; expect 401
        assert r.status_code == 401


# ── 6. Password reset flow ───────────────────────────────────────────────────


class TestPasswordReset:
    def _seed_user(self, sqlite_db, username, password, email, role="viewer"):
        h = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
        sqlite_db.execute(
            "INSERT INTO users (username, name, role, email, phone, password_hash, salt, active, created_at, department) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (username, username.title(), role, email, "", h, "bcrypt", 1, time.time(), ""),
        )
        sqlite_db.commit()

    def test_forgot_password_generates_token_and_pin(self, reset_client, monkeypatch, sqlite_db):
        client, _ = reset_client
        import users as users_mod

        self._seed_user(sqlite_db, "alice", "Secret123!", "alice@example.com", role="admin")
        r = client.post(
            "/api/auth/forgot-password",
            json={"email": "alice@example.com", "website": "", "turnstile": ""},
        )
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data
        row = sqlite_db.execute(
            "SELECT * FROM password_reset_tokens WHERE email = ?", ("alice@example.com",)
        ).fetchone()
        assert row is not None
        assert len(row["pin"]) == 6
        assert row["token"] is not None

    def test_verify_reset_pin_validates_pin(self, reset_client, monkeypatch, sqlite_db):
        client, _ = reset_client
        import users as users_mod

        self._seed_user(sqlite_db, "alice", "Secret123!", "alice@example.com")
        client.post(
            "/api/auth/forgot-password",
            json={"email": "alice@example.com", "website": "", "turnstile": ""},
        )
        row = sqlite_db.execute(
            "SELECT * FROM password_reset_tokens WHERE email = ?", ("alice@example.com",)
        ).fetchone()
        token = row["token"]
        pin = row["pin"]

        r = client.post("/api/auth/verify-reset-pin", json={"token": token, "pin": pin})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "validation_token" in data

    def test_reset_password_updates_hash(self, reset_client, monkeypatch, sqlite_db):
        client, _ = reset_client
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "OldPass123!", "alice@example.com")

        client.post(
            "/api/auth/forgot-password",
            json={"email": "alice@example.com", "website": "", "turnstile": ""},
        )
        row = sqlite_db.execute(
            "SELECT * FROM password_reset_tokens WHERE email = ?", ("alice@example.com",)
        ).fetchone()
        token = row["token"]
        pin = row["pin"]

        r = client.post("/api/auth/verify-reset-pin", json={"token": token, "pin": pin})
        validation_token = r.json()["validation_token"]

        r = client.post(
            "/api/auth/reset-password",
            json={
                "validation_token": validation_token,
                "password": "NewPass1234!",
                "password_confirm": "NewPass1234!",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True

        auth = users_mod.authenticate("alice", "NewPass1234!")
        assert auth is not None
        auth_old = users_mod.authenticate("alice", "OldPass123!")
        assert auth_old is None

        remaining = sqlite_db.execute(
            "SELECT * FROM password_reset_tokens WHERE validation_token = ?",
            (validation_token,),
        ).fetchone()
        assert remaining is None
