"""Tests for users.py public API and admin router endpoints."""
from __future__ import annotations

import time

import bcrypt
import pytest


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
        result = users_mod.create_user("carol", "Secret123!", "Carol", role="manager", email="c@example.com")
        assert result["username"] == "carol"
        assert result["name"] == "Carol"
        assert result["role"] == "manager"
        assert result["email"] == "c@example.com"
        row = sqlite_db.execute("SELECT * FROM users WHERE username = ?", ("carol",)).fetchone()
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
        result = users_mod.update_user("alice", name="Alice Smith", role="superadmin", email="alice@new.com")
        assert result["name"] == "Alice Smith"
        assert result["role"] == "superadmin"
        assert result["email"] == "alice@new.com"

    def test_update_user_password(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "OldPass123!")
        result = users_mod.update_user("alice", password="NewPass123!")
        assert result is not None
        assert users_mod.authenticate("alice", "NewPass123!") is not None
        assert users_mod.authenticate("alice", "OldPass123!") is None

    def test_delete_user_soft_deletes(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "Secret123!")
        users_mod.delete_user("alice")
        row = sqlite_db.execute("SELECT active FROM users WHERE username = ?", ("alice",)).fetchone()
        assert row["active"] == 0

    def test_delete_user_invalidates_sessions(self, monkeypatch, sqlite_db):
        import users as users_mod

        monkeypatch.setattr(users_mod, "_trigger_backup", lambda: None)
        self._seed_user(sqlite_db, "alice", "Secret123!", role="admin")
        token = users_mod.create_session("alice", "admin", "Alice")
        monkeypatch.setattr(users_mod, "_sessions", {token: {"user": "alice", "role": "admin", "name": "Alice"}})
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
        row = sqlite_db.execute("SELECT active FROM users WHERE username = ?", ("alice",)).fetchone()
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
            json={"username": "bob", "name": "Bob", "password": "ValidPass123!", "role": "viewer", "email": "bob@example.com"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "bob"
        row = sqlite_db.execute("SELECT * FROM users WHERE username = ?", ("bob",)).fetchone()
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
        row = sqlite_db.execute("SELECT active FROM users WHERE username = ?", ("alice",)).fetchone()
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
        r = admin_client.post("/api/admin/users/alice/restore", headers={"X-Admin-Pin": "1234"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["user"]["active"] is True
        row = sqlite_db.execute("SELECT active FROM users WHERE username = ?", ("alice",)).fetchone()
        assert row["active"] == 1

    def test_restore_missing_endpoint_shape(self, admin_client, monkeypatch):
        import db_backup

        monkeypatch.setattr(db_backup, "restore_latest", lambda: True)
        r = admin_client.post("/api/admin/users/restore-missing", headers={"X-Admin-Pin": "1234"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "source" in data
