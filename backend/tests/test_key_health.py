"""Key health — key status rules, vault links, and alert emails only on change."""
from unittest.mock import patch

import pytest

import key_health

GOOD = ("good", "Good key", "Nothing works", ["GOOD_KEY"], lambda env: (True, "accepted"), "github")
BAD = ("bad", "Bad key", "Emails stop", ["BAD_KEY"], lambda env: (False, "rejected"), "agentmail")


@pytest.fixture
def store(monkeypatch):
    """In-memory stand-in for the shared cache, and two test keys."""
    saved = {}
    monkeypatch.setattr(key_health.cache, "disk_get_stale", lambda k: saved.get(k))
    monkeypatch.setattr(key_health.cache, "disk_put", lambda k, v, ttl=0: saved.__setitem__(k, v))
    monkeypatch.setattr(key_health, "KEYS", [GOOD, BAD])
    monkeypatch.setenv("GOOD_KEY", "x")
    monkeypatch.setenv("BAD_KEY", "y")
    monkeypatch.setenv("WEBSITE_SITE_NAME", "fslapp-nyaaa")
    monkeypatch.setattr(key_health, "_admin_emails", lambda: ["admin@nyaaa.com"])
    return saved


def test_vault_link_uses_dash_name():
    assert key_health.vault_name("SF_PASSWORD") == "SF-PASSWORD"
    assert key_health.secret_url("SF_PASSWORD").endswith("kv-fslapp-nyaaa.vault.azure.net/secrets/SF-PASSWORD")


def test_unreadable_vault_reference_is_broken(monkeypatch):
    monkeypatch.setenv("GOOD_KEY", "@Microsoft.KeyVault(SecretUri=https://kv/secrets/GOOD-KEY/)")
    row = key_health._check_one(*GOOD)
    assert row["status"] == "broken" and "cannot read GOOD_KEY from the Key Vault" in row["message"]


def test_missing_key(monkeypatch):
    monkeypatch.delenv("GOOD_KEY", raising=False)
    assert key_health._check_one(*GOOD)["status"] == "missing"


def test_unreachable_service_is_unknown_not_broken(monkeypatch):
    monkeypatch.setenv("GOOD_KEY", "x")
    def boom(env):
        raise TimeoutError("timed out")
    row = key_health._check_one("x", "X", "", ["GOOD_KEY"], boom, None)
    assert row["status"] == "unknown"


def test_emails_once_when_key_breaks_and_once_when_fixed(store, monkeypatch):
    with patch.object(key_health, "_send", return_value=True) as send:
        key_health.check_and_alert()
        key_health.check_and_alert()          # still broken: no second email
        assert send.call_count == 1
        to, subject, text = send.call_args.args
        assert to == ["admin@nyaaa.com"] and "Bad key" in subject
        assert "secrets/BAD-KEY" in text and "restart" in text

        monkeypatch.setattr(key_health, "KEYS", [GOOD, (*BAD[:4], lambda env: (True, "ok"), BAD[5])])
        key_health.check_and_alert()
        assert send.call_count == 2 and "working again" in send.call_args.args[1]


def test_test_site_never_emails(store, monkeypatch):
    monkeypatch.setenv("WEBSITE_SITE_NAME", "fslapp-nyaaa-dr")
    with patch.object(key_health, "_send") as send:
        key_health.check_and_alert()
    send.assert_not_called()


def test_broken_key_marks_its_diagram_node(store):
    with patch.object(key_health, "_send", return_value=True):
        key_health.check_and_alert()
    assert list(key_health.broken_nodes()) == ["agentmail"]
