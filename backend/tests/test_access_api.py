"""Access matrix API, on a scratch app that mounts only the router (never main.py) over a temp sqlite database."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import access_store
import users
from permissions import FEATURE_ROLES, can_access
from routers import admin_access, auth
from tests.access_helpers import add_extra, add_user, hide_access_tables, seed_features


def _login(client, username):
    client.cookies.set("fslapp_auth", auth._sign_cookie(f"{username}:x:nosession"))


@pytest.fixture
def api(access_db, monkeypatch):
    monkeypatch.setattr(auth, "_AUTH_SECRET", "t")
    seed_features(access_db)
    for name, role in [("boss", "superadmin"), ("adm", "admin"), ("fin", "finance"), ("con", "contractor"), ("dir", "ers-director")]:
        add_user(access_db, name, role)
    app = FastAPI()
    app.include_router(admin_access.router)
    client = TestClient(app)
    _login(client, "boss")
    return client, access_db


def _log(db):
    return [(r["action"], json.loads(r["detail"])) for r in db.execute("SELECT * FROM activity_log ORDER BY id").fetchall()]


@pytest.mark.parametrize("who,status", [("adm", 403), ("fin", 403), ("boss", 200)])
def test_only_superadmin(api, who, status):
    client, _ = api
    _login(client, who)
    assert client.get("/api/admin/access/matrix").status_code == status
    assert client.put("/api/admin/access/features", json={"changes": {"scheduler.replay": ["superadmin"]}}).status_code == (200 if status == 200 else 403)
    assert client.put("/api/admin/access/users", json={"changes": [{"username": "fin", "extra": ["admin"]}]}).status_code == (200 if status == 200 else 403)


def test_not_logged_in_is_401(api):
    client, _ = api
    client.cookies.clear()
    assert client.get("/api/admin/access/matrix").status_code == 401


def test_matrix_shape(api):
    client, _ = api
    m = client.get("/api/admin/access/matrix").json()
    assert m["fallback"] is False and "contractor" in m["roles"]
    by = {f["key"]: f for f in m["features"]}
    assert by["admin.panel"]["locked"] and by["access.edit"]["locked"] and by["scheduler.report_card_admin"]["locked"] and by["admin.impersonate"]["locked"]
    assert not by["scheduler.replay"]["locked"] and by["scheduler.replay"]["source"] == "db"
    assert by["scheduler.replay"]["roles"] == sorted(FEATURE_ROLES["scheduler.replay"])


def test_feature_save_logs_and_takes_effect(api):
    client, db = api
    roles = sorted(FEATURE_ROLES["scheduler.replay"] | {"finance"})
    assert client.put("/api/admin/access/features", json={"changes": {"scheduler.replay": roles}}).status_code == 200
    assert can_access("finance", "scheduler.replay")  # cache was invalidated by the save
    assert _log(db) == [("access_feature_change", {"feature": "scheduler.replay", "before": sorted(FEATURE_ROLES["scheduler.replay"]), "after": roles, "reset": False})]
    reset = client.put("/api/admin/access/features", json={"changes": {"scheduler.replay": None}}).json()
    assert not can_access("finance", "scheduler.replay")
    assert {f["key"]: f for f in reset["features"]}["scheduler.replay"]["source"] == "default"


@pytest.mark.parametrize("changes", [
    {"admin.panel": ["superadmin", "finance"]},                  # locked
    {"access.edit": ["superadmin", "finance"]},                  # locked
    {"scheduler.report_card_admin": ["superadmin"]},             # locked
    {"nope": ["superadmin"]},                                    # unknown feature
    {"scheduler.replay": ["superadmin", "wizard"]},              # unknown role
    {"scheduler.report_card": ["superadmin", "contractor"]},     # contractor never
    {"scheduler.replay": ["admin"]},                             # superadmin removed
    {"scheduler.replay": "admin"},                               # not a list
])
def test_feature_validation(api, changes):
    client, db = api
    assert client.put("/api/admin/access/features", json={"changes": changes}).status_code == 400
    assert _log(db) == []
    assert can_access("executive", "scheduler.replay")


def test_feature_save_is_all_or_nothing(api):
    client, _ = api
    r = client.put("/api/admin/access/features", json={"changes": {"scheduler.replay": ["superadmin", "finance"], "admin.panel": ["superadmin"]}})
    assert r.status_code == 400 and not can_access("finance", "scheduler.replay")


def test_user_extra_roles_save(api):
    client, db = api
    r = client.put("/api/admin/access/users", json={"changes": [{"username": "fin", "extra": ["ers-director"]}]})
    assert r.status_code == 200
    eff = r.json()["changed"]["fin"]
    assert eff["roles"] == ["finance", "ers-director"] and "scheduler.report_card" in eff["features"]
    assert client.get("/api/admin/access/users/fin/effective").json() == eff
    assert _log(db) == [("access_user_change", {"username": "fin", "primary": ["finance", "finance"], "extra": ["ers-director"]})]
    page = client.get("/api/admin/access/users").json()
    assert {u["username"]: u for u in page["users"]}["fin"]["extra"] == ["ers-director"]


def test_primary_change_updates_the_user_and_clears_the_cache(api):
    client, db = api
    r = client.put("/api/admin/access/users", json={"changes": [{"username": "fin", "primary": "executive", "extra": []}]})
    assert r.status_code == 200 and r.json()["changed"]["fin"]["roles"] == ["executive"]
    assert db.execute("SELECT role FROM users WHERE username='fin'").fetchone()["role"] == "executive"
    assert users.get_user("fin")["role"] == "executive"  # cache invalidated


@pytest.mark.parametrize("change", [
    {"username": "con", "extra": ["admin"]},                       # contractor + another
    {"username": "fin", "extra": ["contractor"]},                  # another + contractor
    {"username": "fin", "primary": "ers-supervisor", "extra": ["admin"]},
    {"username": "fin", "extra": ["wizard"]},                      # unknown role
    {"username": "ghost", "extra": []},                            # unknown user
])
def test_user_validation(api, change):
    client, db = api
    assert client.put("/api/admin/access/users", json={"changes": [change]}).status_code == 400
    assert _log(db) == [] and db.execute("SELECT COUNT(*) AS n FROM user_extra_roles").fetchone()["n"] == 0


def test_cannot_remove_last_superadmin(api):
    client, db = api
    assert client.put("/api/admin/access/users", json={"changes": [{"username": "boss", "primary": "admin", "extra": []}]}).status_code == 400
    add_user(db, "boss2", "superadmin")
    assert client.put("/api/admin/access/users", json={"changes": [{"username": "boss2", "primary": "admin", "extra": []}]}).status_code == 200
    assert client.put("/api/admin/access/users", json={"changes": [{"username": "boss", "primary": "admin", "extra": []}]}).status_code == 400


def test_one_activity_row_per_user_change(api):
    client, db = api
    client.put("/api/admin/access/users", json={"changes": [{"username": "fin", "extra": ["admin"]}, {"username": "dir", "extra": ["ers-manager"]}]})
    assert [a for a, _ in _log(db)] == ["access_user_change"] * 2


def test_users_paging_and_search(api):
    client, db = api
    for i in range(30):
        add_user(db, f"user{i:02d}", "viewer")
    p1 = client.get("/api/admin/access/users?page_size=25").json()
    assert p1["total"] == 35 and len(p1["users"]) == 25
    assert len(client.get("/api/admin/access/users?page=2&page_size=25").json()["users"]) == 10
    assert client.get("/api/admin/access/users?q=USER07").json()["total"] == 1
    add_extra(db, "fin", "ers-director")
    assert {u["username"] for u in client.get("/api/admin/access/users?role=ers-director").json()["users"]} == {"dir", "fin"}


def test_tables_missing_save_is_a_clear_503_and_matrix_falls_back(api):
    client, db = api
    hide_access_tables(db, "feature_access", "user_extra_roles")
    access_store.invalidate()
    m = client.get("/api/admin/access/matrix").json()
    assert m["fallback"] is True and {f["key"]: f for f in m["features"]}["scheduler.replay"]["source"] == "default"
    assert client.put("/api/admin/access/features", json={"changes": {"scheduler.replay": ["superadmin"]}}).status_code == 503
    assert client.put("/api/admin/access/users", json={"changes": [{"username": "fin", "extra": ["admin"]}]}).status_code == 503


def test_user_save_is_all_or_nothing(api, monkeypatch):
    client, db = api
    from repositories import access as repo
    real = repo.db_adapter.writer

    def failing_writer():
        raise RuntimeError("db down")
    monkeypatch.setattr(repo.db_adapter, "writer", failing_writer)
    r = client.put("/api/admin/access/users", json={"changes": [{"username": "fin", "primary": "executive", "extra": []}]})
    monkeypatch.setattr(repo.db_adapter, "writer", real)
    assert r.status_code == 503
    assert db.execute("SELECT role FROM users WHERE username='fin'").fetchone()["role"] == "finance"


@pytest.mark.parametrize("change", [
    {"username": "con", "primary": "manager", "extra": []},        # contractor swapped for manager (the QA bug)
    {"username": "con", "primary": "admin", "extra": ["manager"]},
    {"username": "fin", "primary": "contractor", "extra": []},     # a normal user swapped into a restricted role
    {"username": "fin", "primary": "ers-supervisor", "extra": []},
])
def test_restricted_roles_are_never_swapped_by_this_screen(api, change):
    client, db = api
    r = client.put("/api/admin/access/users", json={"changes": [change]})
    assert r.status_code == 400 and "Users & Sessions" in r.json()["detail"]
    assert db.execute("SELECT role FROM users WHERE username=?", (change["username"],)).fetchone()["role"] in ("contractor", "finance")
    assert _log(db) == []


def test_a_bulk_save_with_one_restricted_swap_changes_nobody(api):
    client, db = api
    r = client.put("/api/admin/access/users", json={"changes": [{"username": "fin", "extra": ["admin"]},
                                                                  {"username": "con", "primary": "manager", "extra": []}]})
    assert r.status_code == 400
    assert db.execute("SELECT COUNT(*) AS n FROM user_extra_roles").fetchone()["n"] == 0


def test_restricted_user_can_be_saved_unchanged(api):
    client, _ = api
    assert client.put("/api/admin/access/users", json={"changes": [{"username": "con", "primary": "contractor", "extra": []}]}).status_code == 200
