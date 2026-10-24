"""Access matrix logic: union of roles, fallback, locked features, caching."""
import pytest

import access_store
import users
from permissions import FEATURE_ROLES, ROLES, can_access, feature_roles, get_user_features
from tests.access_helpers import add_extra, add_user, hide_access_tables, seed_features


def test_union_of_two_roles(access_db):
    seed_features(access_db)
    assert not can_access("ers-manager", "scheduler.report_card") and not can_access("finance", "scheduler.report_card")
    assert can_access({"finance", "ers-director"}, "scheduler.report_card")
    assert can_access(["finance", "ers-manager"], "scheduler.replay")


def test_extra_role_reaches_effective_roles(access_db):
    seed_features(access_db)
    add_user(access_db, "pat", "finance")
    add_extra(access_db, "pat", "ers-director")
    got = users.get_user("pat")
    assert got["roles"] == ["finance", "ers-director"]
    assert "scheduler.report_card" in get_user_features(got["roles"])


def test_exclusive_primary_ignores_extras(access_db):
    add_user(access_db, "con", "contractor")
    add_extra(access_db, "con", "admin")
    assert users.get_user("con")["roles"] == ["contractor"]


def test_report_card_refuses_contractor_even_if_db_says_yes(access_db):
    access_db.execute("INSERT INTO feature_access (feature, roles) VALUES ('scheduler.report_card', '[\"contractor\",\"superadmin\"]')")
    access_db.commit()
    access_store.invalidate()
    assert not can_access("contractor", "scheduler.report_card")
    assert not can_access({"contractor", "finance"}, "scheduler.report_card")


def test_database_overrides_default_for_editable_feature(access_db):
    access_db.execute("INSERT INTO feature_access (feature, roles) VALUES ('scheduler.replay', '[\"finance\",\"superadmin\"]')")
    access_db.commit()
    access_store.invalidate()
    assert can_access("finance", "scheduler.replay") and not can_access("admin", "scheduler.replay")


@pytest.mark.parametrize("feature", ["admin.panel", "admin.impersonate", "access.edit", "scheduler.report_card_admin"])
def test_locked_features_never_read_the_database(access_db, feature):
    access_db.execute("INSERT INTO feature_access (feature, roles) VALUES (?, '[\"finance\"]')", (feature,))
    access_db.commit()
    access_store.invalidate()
    assert not can_access("finance", feature)
    assert can_access("superadmin", feature)


def test_unknown_role_in_row_uses_default(access_db):
    access_db.execute("INSERT INTO feature_access (feature, roles) VALUES ('scheduler.replay', '[\"wizard\"]')")
    access_db.commit()
    access_store.invalidate()
    assert can_access("executive", "scheduler.replay")


def test_cache_is_refreshed_after_invalidate(access_db):
    assert not can_access("finance", "scheduler.replay")
    access_db.execute("INSERT INTO feature_access (feature, roles) VALUES ('scheduler.replay', '[\"finance\",\"superadmin\"]')")
    access_db.commit()
    assert not can_access("finance", "scheduler.replay")  # still cached
    access_store.invalidate()
    assert can_access("finance", "scheduler.replay")


def test_failed_read_is_retried_after_five_seconds(access_db, monkeypatch):
    hide_access_tables(access_db, "feature_access")
    access_store.invalidate()
    assert feature_roles("scheduler.replay") == FEATURE_ROLES["scheduler.replay"]
    assert access_store.is_fallback()
    access_db.execute("ALTER TABLE feature_access_hidden RENAME TO feature_access")
    access_db.execute("INSERT INTO feature_access (feature, roles) VALUES ('scheduler.replay', '[\"finance\",\"superadmin\"]')")
    access_db.commit()
    assert not can_access("finance", "scheduler.replay")  # failure cached briefly
    now = access_store.time.monotonic()
    monkeypatch.setattr(access_store.time, "monotonic", lambda: now + 6)
    assert can_access("finance", "scheduler.replay") and not access_store.is_fallback()


def test_roles_list_covers_every_default_role():
    assert set().union(*FEATURE_ROLES.values()) <= set(ROLES)
