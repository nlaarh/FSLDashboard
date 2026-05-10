"""Tests for core_users.py — Postgres CRUD interface."""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from conftest import _make_mock_conn


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
            "username": "alice", "name": "Alice", "role": "admin",
            "email": "alice@example.com", "phone": "555-1234",
            "password_hash": "h", "salt": "s", "active": 1,
            "created_at": 1.0, "department": "executive",
        }
        conn, cur = _make_mock_conn(rows=[row])

        @contextmanager
        def fake_reader():
            yield conn

        monkeypatch.setattr("pg_pool.reader", fake_reader)
        user = core_users.get_user("alice")
        assert user == {
            "username": "alice", "name": "Alice", "role": "admin",
            "email": "alice@example.com", "active": True, "department": "executive",
        }

    def test_get_user_with_hash_includes_password_fields(self, monkeypatch):
        import core_users

        row = {
            "username": "alice", "name": "Alice", "role": "admin",
            "email": "alice@example.com", "phone": "",
            "password_hash": "h", "salt": "s", "active": 1,
            "created_at": 1.0, "department": "",
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
            "username": "alice", "name": "Alice", "role": "admin",
            "email": "Alice@Example.COM", "phone": "",
            "password_hash": "h", "salt": "s", "active": 1,
            "created_at": 1.0, "department": "",
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
            {"username": "alice", "name": "Alice", "role": "admin", "email": "",
             "phone": "", "password_hash": "h", "salt": "s", "active": 1,
             "created_at": 1.0, "department": ""},
            {"username": "bob", "name": "Bob", "role": "viewer", "email": "",
             "phone": "", "password_hash": "h", "salt": "s", "active": 0,
             "created_at": 2.0, "department": ""},
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
        core_users.create_user("carol", "Carol", "manager", "c@example.com", "", "h", "s", 1, 1.0, "ers")
        cur = conn.cursor.return_value.__enter__.return_value
        assert cur.execute.called
        calls = [c[0][0] for c in cur.execute.call_args_list]
        assert any("INSERT INTO users" in sql for sql in calls)

    def test_update_user_updates_fields(self, monkeypatch):
        import core_users

        existing = {
            "username": "alice", "name": "Alice", "role": "admin", "email": "",
            "phone": "", "password_hash": "h", "salt": "s", "active": 1,
            "created_at": 1.0, "department": "",
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
        cursor = conn.cursor.return_value.__enter__.return_value
        calls = [c[0] for c in cursor.execute.call_args_list]
        update_calls = [c for c in calls if "UPDATE users" in c[0]]
        assert len(update_calls) > 0
        params = update_calls[0][1]
        assert "Alice Smith" in params
        assert "superadmin" in params
        assert isinstance(result, dict)
        assert result["username"] == "alice"

    def test_update_user_with_password_uses_bcrypt(self, monkeypatch):
        import core_users

        existing = {
            "username": "alice", "name": "Alice", "role": "admin", "email": "",
            "phone": "", "password_hash": "oldhash", "salt": "oldsalt", "active": 1,
            "created_at": 1.0, "department": "",
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
            "username": "alice", "name": "Alice", "role": "admin", "email": "",
            "phone": "", "password_hash": "oldhash", "salt": "oldsalt", "active": 1,
            "created_at": 1.0, "department": "",
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
            "username": "alice", "name": "Alice", "role": "admin", "email": "",
            "phone": "", "password_hash": "h", "salt": "s", "active": 1,
            "created_at": 1.0, "department": "",
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
        assert any("active = %s" in c[0] and c[1][0] == 0 for c in update_calls)

    def test_restore_user_sets_active_one(self, monkeypatch):
        import core_users

        existing = {
            "username": "alice", "name": "Alice", "role": "admin", "email": "",
            "phone": "", "password_hash": "h", "salt": "s", "active": 0,
            "created_at": 1.0, "department": "",
        }
        conn, cur = _make_mock_conn(rows=[existing])

        @contextmanager
        def fake_writer():
            yield conn

        monkeypatch.setattr("pg_pool.writer", fake_writer)
        monkeypatch.setattr("pg_pool.reader", fake_writer)
        result = core_users.restore_user("alice")
        cursor = conn.cursor.return_value.__enter__.return_value
        calls = [c[0] for c in cursor.execute.call_args_list]
        update_calls = [c for c in calls if "UPDATE users" in c[0]]
        assert any("active = %s" in c[0] and c[1][0] == 1 for c in update_calls)
        assert isinstance(result, dict)
        assert result["username"] == "alice"
