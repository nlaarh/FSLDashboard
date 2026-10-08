"""wo_replay_roads.py: moving runs, snapping pings to OSRM road vertices, thinning, garage route. OSRM is faked."""

import pytest

import wo_replay_roads as wr


def track(*steps):
    """[[t, lat, lon]] from (miles-ish step in lat) values: 0.01 deg of latitude is about 0.69 mi, 0.001 about 0.07 mi."""
    out, lat = [], 42.0
    for k, d in enumerate(steps):
        lat += d
        out.append([1000 + k * 60, round(lat, 5), -78.0])
    return [[1000 - 60, 42.0, -78.0]] + out


def test_pings_more_than_a_quarter_mile_apart_form_a_run_and_a_stop_splits_runs():
    t = track(0.01, 0.01, 0.0005, 0.01, 0.01, 0.01)               # move, move, stop, move, move, move
    runs = wr.moving_runs(t)
    assert [len(r) for r in runs] == [3, 4] and runs[0][0] == t[0] and runs[1][-1] == t[-1]


def test_a_parked_truck_has_no_runs_and_an_empty_track_is_fine():
    assert wr.moving_runs(track(0.0001, 0.0001, 0.0001)) == [] and wr.moving_runs([]) == []


def test_long_runs_are_cut_at_25_pings_and_pieces_share_an_end_ping():
    t = track(*[0.01] * 30)                                       # 31 pings, all moving
    runs = wr.moving_runs(t)
    assert [len(r) for r in runs] == [25, 7] and runs[0][-1] == runs[1][0]
    assert all(2 <= len(r) <= 25 for r in runs)


def test_a_single_far_step_is_a_two_ping_run():
    assert [len(r) for r in wr.moving_runs(track(0.01))] == [2]


def fake_route(coords_for):
    def route(points, timeout=8, cached=True):
        coords = coords_for(points)
        return coords and {'coords': coords, 'miles': 1.0, 'minutes': 2, 'snapped': [list(p) for p in points]}
    return route


def test_each_ping_gets_the_index_of_its_nearest_road_vertex_scanning_forward(monkeypatch):
    t = track(0.01, 0.01, 0.01)                                    # 4 pings, lat 42.0 .. 42.03
    # the road has a vertex every 0.005 lat plus a detour, so ping vertices are not simply 0, 2, 4, 6
    road = [[42.0 + 0.005 * k, -78.0] for k in range(7)]
    monkeypatch.setattr(wr.osrm, 'route', fake_route(lambda pts: road))
    out = wr.snap_runs(t)
    assert len(out) == 1 and out[0]['t'] == [p[0] for p in t] and out[0]['i'] == [0, 2, 4, 6] and out[0]['c'] == road


def test_a_run_osrm_cannot_route_stays_a_straight_line(monkeypatch):
    monkeypatch.setattr(wr.osrm, 'route', lambda *a, **k: None)
    assert wr.snap_runs(track(0.01, 0.01)) == []


def test_request_count_and_time_budget_are_respected(monkeypatch):
    calls = []
    monkeypatch.setattr(wr.osrm, 'route', lambda pts, timeout=8, cached=True: calls.append(timeout) or None)
    stops = [0.01, 0.0001] * 10                                    # many separate runs
    wr.snap_runs(track(*stops), max_requests=3)
    assert len(calls) == 3 and all(c <= 6 for c in calls)
    calls.clear()
    wr.snap_runs(track(*stops), budget_s=0)
    assert calls == []


def test_thin_keeps_every_ping_vertex_and_caps_the_vertex_count():
    coords = [[42.0 + k * 1e-4, -78.0] for k in range(10000)]
    out, idx = wr.thin(coords, [0, 4321, 9999])
    assert len(out) <= wr.MAX_VERTICES and [out[i] for i in idx] == [coords[0], coords[4321], coords[9999]] and idx == sorted(idx)
    short, same = wr.thin(coords[:5], [1, 3])
    assert short == coords[:5] and same == [1, 3]


def test_a_thinned_run_still_points_every_ping_at_its_own_vertex(monkeypatch):
    road = [[42.0 + k * 1e-4, -78.0] for k in range(5000)]
    t = [[1000, road[0][0], -78.0], [1060, road[2500][0], -78.0], [1120, road[4999][0], -78.0]]
    monkeypatch.setattr(wr.osrm, 'route', fake_route(lambda pts: road))
    out = wr.snap_runs(t)[0]
    assert len(out['c']) <= wr.MAX_VERTICES and [out['c'][i] for i in out['i']] == [road[0], road[2500], road[4999]]


def test_garage_route_returns_vertices_miles_and_minutes(monkeypatch):
    monkeypatch.setattr(wr.osrm, 'route', fake_route(lambda pts: [[1.0, 2.0], [3.0, 4.0]]))
    assert wr.garage_route({'lat': 1.0, 'lon': 2.0}, {'lat': 3.0, 'lon': 4.0}) == {'c': [[1.0, 2.0], [3.0, 4.0]], 'miles': 1.0, 'minutes': 2}


@pytest.mark.parametrize('g, m', [(None, {'lat': 1, 'lon': 2}), ({'lat': 1, 'lon': 2}, None)])
def test_garage_route_without_both_ends_is_none(g, m, monkeypatch):
    monkeypatch.setattr(wr.osrm, 'route', lambda *a, **k: pytest.fail('no request without both ends'))
    assert wr.garage_route(g, m) is None
