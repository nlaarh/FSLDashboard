"""PARITY: the matrix must change nothing at ship time.

Every role x every user in the read-only users snapshot x every feature gives the same answer as the old
code (`role in FEATURE_ROLES[feature]`), in three modes: seeded tables, tables missing, broken connection.
"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import access_store
import users
from permissions import FEATURE_ROLES, ROLES, can_access, get_user_features
from tests.access_helpers import add_user, hide_access_tables, seed_features

SNAPSHOT = Path(__file__).resolve().parent.parent / "local_backups" / "users_table_backup_20261002_225054.json"
LEGACY = ("manager", "officer", "supervisor", "viewer", "finance", "ers")
SNAPSHOT_USERS = [(u["username"], u["role"]) for u in json.loads(SNAPSHOT.read_text())]
OLD_FEATURES = [f for f in FEATURE_ROLES if f != "access.edit"]  # access.edit is new


def _old_features(role):
    return [f for f in OLD_FEATURES if role in FEATURE_ROLES[f]]


@pytest.fixture(params=["seeded", "tables_missing", "broken_connection"])
def mode(request, access_db, monkeypatch):
    if request.param == "seeded":
        seed_features(access_db)
    elif request.param == "tables_missing":
        hide_access_tables(access_db, "feature_access", "user_extra_roles")
    else:
        import db_adapter

        def boom():
            raise RuntimeError("connection refused")
        monkeypatch.setattr(db_adapter, "reader", boom)
    access_store.invalidate()
    return request.param


def test_every_role_every_feature(mode):
    for role in {*ROLES, *LEGACY}:
        for feature in OLD_FEATURES:
            assert can_access(role, feature) == (role in FEATURE_ROLES[feature]), (mode, role, feature)
        assert [f for f in get_user_features(role) if f in OLD_FEATURES] == _old_features(role)


def test_every_snapshot_user(mode, access_db):
    assert len(SNAPSHOT_USERS) > 5
    for username, role in SNAPSHOT_USERS:
        if mode == "broken_connection":  # the user lookup itself needs the broken connection
            roles = [role]
        else:
            add_user(access_db, username, role)
            roles = users.get_user(username)["roles"]
            assert roles == [role], (mode, username)
        for feature in OLD_FEATURES:
            assert can_access(roles, feature) == (role in FEATURE_ROLES[feature]), (mode, username, feature)


def test_me_features_unchanged(mode, access_db, monkeypatch):
    from routers import auth
    if mode == "broken_connection":
        pytest.skip("/me needs the users table itself; the role checks above cover this mode")
    monkeypatch.setattr(auth, "_AUTH_SECRET", "t")
    monkeypatch.setattr(users, "_sessions", {})
    app = FastAPI()
    app.include_router(auth.router)
    client = TestClient(app)
    for username, role in SNAPSHOT_USERS:
        add_user(access_db, username, role)
        client.cookies.set("fslapp_auth", auth._sign_cookie(f"{username}:{role}:nosession"))
        body = client.get("/api/auth/me").json()
        assert body["role"] == role and body["roles"] == [role]
        assert [f for f in body["features"] if f in OLD_FEATURES] == _old_features(role)
        assert ("access.edit" in body["features"]) == (role == "superadmin")


def test_snapshot_roles_are_all_known():
    assert {r for _, r in SNAPSHOT_USERS} <= {*ROLES, *LEGACY}


# ── The page / tab catalog: today's access, written out independently of permissions.py ──────────────────────

def _today(role: str, key: str) -> bool:
    """What the app did before the catalog: the frontend menu rules plus the server rules."""
    staff = role != "contractor"
    supervisor = role in ("ers-supervisor", "ers-member-relations")
    group = key.split(".")[0]
    if key.startswith("page."):
        return staff and not (key == "page.accounting" and supervisor)
    if key.startswith("accounting.tab_"):
        return staff and not supervisor
    if group in ("garage", "watchlist") and key != "garage.revenue_performance":
        return True                                           # staff and contractors alike
    if key == "reporting.tab_garage_performance":
        return staff
    if key in ("reporting.user_adoption", "reporting.dispatch_scorecard"):
        return role in ("superadmin", "admin", "executive")
    if key == "contractor.portal":
        return role == "contractor"
    if key == "admin.reference_data":
        return role in ("superadmin", "admin", "executive", "ers-director")
    return role in FEATURE_ROLES[key]                          # the original features keep their original sets


def test_catalog_matches_today_for_every_role(mode):
    for role in {*ROLES, *LEGACY}:
        for key in FEATURE_ROLES:
            assert can_access(role, key) == _today(role, key), (mode, role, key)


def test_server_gates_match_the_old_hard_coded_sets(mode):
    from routers.auth import _accounting_blocked, _admin_allowed, _reference_allowed
    for role in {*ROLES, *LEGACY}:
        assert _admin_allowed(role) == (role in ("superadmin", "admin")), (mode, role)
        assert _reference_allowed(role, "/api/admin/reference/x") == (role in ("executive", "ers-director", "superadmin", "admin")), (mode, role)
        assert not _reference_allowed(role, "/api/admin/users")
        assert _accounting_blocked([role], "/api/accounting/analytics") == (role in ("ers-supervisor", "ers-member-relations")), (mode, role)
    assert not _accounting_blocked(["contractor"], "/api/accounting/analytics")  # contractors are blocked elsewhere, as before


def test_migration_seeds_every_editable_feature_with_its_default():
    from migrations.roles_matrix import seed_rows
    from permissions import LOCKED_FEATURES
    rows = dict(seed_rows())
    assert set(rows) == set(FEATURE_ROLES) - set(LOCKED_FEATURES)
    assert all(set(json.loads(v)) == FEATURE_ROLES[k] for k, v in rows.items())
