"""Persistent user session and adoption reporting tests."""
from __future__ import annotations

import time

import bcrypt
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _seed_user(sqlite_db, username, password="ValidPass123!", role="viewer", active=1, department=""):
    h = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    sqlite_db.execute(
        "INSERT INTO users (username, name, role, email, phone, password_hash, salt, active, created_at, department) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (username, username.title(), role, "", "", h, "bcrypt", active, time.time(), department),
    )
    sqlite_db.commit()


def test_session_lifecycle_is_persisted(monkeypatch, sqlite_db):
    import users
    from repositories import user_sessions

    monkeypatch.setattr(users, "_trigger_backup", lambda: None)
    _seed_user(sqlite_db, "alice", role="admin")

    token = users.create_session("alice", "admin", "Alice")
    active = user_sessions.list_active_sessions()

    assert any(row["user"] == "alice" for row in active)

    users.destroy_session(token)
    active_after_logout = user_sessions.list_active_sessions()

    assert all(row["user"] != "alice" for row in active_after_logout)


def test_get_session_refreshes_persistent_last_seen(monkeypatch, sqlite_db):
    import users
    from repositories import user_sessions

    monkeypatch.setattr(users, "_trigger_backup", lambda: None)
    _seed_user(sqlite_db, "alice", role="admin")

    token = users.create_session("alice", "admin", "Alice")
    before = user_sessions.get_session(token)["last_seen"]
    time.sleep(0.01)

    assert users.get_session(token)["user"] == "alice"

    after = user_sessions.get_session(token)["last_seen"]
    assert after > before


def test_user_adoption_report_requires_privileged_role(monkeypatch, sqlite_db):
    from routers import auth, reporting

    monkeypatch.setattr(auth, "_AUTH_SECRET", "testsecret")
    _seed_user(sqlite_db, "viewer", role="viewer")

    app = FastAPI()
    app.include_router(reporting.router)
    client = TestClient(app)
    cookie = auth._sign_cookie("viewer:viewer:token")

    response = client.get(
        "/api/reporting/user-adoption",
        cookies={"fslapp_auth": cookie},
    )

    assert response.status_code == 403


def test_user_adoption_report_returns_all_users_with_current_month_usage(monkeypatch, sqlite_db):
    import users
    from routers import auth, reporting

    monkeypatch.setattr(auth, "_AUTH_SECRET", "testsecret")
    _seed_user(sqlite_db, "exec", role="executive", department="executive")
    _seed_user(sqlite_db, "alice", role="admin")
    _seed_user(sqlite_db, "bob", role="viewer")

    token = users.create_session("alice", "admin", "Alice")
    cookie = auth._sign_cookie(f"exec:executive:{token}")

    app = FastAPI()
    app.include_router(reporting.router)
    client = TestClient(app)

    response = client.get(
        "/api/reporting/user-adoption",
        cookies={"fslapp_auth": cookie},
    )

    assert response.status_code == 200
    data = response.json()
    usernames = {row["username"] for row in data["rows"]}
    alice = next(row for row in data["rows"] if row["username"] == "alice")
    bob = next(row for row in data["rows"] if row["username"] == "bob")

    assert {"exec", "alice", "bob"} <= usernames
    assert alice["status"] == "logged_in"
    assert alice["session_count"] == 1
    assert alice["minutes_this_month"] >= 0
    assert bob["status"] == "not_logged_in"
    assert bob["last_login"] is None
