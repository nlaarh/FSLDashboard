"""FSLAPP_FEATURE_OVERRIDES: local-only feature flag overrides (never written to the settings table)."""

import logging

import pytest

import feature_flags
from feature_flags import OVERRIDES_ENV, effective_features, env_overrides, is_on


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(OVERRIDES_ENV, raising=False)
    monkeypatch.delenv('WEBSITE_SITE_NAME', raising=False)
    monkeypatch.setattr(feature_flags, '_logged', set())
    from repositories import settings
    monkeypatch.setattr(settings, 'get_setting', lambda key: {'chat': True, 'scheduler_report_card': False})


def test_no_env_means_no_overrides():
    assert env_overrides() == {}
    assert effective_features()['chat'] is True


def test_overrides_beat_the_settings_table(monkeypatch):
    monkeypatch.setenv(OVERRIDES_ENV, 'scheduler_report_card=1,chat=0')
    assert env_overrides() == {'scheduler_report_card': True, 'chat': False}
    assert is_on('scheduler_report_card') and not is_on('chat')


def test_parsing_is_forgiving_and_safe(monkeypatch, caplog):
    monkeypatch.setenv(OVERRIDES_ENV, ' Scheduler_Report_Card = on , made_up=1, chat=maybe, ,matrix=false ')
    with caplog.at_level(logging.WARNING, logger='feature_flags'):
        assert env_overrides() == {'scheduler_report_card': True, 'matrix': False}
    assert 'made_up=1' in caplog.text and 'chat=maybe' in caplog.text
    assert 'made_up' not in effective_features()      # an unknown name never invents a flag


def test_warning_is_logged_once(monkeypatch, caplog):
    monkeypatch.setenv(OVERRIDES_ENV, 'scheduler_report_card=1')
    with caplog.at_level(logging.WARNING, logger='feature_flags'):
        env_overrides(), env_overrides(), is_on('chat')
    warnings = [r for r in caplog.records if 'OVERRIDES ACTIVE' in r.getMessage()]
    assert len(warnings) == 1 and 'scheduler_report_card=on' in warnings[0].getMessage()


def test_ignored_on_azure(monkeypatch):
    monkeypatch.setenv(OVERRIDES_ENV, 'scheduler_report_card=1')
    monkeypatch.setenv('WEBSITE_SITE_NAME', 'fslapp-nyaaa')
    assert env_overrides() == {}
    assert is_on('scheduler_report_card') is False


def test_admin_save_never_persists_an_overridden_flag(monkeypatch):
    from routers import admin
    stored = {'features': {'scheduler_report_card': False, 'chat': True}}
    saved = {}
    monkeypatch.setattr(admin, '_check_pin', lambda request: None)
    monkeypatch.setattr(admin, '_load_settings', lambda: stored)
    monkeypatch.setattr(admin, '_save_settings', lambda s: saved.update(s))
    monkeypatch.setenv(OVERRIDES_ENV, 'scheduler_report_card=1')
    # The Admin screen echoes back what /api/features showed, overrides included.
    admin.admin_update_settings(None, {'features': {'scheduler_report_card': True, 'chat': False}})
    assert saved['features']['scheduler_report_card'] is False   # stored value kept
    assert saved['features']['chat'] is False                     # real edits still saved
