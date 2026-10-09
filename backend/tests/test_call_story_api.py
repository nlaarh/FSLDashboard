"""Call Story API and Salesforce budget (bare FastAPI app; fake Salesforce; no Postgres)."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from call_story_config import cs1
from tests.call_story_factories import WO, towbook_cascade_raw


def _composite_refused(monkeypatch):
    """Salesforce refuses the bundled request, so pull_story takes the slow, one-query-at-a-time path."""
    import report_card_build as rb

    def refuse(self, named):
        raise rb.CompositeError('wo', 'refused')
    monkeypatch.setattr(rb.Puller, 'composite', refuse)


def test_slow_path_is_sequential_and_capped(monkeypatch):
    """Every query goes through sf_query_all one at a time; sf_parallel is never used; <= max_sf_calls."""
    import call_story_pull as cp
    import report_card_build as rb
    _composite_refused(monkeypatch)
    raw = towbook_cascade_raw()
    calls = []

    def fake_all(soql, timeout=None):
        calls.append(soql)
        if 'FROM WorkOrder WHERE WorkOrderNumber' in soql:
            return [raw['wo']]
        if 'FROM ServiceAppointment WHERE ERS_Work_Order__c' in soql:
            return raw['sas']
        if 'ServiceAppointmentHistory' in soql:
            return raw['history']
        if 'FROM SMS_Send_Log__c' in soql:
            return raw['sms']
        return []
    monkeypatch.setattr(rb, 'sf_query_all', fake_all)
    monkeypatch.setattr('sf_client.sf_parallel', lambda **kw: pytest.fail('sf_parallel used'))
    monkeypatch.setattr('cache.get', lambda key: None)
    monkeypatch.setattr('cache.put', lambda *a, **k: None)
    out = cp.pull_story('05164342', cs1(), now=cp.parse_dt('2026-10-04T00:00:00Z'))
    assert out['sf_calls'] == len(calls) <= cs1()['max_sf_calls']
    assert out['wo']['Id'] == WO and len(out['history']) == len(raw['history']) and out['closed'] is True
    assert all('Mobile_Phone__c' not in q for q in calls)                # after 9/1: no phone read at all


def test_pull_refuses_non_ers_and_old_calls(monkeypatch):
    import call_story_pull as cp
    import report_card_build as rb
    _composite_refused(monkeypatch)
    raw = towbook_cascade_raw()
    sas = [{**s, 'RecordType': {'Name': 'Travel'}} for s in raw['sas']]
    monkeypatch.setattr(rb, 'sf_query_all', lambda soql, timeout=None: [raw['wo']] if 'FROM WorkOrder' in soql else sas)
    with pytest.raises(cp.NotSupported):
        cp.pull_story('05164342', cs1(), now=cp.parse_dt('2026-10-04T00:00:00Z'))
    with pytest.raises(cp.NotSupported):
        cp.pull_story('05164342', cs1(), now=cp.parse_dt('2028-10-04T00:00:00Z'))


@pytest.fixture
def client(monkeypatch, tmp_path):
    import feature_flags
    from routers import call_story
    state = {'flag': True, 'pulls': 0}
    monkeypatch.setenv('REPORT_CARD_STORE_DIR', str(tmp_path))
    monkeypatch.setattr(feature_flags, 'is_on', lambda name: state['flag'] and name == 'call_story')

    def fake_require(feature, request):
        if request.headers.get('x-test-role', 'admin') not in ('admin', 'executive'):
            raise HTTPException(status_code=403, detail='Access restricted')

    def fake_pull(q, cfg, now=None):
        state['pulls'] += 1
        return towbook_cascade_raw()
    store = {}
    monkeypatch.setattr(call_story, 'require_feature', fake_require)
    monkeypatch.setattr(call_story, '_check_territory_access', lambda request, tid: None)
    monkeypatch.setattr(call_story, 'pull_story', fake_pull)
    monkeypatch.setattr(call_story, '_norms', lambda d, cfg: None)
    monkeypatch.setattr(call_story.cache, 'get', lambda k: store.get(k))
    monkeypatch.setattr(call_story.cache, 'put', lambda k, v, ttl=0: store.__setitem__(k, v))
    disk = state['disk'] = {}
    monkeypatch.setattr(call_story.cache, 'disk_get', lambda k: disk.get(k))        # never the real L2 cache (a database)
    monkeypatch.setattr(call_story.cache, 'disk_put', lambda k, v, ttl=0: disk.__setitem__(k, (v, ttl)[0]))
    state['store'] = store
    call_story._RATE.clear()
    app = FastAPI()
    app.include_router(call_story.router)
    return TestClient(app), state


def test_flag_off_404_and_contractor_403(client):
    c, state = client
    assert c.get('/api/call-story?q=05164342', headers={'x-test-role': 'contractor'}).status_code == 403
    state['flag'] = False
    assert c.get('/api/call-story?q=05164342').status_code == 404


def test_unrecognised_input_is_400_before_any_salesforce_call(client):
    c, state = client
    r = c.get('/api/call-story?q=hello')
    assert r.status_code == 400 and 'Not a call number' in r.json()['detail'] and state['pulls'] == 0


def test_story_then_cache_hit_with_zero_salesforce_calls(client):
    c, state = client
    r1 = c.get('/api/call-story?q=05164342')
    assert r1.status_code == 200 and r1.json()['meta']['cache'] == 'miss' and r1.json()['meta']['sf_calls'] == 8
    assert r1.json()['verdict']['primary'] == 'NOT_GRADED_TOWBOOK'
    r2 = c.get('/api/call-story?q=05164342&sa=SA-1000010')
    assert r2.json()['meta'] == {**r2.json()['meta'], 'cache': 'hit', 'sf_calls': 0} and state['pulls'] == 1
    assert c.get('/api/call-story?q=05164342&raw=1').json()['raw_history'][0]['Field'] == 'created'


def test_rate_limit_429_counts_real_salesforce_pulls(client):
    c, state = client
    numbers = [f'051643{n:02d}' for n in range(20, 31)]     # 11 different calls = 11 pulls
    codes = [c.get(f'/api/call-story?q={n}').status_code for n in numbers]
    assert codes[:10] == [200] * 10 and codes[10] == 429 and state['pulls'] == 10


def test_cache_hits_never_count_towards_the_limit(client):
    c, state = client
    codes = [c.get('/api/call-story?q=05164342').status_code for _ in range(25)]   # 1 pull, 24 hits
    assert codes == [200] * 25 and state['pulls'] == 1


def test_narrative_needs_the_story_first_and_falls_back_without_a_key(client, monkeypatch):
    c, _ = client
    assert c.post('/api/call-story/narrative', json={'sa_id': '08pFAKE00000010AAA'}).status_code == 409
    c.get('/api/call-story?q=05164342')
    monkeypatch.setattr('utils.load_ai_settings', lambda: ('openai', '', 'gpt-4o'))
    r = c.post('/api/call-story/narrative', json={'sa_id': '08pFAKE00000010AAA'}).json()
    assert r['source'] == 'template' and r['validation']['reason'] == 'no AI key'
    assert any('48.1 min' in s['text'] for s in r['sentences'])


def test_replay_endpoint_returns_steps_for_a_towbook_cascade_and_is_gated(client):
    """Same gates as the story; Towbook offers/declines become steps; no phone or street leaves the API."""
    c, state = client
    assert c.get('/api/call-story/replay?q=05164342', headers={'x-test-role': 'contractor'}).status_code == 403
    assert c.get('/api/call-story/replay?q=hello').status_code == 400 and state['pulls'] == 0
    r = c.get('/api/call-story/replay?q=05164342')
    assert r.status_code == 200
    body = r.json()
    ids = [s['id'] for s in body['steps']]
    assert ids[0] == 'C0' and len(ids) == len(set(ids)) and body['steps'][0]['dt'] == 0
    assert [s['dt'] for s in body['steps']] == sorted(s['dt'] for s in body['steps'])
    assert any(s['to'] == 'towbook' or s['from'] == 'towbook' for s in body['steps'])
    import re
    assert body['header']['wo'] and not re.search(r'\d{3}[-. ]?\d{3}[-. ]?\d{4}', r.text)       # no phone number anywhere
    assert not any(k in r.text.lower() for k in ('recipient_phone', 'mobile_phone', '"street"'))
    state['flag'] = False
    assert c.get('/api/call-story/replay?q=05164342').status_code == 404


def test_replay_map_endpoint_is_gated_cached_and_reports_towbook(client, monkeypatch):
    from routers import call_story
    c, state = client
    seen = []

    def fake_pull_map(raw, puller=None, snapshot_for=None):
        assert snapshot_for is not None                                    # the day snapshot is what makes most maps free
        seen.append(1)
        return {'wo': {'lat': 1.0, 'lon': 2.0}, 'garage': None, 'towbook': {'driver': None, 'truck': None}, 'drivers': [], 'notes': ['t'], 'window': None, 'sf_calls': 2}
    monkeypatch.setattr('wo_replay_map.pull_map', fake_pull_map)
    assert c.get('/api/call-story/replay-map?q=05164342', headers={'x-test-role': 'contractor'}).status_code == 403
    assert c.get('/api/call-story/replay-map?q=hello').status_code == 400
    r1 = c.get('/api/call-story/replay-map?q=05164342')
    r2 = c.get('/api/call-story/replay-map?q=05164342')
    assert r1.status_code == 200 and r1.json()['towbook'] == {'driver': None, 'truck': None} and r2.json() == r1.json()
    assert len(seen) == 1 and state['pulls'] == 1                          # the second call used the cached map and the cached pull
    state['flag'] = False
    assert c.get('/api/call-story/replay-map?q=05164342').status_code == 404


def test_closed_call_map_is_kept_on_disk_and_a_restart_reads_it_back(client, monkeypatch):
    from routers import call_story
    c, state = client
    seen = []
    monkeypatch.setattr('wo_replay_map.pull_map', lambda raw, puller=None, snapshot_for=None: seen.append(1) or {'drivers': [], 'sf_calls': 0})
    c.get('/api/call-story/replay-map?q=05164342')
    assert list(state['disk']) == [f'cs_map:{towbook_cascade_raw()["wo"]["Id"]}']
    state['store'].clear()                                       # the memory cache is gone, as after a restart
    call_story._RATE.clear()
    monkeypatch.setattr(call_story, 'pull_story', lambda *a, **k: towbook_cascade_raw())
    assert c.get('/api/call-story/replay-map?q=05164342').json() == {'drivers': [], 'sf_calls': 0} and len(seen) == 1


def test_open_call_map_is_never_written_to_disk(client, monkeypatch):
    from routers import call_story
    c, state = client
    monkeypatch.setattr(call_story, 'pull_story', lambda *a, **k: {**towbook_cascade_raw(), 'closed': False})
    monkeypatch.setattr('wo_replay_map.pull_map', lambda raw, puller=None, snapshot_for=None: {'drivers': [], 'sf_calls': 1})
    assert c.get('/api/call-story/replay-map?q=05164342').status_code == 200 and state['disk'] == {}


def test_replay_carries_where_and_meta(client):
    c, _ = client
    body = c.get('/api/call-story/replay?q=05164342').json()
    assert set(body['header']['where']) == {'member', 'garage'}
    assert body['meta']['cache'] == 'miss' and body['meta']['sf_calls'] == 8 and body['meta']['ms'] >= 0
    again = c.get('/api/call-story/replay?q=05164342').json()
    assert again['meta']['cache'] == 'hit' and again['meta']['sf_calls'] == 0
