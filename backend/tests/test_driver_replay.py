"""driver_replay.py: stops, names for them, re-timed track, day summary, and the API route. No Salesforce, no network."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import driver_replay as dr
from report_card_snapshot import build_snapshot
from tests.report_card_factories import tiny_raw

GARAGE = (42.9000, -78.8000)
SHOP = (42.9500, -78.8500)        # a made-up coffee shop
CALL = (42.9300, -78.7700)
T = 1_759_000_000


def east(lat, lon, m):            # a point m metres east
    return lat, lon + m / (111_320 * 0.733)


@pytest.fixture(autouse=True)
def places(monkeypatch):
    monkeypatch.setattr(dr.Places, '_grid', None)
    monkeypatch.setattr(dr, 'PLACES_FILE', '/nonexistent')
    dr.Places.grid()
    g = dr.Places._grid
    g.setdefault((int(SHOP[0] // dr.CELL), int(SHOP[1] // dr.CELL)), []).append((SHOP[0], SHOP[1], 'Tim Hortons', 'coffee'))
    yield
    monkeypatch.setattr(dr.Places, '_grid', None)


def day_track():
    """Garage 08:00-08:30 (pings every 2 min), drive, Tim Hortons from 08:50 with ONE ping, next ping 09:20 nearby, drive on."""
    tr = [[T + k * 120, GARAGE[0], GARAGE[1]] for k in range(16)]              # 08:00 .. 08:30
    for k in range(1, 9):                                                       # drive 08:32 .. 08:48
        f = k / 9
        tr.append([T + 1800 + k * 120, GARAGE[0] + (SHOP[0] - GARAGE[0]) * f, GARAGE[1] + (SHOP[1] - GARAGE[1]) * f])
    tr.append([T + 3000, *SHOP])                                                # 08:50 parked, no more pings
    tr.append([T + 4800, *east(*SHOP, 400)])                                    # 09:20, 400 m away: he just left
    tr.append([T + 4920, *east(*SHOP, 2000)])
    return tr


def test_find_stops_holds_a_single_ping_stop_until_shortly_before_the_next_ping():
    stops = dr.find_stops(day_track())
    assert len(stops) == 2
    garage, shop = stops
    assert garage['t0'] == T and T + 1800 <= garage['t1'] < T + 1920           # left between the last garage ping and the next one
    assert shop['t0'] == T + 3000
    assert T + 4800 - 60 <= shop['t1'] < T + 4800                               # 400 m at city speed is about 36 s


def test_short_stops_are_not_stops():
    tr = [[T, 42.9, -78.8], [T + 120, 42.9, -78.8], [T + 180, *east(42.9, -78.8, 1000)]]
    assert dr.find_stops(tr) == []


def test_retime_keeps_the_truck_parked_then_drives():
    tr = day_track()
    stops = dr.find_stops(tr)
    moved = dr.retime(tr, stops)
    assert len(moved) == len(tr) + 2                                            # a keyframe for leaving the garage and the shop
    k = next(i for i, p in enumerate(moved) if p[0] == stops[1]['t1'])
    assert moved[k][1:] == moved[k - 1][1:]                                     # still at the shop until then
    assert [p[0] for p in moved] == sorted(p[0] for p in moved)


def test_labels_call_beats_garage_beats_place():
    calls = [{'number': '12345', 'lat': CALL[0], 'lon': CALL[1], 'created': T, 'end': T + 7200, 'holds': [['D1', T, T + 7200]]}]
    g = {'lat': GARAGE[0], 'lon': GARAGE[1]}
    at = lambda p: {'lat': p[0], 'lon': p[1], 't0': T + 600, 't1': T + 1800}
    assert dr.label(at(CALL), 'D1', calls, g, {})['label'] == 'At call 12345'
    assert dr.label(at(GARAGE), 'D1', calls, g, {})['kind'] == 'garage'
    assert dr.label(at(SHOP), 'D1', calls, g, {}) == {'kind': 'coffee', 'label': 'Tim Hortons', 'place_kind': 'Coffee', 'place_m': 0}
    assert dr.label(at(east(*SHOP, 80)), 'D1', calls, g, {})['label'] == 'Near Tim Hortons'      # 80 m away: near, not at
    assert dr.label(at(east(*SHOP, 900)), 'D1', calls, g, {})['label'] == 'Unlisted stop'
    assert dr.label(at(east(*SHOP, 900)), 'D1', calls, g, {'lat': east(*SHOP, 900)[0], 'lon': east(*SHOP, 900)[1]})['kind'] == 'home'


def test_shift_keeps_only_this_days_logins_clipped_to_the_day():
    d = {'logins': [{'start': '2026-09-08T18:00:00Z', 'end': '2026-09-08T21:33:00Z'},     # the day before
                    {'start': '2026-09-09T02:00:00Z', 'end': '2026-09-09T06:00:00Z'},     # overnight, runs into the day
                    {'start': '2026-09-09T11:15:00Z', 'end': '2026-09-09T20:38:00Z'}]}
    d0, d1 = 1788926400, 1789012800                                                      # 2026-09-09 00:00 to 24:00 ET
    assert dr.shift(d, d0, d1) == [[d0, 1788933600], [1788952500, 1788986280]]


def test_another_drivers_call_is_not_at_a_call():
    calls = [{'number': '7', 'lat': CALL[0], 'lon': CALL[1], 'created': T, 'end': T + 7200, 'holds': [['D2', T, T + 7200]]}]
    s = {'lat': CALL[0], 'lon': CALL[1], 't0': T + 600, 't1': T + 1800}
    assert dr.label(s, 'D1', calls, {}, {})['kind'] == 'unknown'


def test_parked_outside_the_shift_is_off_shift_unless_it_is_a_call():
    s = {'lat': SHOP[0], 'lon': SHOP[1], 't0': T, 't1': T + 3600}
    assert dr.label(s, 'D1', [], {}, {}, [[T + 7200, T + 9000]])['label'] == 'Parked, off shift'
    assert dr.label(s, 'D1', [], {}, {}, [[T + 1800, T + 9000]])['kind'] == 'coffee'          # overlaps the shift


def test_back_to_back_stops_with_the_same_name_merge():
    a = {'t0': T, 't1': T + 360, 'label': 'At call 1', 'first': 0, 'last': 3}
    b = {'t0': T + 400, 't1': T + 1000, 'label': 'At call 1', 'first': 4, 'last': 8}
    c = {'t0': T + 1100, 't1': T + 1500, 'label': 'Sunoco', 'first': 9, 'last': 9}
    m = dr.merge([a, b, c])
    assert [(x['t0'], x['t1'], x['first'], x['last']) for x in m] == [(T, T + 1000, 0, 8), (T + 1100, T + 1500, 9, 9)]


def test_a_call_that_was_already_cleared_is_not_the_reason_for_a_later_stop():
    calls = [{'number': '9', 'lat': CALL[0], 'lon': CALL[1], 'created': T, 'end': T + 600, 'holds': [['D1', T, T + 600]]}]
    s = {'lat': CALL[0], 'lon': CALL[1], 't0': T + 3600, 't1': T + 4200}
    assert dr.label(s, 'D1', calls, {}, {})['kind'] != 'call'


def test_gaps_are_far_silences_only():
    tr = [[T, 42.9, -78.8], [T + 120, *east(42.9, -78.8, 500)], [T + 120 + 3600, *east(42.9, -78.8, 30000)]]
    assert dr.gaps(tr, dr.find_stops(tr)) == [[T + 120, T + 3720]]


def test_summary_splits_the_day():
    tr = day_track()
    stops = dr.find_stops(tr)
    for s in stops:
        s['kind'] = 'garage' if s['t0'] == T else 'coffee'
    s = dr.summary(tr, stops, [])
    assert s['stopped_s'] == {'garage': stops[0]['t1'] - T, 'coffee': stops[1]['t1'] - stops[1]['t0']}
    assert s['driving_s'] == tr[-1][0] - T - sum(s['stopped_s'].values())
    assert s['miles'] > 3


def test_places_file_loads_and_finds_a_real_new_york_place(monkeypatch):
    monkeypatch.setattr(dr.Places, '_grid', None)
    monkeypatch.setattr(dr, 'PLACES_FILE', dr.os.path.join(dr.os.path.dirname(dr.os.path.abspath(dr.__file__)), 'geo', 'ny_places.json'))
    g = dr.Places.grid()
    assert sum(len(v) for v in g.values()) > 10_000
    lat, lon, name, kind = next(p for v in g.values() for p in v if p[2] == 'Walmart')
    assert dr.Places.nearest(lat, lon)['name'] == 'Walmart'


# ── API ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

TID, DAY = '0HhFAKE00000001AAA', '2026-09-28'


@pytest.fixture
def client(monkeypatch, tmp_path):
    import feature_flags
    from routers import report_card
    monkeypatch.setenv('REPORT_CARD_STORE_DIR', str(tmp_path))
    monkeypatch.setattr(feature_flags, 'is_on', lambda name: name == 'scheduler_report_card')

    def fake_require(feature, request):
        if request.headers.get('x-test-role', 'admin') != 'admin':
            raise HTTPException(status_code=403, detail='Access restricted')
    monkeypatch.setattr(report_card, 'require_feature', fake_require)
    monkeypatch.setattr(report_card, '_check_territory_access', lambda request, tid: None)
    monkeypatch.setattr(report_card.cache, 'get', lambda key: None)
    monkeypatch.setattr(report_card.cache, 'put', lambda key, data, ttl=0: None)
    app = FastAPI()
    app.include_router(report_card.router)
    return TestClient(app)


def test_route_is_gated_and_reads_only_the_snapshot(client):
    import report_card_store as store
    url = f'/api/report-card/{TID}/{DAY}/driver-replay'
    assert client.get(url).status_code == 422                                   # no driver picked
    snap = build_snapshot(tiny_raw())
    assert client.get(url, params={'drivers': snap['drivers'][0]['id']}).json() == {'status': 'not_built'}
    store.save_snapshot(TID, DAY, snap)
    ids = ','.join(d['id'] for d in snap['drivers']) + ',bad id'
    r = client.get(url, params={'drivers': ids})
    assert r.status_code == 200
    got = r.json()['drivers']
    assert [d['id'] for d in got] == [d['id'] for d in snap['drivers']][:dr_max()]
    assert all(d['mode'] in ('gps', 'none') and isinstance(d['stops'], list) for d in got)
    assert client.get(url, params={'drivers': ids}, headers={'x-test-role': 'contractor'}).status_code == 403


def dr_max():
    from routers.report_card import DRIVER_REPLAY_MAX
    return DRIVER_REPLAY_MAX
