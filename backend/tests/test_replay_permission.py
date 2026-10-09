"""Replay is for administrators, executives and ERS managers only: the permission and the three endpoints that serve it."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from permissions import FEATURE_ROLES, can_access, get_user_features
from tests.call_story_factories import towbook_cascade_raw


def test_who_may_replay():
    assert {r for r in ('superadmin', 'admin', 'executive', 'ers-manager', 'ers-director', 'ers-supervisor', 'contractor', 'finance') if can_access(r, 'scheduler.replay')} \
        == {'superadmin', 'admin', 'executive', 'ers-manager'}
    assert 'scheduler.replay' in get_user_features('executive') and 'scheduler.replay' not in get_user_features('ers-director')
    assert can_access('ers-director', 'scheduler.report_card')            # the report card itself is unchanged
    assert 'contractor' not in FEATURE_ROLES['scheduler.report_card'] | FEATURE_ROLES['scheduler.replay']


def _feature_aware(feature, request):
    role = request.headers.get('x-test-role', 'admin')
    if not any(can_access(role, f) for f in (feature if isinstance(feature, tuple) else (feature,))):
        raise HTTPException(status_code=403, detail='Access restricted')


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    import feature_flags
    from routers import call_story, report_card
    monkeypatch.setenv('REPORT_CARD_STORE_DIR', str(tmp_path))
    monkeypatch.setattr(feature_flags, 'is_on', lambda name: True)
    store = {}
    for mod in (call_story, report_card):
        monkeypatch.setattr(mod, 'require_feature', _feature_aware)
        monkeypatch.setattr(mod.cache, 'get', lambda k: store.get(k))
        monkeypatch.setattr(mod.cache, 'put', lambda k, v, ttl=0: store.__setitem__(k, v))
    monkeypatch.setattr(call_story, '_check_territory_access', lambda r, t: None)
    monkeypatch.setattr(report_card, '_check_territory_access', lambda r, t: None)
    monkeypatch.setattr(call_story, 'pull_story', lambda q, cfg, now=None: towbook_cascade_raw())
    monkeypatch.setattr(call_story, '_norms', lambda d, cfg: None)
    call_story._RATE.clear()
    app = FastAPI()
    app.include_router(call_story.router)
    app.include_router(report_card.router)
    return TestClient(app)


REPLAY_PATHS = ['/api/call-story/replay?q=05164342', '/api/call-story/replay-map?q=05164342', '/api/report-card/0HhFAKE0000000A1AA/2026-09-28/replay']


@pytest.mark.parametrize('role', ['ers-director', 'ers-supervisor', 'contractor'])
def test_other_roles_are_refused_on_every_replay_endpoint(app_client, role):
    for path in REPLAY_PATHS:
        assert app_client.get(path, headers={'x-test-role': role}).status_code == 403, (role, path)


@pytest.mark.parametrize('role', ['admin', 'executive', 'superadmin', 'ers-manager'])
def test_admin_executive_superadmin_and_ers_manager_are_let_through(app_client, role):
    assert app_client.get(REPLAY_PATHS[0], headers={'x-test-role': role}).status_code == 200
    assert app_client.get(REPLAY_PATHS[2], headers={'x-test-role': role}).status_code in (200, 404)       # 404 = day not built, not a refusal


def test_the_director_can_still_use_the_report_card_and_the_story(app_client):
    h = {'x-test-role': 'ers-director'}
    assert app_client.get('/api/call-story?q=05164342', headers=h).status_code == 200
    assert app_client.get('/api/report-card/0HhFAKE0000000A1AA/2026-09-28', headers=h).status_code in (200, 404)
