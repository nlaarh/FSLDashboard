"""Text thread mapping, and the extras / text-thread routes: gates, caching, logging, and what never leaves the server."""

import logging
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import replay_thread as rt
from tests.call_story_factories import towbook_cascade_raw

START, END = datetime(2026, 10, 7, 17, tzinfo=timezone.utc), datetime(2026, 10, 8, 2, tzinfo=timezone.utc)


def _entry(ms, role, text, **kw):
    return {'identifier': 'x', 'serverReceivedTimestamp': ms, 'clientTimestamp': ms, 'messageText': text, 'relatedRecords': ['0Mw1'],
            'sender': {'role': role, 'appType': 'live_message'}, **kw}


def test_entries_are_mapped_cleaned_and_sorted():
    body = {'conversationEntries': [
        _entry(1791420000000, 'Agent', 'We are on it &amp; <b>sending</b> a driver'),
        _entry(1791419000000, 'EndUser', 'Where is my driver?'),
        _entry(1791418000000, 'System', 'Your tow is on the way'),
        _entry(1791421000000, 'EndUser', ''),                    # empty: dropped
    ]}
    out = rt.map_entries(body)
    assert [e['who'] for e in out] == ['system', 'member', 'agent']
    assert out[2]['text'] == 'We are on it & sending a driver' and '&amp;' not in out[2]['text']
    assert out[1]['ts'] == '2026-10-08T00:23:20Z'            # 1791419000 s since the epoch
    assert rt.map_entries(None) == [] and rt.map_entries({}) == []


def test_fetch_is_one_get_per_conversation_with_millisecond_window(monkeypatch):
    seen = []
    monkeypatch.setattr(rt, 'sf_rest_get', lambda path, params=None: seen.append((path, params)) or {'conversationEntries': [_entry(1791419000000, 'EndUser', 'hi')]})
    entries, calls = rt.fetch_thread(['abc'], START, END)
    assert calls == 1 and len(entries) == 1
    assert seen == [('/connect/conversation/abc/entries', {'startTimestamp': int(START.timestamp() * 1000), 'endTimestamp': int(END.timestamp() * 1000)})]


@pytest.fixture
def client(monkeypatch, tmp_path):
    import feature_flags
    from routers import call_story, replay_extras
    state = {'flags': {'call_story': True, 'replay_member_contact': True}, 'pulls': 0, 'extras': 0, 'gets': 0}
    monkeypatch.setenv('REPORT_CARD_STORE_DIR', str(tmp_path))
    monkeypatch.setattr(feature_flags, 'is_on', lambda name: state['flags'].get(name, False))

    def fake_require(feature, request):
        if request.headers.get('x-test-role', 'admin') not in ('admin', 'executive'):
            raise HTTPException(status_code=403, detail='Access restricted')

    def fake_pull(q, cfg, now=None):
        state['pulls'] += 1
        return towbook_cascade_raw()

    def fake_extras(raw, promise, **kw):
        state['extras'] += 1
        return ({'calls': [], 'inbound_texts': [], 'driver_load': [], 'insights': [], 'notes': [], 'thread_available': True, 'sf_calls': 2},
                {'conversations': ['conv-1'], 'window': (START, END)})

    def fake_fetch(ids, start, end):
        state['gets'] += 1
        return [{'ts': '2026-10-07T21:03:20Z', 'who': 'member', 'text': 'hello'}], len(ids)
    store = {}
    for mod in (call_story, replay_extras):
        monkeypatch.setattr(mod, 'require_feature', fake_require)
    monkeypatch.setattr(call_story, '_check_territory_access', lambda request, tid: None)
    monkeypatch.setattr(call_story, 'pull_story', fake_pull)
    monkeypatch.setattr(call_story, '_norms', lambda d, cfg: None)
    monkeypatch.setattr(replay_extras, 'pull_extras', fake_extras)
    monkeypatch.setattr(replay_extras, 'fetch_thread', fake_fetch)
    monkeypatch.setattr(call_story.cache, 'get', lambda k: store.get(k))
    monkeypatch.setattr(call_story.cache, 'put', lambda k, v, ttl=0: store.__setitem__(k, v))
    monkeypatch.setattr(call_story.cache, 'disk_get', lambda k: None)
    monkeypatch.setattr(call_story.cache, 'disk_put', lambda k, v, ttl=0: pytest.fail('extras must never be written to disk'))
    state['store'] = store
    call_story._RATE.clear()
    app = FastAPI()
    app.include_router(call_story.router)
    app.include_router(replay_extras.router)
    return TestClient(app), state


def test_flag_and_permission_gates(client):
    c, state = client
    assert c.get('/api/call-story/extras?q=05164342', headers={'x-test-role': 'contractor'}).status_code == 403
    assert c.get('/api/call-story/text-thread?q=05164342', headers={'x-test-role': 'contractor'}).status_code == 403
    assert c.get('/api/call-story/extras?q=hello').status_code == 400
    state['flags']['replay_member_contact'] = False                     # the switch can still be turned off in Admin
    assert c.get('/api/call-story/extras?q=05164342').status_code == 404
    assert c.get('/api/call-story/text-thread?q=05164342').status_code == 404
    assert state['pulls'] == 0 and state['extras'] == 0


def test_extras_cached_second_call_costs_nothing_and_conversation_id_stays_server_side(client):
    c, state = client
    r1, r2 = c.get('/api/call-story/extras?q=05164342'), c.get('/api/call-story/extras?q=05164342')
    assert r1.status_code == 200 and r1.json()['cache'] == 'miss' and r1.json()['sf_calls'] == 2
    assert r2.json()['cache'] == 'hit' and r2.json()['sf_calls'] == 0 and state['extras'] == 1
    assert 'conv-1' not in r1.text and 'conv-1' not in r2.text


def test_thread_needs_extras_first_then_reads_on_click_logs_and_caches(client, caplog):
    c, state = client
    first = c.get('/api/call-story/text-thread?q=05164342')
    assert first.status_code == 409 and first.json() == {'status': 'load_extras_first'} and state['gets'] == 0
    c.get('/api/call-story/extras?q=05164342')
    assert state['gets'] == 0                                           # message bodies are not read with the extras
    with caplog.at_level(logging.INFO, logger='replay_extras'):
        r1 = c.get('/api/call-story/text-thread?q=05164342')
        r2 = c.get('/api/call-story/text-thread?q=05164342')
    assert r1.json() == {'entries': [{'ts': '2026-10-07T21:03:20Z', 'who': 'member', 'text': 'hello'}], 'sf_calls': 1}
    assert r2.json()['sf_calls'] == 0 and state['gets'] == 1
    views = [m for m in caplog.messages if m.startswith('text thread viewed user=')]
    assert len(views) == 2 and 'wo=05164342' in views[0]                  # every view is logged: who, which work order
