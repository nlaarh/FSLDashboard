"""Admin user management tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(monkeypatch):
    from routers import admin

    monkeypatch.setattr(admin, "_ADMIN_PIN", "1234")
    app = FastAPI()
    app.include_router(admin.router)
    return TestClient(app)


def test_admin_update_user_rejects_weak_password(monkeypatch):
    client = _client(monkeypatch)
    called = False

    def fake_update_user(*args, **kwargs):
        nonlocal called
        called = True
        return {"username": args[0]}

    monkeypatch.setattr("users.update_user", fake_update_user)

    response = client.put(
        "/api/admin/users/tester",
        headers={"X-Admin-Pin": "1234"},
        json={"password": "short"},
    )

    assert response.status_code == 400
    assert "12" in response.json()["detail"]
    assert called is False


def test_admin_update_user_accepts_strong_password(monkeypatch):
    client = _client(monkeypatch)
    captured = {}

    def fake_update_user(username, **kwargs):
        captured["username"] = username
        captured.update(kwargs)
        return {"username": username, "active": True}

    monkeypatch.setattr("users.update_user", fake_update_user)

    response = client.put(
        "/api/admin/users/tester",
        headers={"X-Admin-Pin": "1234"},
        json={"password": "ValidPass123!"},
    )

    assert response.status_code == 200
    assert captured["username"] == "tester"
    assert captured["password"] == "ValidPass123!"


def test_admin_create_user_rejects_weak_password(monkeypatch):
    client = _client(monkeypatch)
    called = False

    def fake_create_user(*args, **kwargs):
        nonlocal called
        called = True
        return {"username": args[0]}

    monkeypatch.setattr("users.create_user", fake_create_user)

    response = client.post(
        "/api/admin/users",
        headers={"X-Admin-Pin": "1234"},
        json={"username": "tester", "name": "Test User", "password": "NoNumber!"},
    )

    assert response.status_code == 400
    assert "number" in response.json()["detail"].lower()
    assert called is False
