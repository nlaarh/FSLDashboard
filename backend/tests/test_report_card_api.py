"""Scheduler Report Card API gates and build flow (bare FastAPI app; no Postgres, no Salesforce)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from report_card_snapshot import build_snapshot
from tests.report_card_factories import tiny_raw

TID, DAY = '0HhFAKE00000001AAA', '2026-09-28'


@pytest.fixture
def client(monkeypatch, tmp_path):
    import feature_flags
    import report_card_store
    from routers import report_card

    state = {'flag': True, 'builds': []}
    monkeypatch.setenv('REPORT_CARD_STORE_DIR', str(tmp_path))
    monkeypatch.setattr(feature_flags, 'is_on', lambda name: state['flag'] and name == 'scheduler_report_card')

    def fake_require(feature, request):
        role = request.headers.get('x-test-role', 'admin')
        allowed = {'scheduler.report_card': {'admin', 'executive'}, 'scheduler.report_card_admin': {'admin'},
                   'scheduler.replay': {'admin', 'executive'}}
        if role not in allowed.get(feature, set()):
            raise HTTPException(status_code=403, detail='Access restricted')

    monkeypatch.setattr(report_card, 'require_feature', fake_require)
    monkeypatch.setattr(report_card, '_check_territory_access', lambda request, tid: None)
    monkeypatch.setattr(report_card, '_run_build', lambda *args: state['builds'].append(args))
    monkeypatch.setattr(report_card.cache, 'get', lambda key: None)
    monkeypatch.setattr(report_card.cache, 'put', lambda key, data, ttl=0: None)
    app = FastAPI()
    app.include_router(report_card.router)
    return TestClient(app), state, report_card_store


def test_flag_off_is_404(client):
    c, state, _ = client
    state['flag'] = False
    assert c.get(f'/api/report-card/{TID}/{DAY}').status_code == 404


def test_contractor_is_forbidden(client):
    c, _, _ = client
    r = c.get(f'/api/report-card/{TID}/{DAY}', headers={'x-test-role': 'contractor'})
    assert r.status_code == 403
    assert c.post(f'/api/report-card/{TID}/{DAY}/build', headers={'x-test-role': 'contractor'}).status_code == 403


@pytest.mark.parametrize('tid, day', [(TID, 'today'), (TID, '2026-9-28'), ('not-an-id', DAY), (TID, '2024-01-01')])
def test_bad_input_and_non_past_days_are_422(client, tid, day):
    c, _, _ = client
    if day == 'today':
        day = datetime.now(ZoneInfo('America/New_York')).date().isoformat()
    assert c.get(f'/api/report-card/{tid}/{day}').status_code == 422


def test_not_built_then_build_starts_once(client):
    c, state, _ = client
    r = c.get(f'/api/report-card/{TID}/{DAY}')
    assert r.status_code == 404 and r.json() == {'status': 'not_built'}
    r = c.post(f'/api/report-card/{TID}/{DAY}/build')
    assert r.status_code == 202 and r.json()['status'] == 'building'
    assert c.get(f'/api/report-card/{TID}/{DAY}').status_code == 202
    assert c.post(f'/api/report-card/{TID}/{DAY}/build').status_code == 202   # no second build
    assert len(state['builds']) == 1


def test_failed_build_is_409(client):
    c, _, store = client
    store.set_status(TID, DAY, status='failed', error='SA count mismatch 84 vs 61', started_ts=0)
    r = c.get(f'/api/report-card/{TID}/{DAY}')
    assert r.status_code == 409 and 'mismatch' in r.json()['error']


def test_built_day_returns_view_and_final_rebuild_needs_admin(client):
    c, state, store = client
    store.save_snapshot(TID, DAY, build_snapshot(tiny_raw()))
    r = c.get(f'/api/report-card/{TID}/{DAY}')
    assert r.status_code == 200
    body = r.json()
    assert body['summary']['sa_count'] == 1
    assert body['sas'][0]['verdict']['code'] == 'BOUNCED'
    assert {d['name'] for d in body['drivers']} == {'Driver One', 'Driver Two'}
    assert all('gps' not in d for d in body['drivers'])
    assert 'candidate_sets' not in body['sas'][0]
    assert c.post(f'/api/report-card/{TID}/{DAY}/build').json()['status'] == 'ready'
    r = c.post(f'/api/report-card/{TID}/{DAY}/build?force=true', headers={'x-test-role': 'executive'})
    assert r.status_code == 403
    assert c.post(f'/api/report-card/{TID}/{DAY}/build?force=true').status_code == 202
    assert len(state['builds']) == 1


def test_r2_is_the_default_and_old_snapshots_ask_for_a_rebuild(client):
    c, _, store = client
    snap = build_snapshot(tiny_raw())
    store.save_snapshot(TID, DAY, snap)
    r = c.get(f'/api/report-card/{TID}/{DAY}')
    assert r.status_code == 200 and r.json()['snapshot']['rules_version'] == 'r2'
    for sa in snap['sas']:
        sa.pop('pta_initial_src', None)
    snap['builder_version'] = 'rc-build-1.0'
    store.save_snapshot(TID, DAY, snap)
    r = c.get(f'/api/report-card/{TID}/{DAY}')
    assert r.status_code == 409 and r.json()['status'] == 'rules_unavailable' and r.json()['available'] == ['r1']
    assert c.get(f'/api/report-card/{TID}/{DAY}?rules=r1').json()['snapshot']['rules_version'] == 'r1'
    assert c.get(f'/api/report-card/{TID}/{DAY}?rules=r9').status_code == 422


def test_replay_is_gated_and_served_from_the_snapshot(client):
    c, state, store = client
    url = f'/api/report-card/{TID}/{DAY}/replay'
    assert c.get(url).status_code == 404 and c.get(url).json() == {'status': 'not_built'}
    store.save_snapshot(TID, DAY, build_snapshot(tiny_raw()))
    r = c.get(url)
    assert r.status_code == 200 and {d['mode'] for d in r.json()['drivers']} <= {'gps', 'estimated', 'none'}
    assert state['builds'] == []                       # nothing pulled from Salesforce
    assert c.get(url, headers={'x-test-role': 'contractor'}).status_code == 403
    state['flag'] = False
    assert c.get(url).status_code == 404


def test_garages_with_work_lists_only_garages_that_had_ers_work_orders_that_day(client, monkeypatch):
    c, state, *_ = client
    asked = []

    def fake_query(soql):
        asked.append(soql)
        if 'GROUP BY ServiceTerritoryId' in soql:
            return [{'ServiceTerritoryId': '0HhFAKE0000000A1AA', 'cnt': 90}, {'ServiceTerritoryId': '0HhFAKE0000000B2AA', 'cnt': 4}]
        return [{'Id': '0HhFAKE0000000A1AA', 'Name': '100 - Fleet'}, {'Id': '0HhFAKE0000000B2AA', 'Name': '076DO - Towbook Garage'}]
    monkeypatch.setattr('sf_client.sf_query_all', fake_query)
    r = c.get('/api/report-card/garages?date=2026-09-28')
    assert r.status_code == 200 and r.json() == [{'id': '0HhFAKE0000000A1AA', 'name': '100 - Fleet', 'count': 90},
                                                  {'id': '0HhFAKE0000000B2AA', 'name': '076DO - Towbook Garage', 'count': 4}]
    day_q = asked[0]
    assert "RecordType.Name = 'ERS Service Appointment'" in day_q and "WorkType.Name != 'Tow Drop-Off'" in day_q
    assert 'CreatedDate >= 2026-09-28T04:00:00Z' in day_q and 'CreatedDate < 2026-09-29T04:00:00Z' in day_q       # the Eastern day, in UTC
    assert len(asked) == 2                                       # one aggregate + one name lookup


def test_garages_with_work_is_gated_validates_the_date_and_needs_a_past_day(client):
    c, state, *_ = client
    assert c.get('/api/report-card/garages?date=2026-09-28', headers={'x-test-role': 'contractor'}).status_code == 403
    assert c.get('/api/report-card/garages?date=tomorrow').status_code == 422
    assert c.get('/api/report-card/garages?date=2999-01-01').status_code == 422
    assert c.get('/api/report-card/garages?date=1999-01-01').status_code == 422
    state['flag'] = False
    assert c.get('/api/report-card/garages?date=2026-09-28').status_code == 404


def test_call_flags_are_gated_and_make_three_queries_at_most(client, monkeypatch):
    import report_card_build
    c, state, store = client
    url = f'/api/report-card/{TID}/{DAY}/call-flags'
    assert c.get(url).status_code == 404 and c.get(url).json() == {'status': 'not_built'}
    snap = build_snapshot(tiny_raw())
    store.save_snapshot(TID, DAY, snap)
    seen = []
    monkeypatch.setattr(report_card_build.Puller, 'batched', lambda self, t, ids, size=150, **k: seen.append(t) or [])
    r = c.get(url)
    assert r.status_code == 200 and r.json() == {'flags': {}} and len(seen) <= 3
    assert c.get(url, headers={'x-test-role': 'contractor'}).status_code == 403
