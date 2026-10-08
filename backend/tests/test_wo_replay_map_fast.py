"""wo_replay_map.py fast paths: ids from history, garage from the story, GPS from a built snapshot, per-driver windows."""

from calendar import timegm
from time import strptime

import pytest

from wo_replay_map import _paired_ids, _windows, locate, pull_map


@pytest.fixture(autouse=True)
def no_roads(monkeypatch):
    """Roads come from OSRM (tests/test_wo_replay_roads.py); here nothing may touch the network."""
    monkeypatch.setattr('wo_replay_map.garage_route', lambda *a, **k: None)
    monkeypatch.setattr('wo_replay_map.snap_runs', lambda *a, **k: [])


def epoch(hhmm, day='2026-09-28'):
    return timegm(strptime(f'{day} {hhmm}', '%Y-%m-%d %H:%M'))


class FakePuller:
    def __init__(self, gps=None):
        self.calls, self.queries, self.gps = 0, [], gps or []

    def all(self, soql):
        self.calls += 1
        self.queries.append(soql)
        return self.gps


def swap(ts, new, old=None, sa='SA1'):
    return {'ServiceAppointmentId': sa, 'Field': 'ERS_Assigned_Resource__c', 'OldValue': old, 'NewValue': new, 'CreatedDate': f'2026-09-28T{ts}:00.000+0000'}


def raw(**over):
    r = {
        'sas': [{'Id': 'SA1', 'WorkType': {'Name': 'Battery'}, 'Latitude': 42.92475, 'Longitude': -78.896304, 'ServiceTerritoryId': 'T1',
                 'CreatedDate': '2026-09-28T15:00:00.000+0000', 'ServiceTerritory': {'Name': '100 - Fleet', 'Latitude': 42.9, 'Longitude': -78.8}}],
        'history': [swap('15:10', 'Al One 100'), swap('15:10', '0HnAAAAAAAAAAAAAAA'),
                    {'ServiceAppointmentId': 'SA1', 'Field': 'ServiceTerritory', 'NewValue': '0HhBBBBBBBBBBBBBBB', 'CreatedDate': '2026-09-28T15:01:00.000+0000'},
                    {'ServiceAppointmentId': 'SA1', 'Field': 'Status', 'NewValue': 'On Location', 'CreatedDate': '2026-09-28T15:50:00.000+0000'},
                    {'ServiceAppointmentId': 'SA1', 'Field': 'Status', 'NewValue': 'Completed', 'CreatedDate': '2026-09-28T16:30:00.000+0000'}],
        'assigned': [],
    }
    r.update(over)
    return r


def snap(built_at='2026-09-29T08:00:00Z', gps=None, rid='0HnAAAAAAAAAAAAAAA'):
    pts = gps if gps is not None else [[epoch('15:20'), 42.91, -78.81], [epoch('15:30'), 42.92, -78.82], [epoch('17:00'), 40.0, -70.0]]
    return {'built_at': built_at, 'drivers': [{'id': rid, 'gps': pts}]}


def test_ids_pair_up_from_the_history_without_a_serviceresource_query():
    assert _paired_ids(raw()) == {'Al One 100': '0HnAAAAAAAAAAAAAAA'}
    p = FakePuller()
    pull_map(raw(), p)
    assert not any('FROM ServiceResource WHERE' in q for q in p.queries)


def test_an_id_row_at_another_time_is_not_paired():
    r = raw(history=[swap('15:10', 'Al One 100'), swap('15:12', '0HnAAAAAAAAAAAAAAA')])
    assert _paired_ids(r) == {}


def test_garage_comes_from_the_story_and_no_territory_query_is_sent():
    p = FakePuller()
    m = pull_map(raw(), p)
    assert m['garage'] == {'name': '100 - Fleet', 'lat': 42.9, 'lon': -78.8}
    assert not any('FROM ServiceTerritory' in q for q in p.queries)


def test_locate_has_member_and_garage_and_none_without_territory_coordinates():
    assert locate(raw()) == {'member': {'lat': 42.9248, 'lon': -78.8963}, 'garage': {'name': '100 - Fleet', 'lat': 42.9, 'lon': -78.8}}
    r = raw()
    r['sas'][0].pop('ServiceTerritory')
    assert locate(r)['garage'] is None


def test_gps_from_a_built_snapshot_costs_no_salesforce_call():
    asked = []
    p = FakePuller()
    m = pull_map(raw(), p, snapshot_for=lambda t, d: asked.append((t, d)) or snap())
    d = m['drivers'][0]
    assert p.calls == 0 and m['sf_calls'] == 0 and d['source'] == 'snapshot'
    assert d['track'] == [[epoch('15:20'), 42.91, -78.81], [epoch('15:30'), 42.92, -78.82]]       # the 17:00 ping is outside the window
    assert asked[0] == ('T1', '2026-09-28')                                                       # the Eastern date of the SA's creation


def test_snapshot_territories_are_the_legs_garage_plus_history_garages_at_most_three():
    r = raw()
    r['history'] += [{'ServiceAppointmentId': 'SA1', 'Field': 'ServiceTerritory', 'NewValue': f'0Hh{n}CCCCCCCCCCC', 'CreatedDate': '2026-09-28T15:02:00.000+0000'} for n in range(4)]
    asked = []
    pull_map(r, FakePuller(), snapshot_for=lambda t, d: asked.append(t))
    assert asked == ['T1', '0HhBBBBBBBBBBBBBBB', '0Hh0CCCCCCCCCCC']


def test_a_snapshot_built_before_the_window_ends_is_not_used():
    p = FakePuller()
    m = pull_map(raw(), p, snapshot_for=lambda t, d: snap(built_at='2026-09-28T15:54:00Z'))      # driver's window ends 15:55 (On Location 15:50 + 5 min)
    assert p.calls == 1 and m['drivers'][0]['source'] == 'salesforce'


def test_a_driver_with_too_few_snapshot_points_goes_to_salesforce():
    p = FakePuller()
    m = pull_map(raw(), p, snapshot_for=lambda t, d: snap(gps=[[epoch('15:20'), 42.91, -78.81]]))
    assert p.calls == 1 and 'ServiceResourceHistory' in p.queries[0] and m['drivers'][0]['source'] == 'salesforce'


def test_a_driver_not_in_the_snapshot_goes_to_salesforce():
    p = FakePuller()
    pull_map(raw(), p, snapshot_for=lambda t, d: snap(rid='0HnZZZZZZZZZZZZZZZ'))
    assert p.calls == 1


def test_only_drivers_missing_from_the_snapshot_are_queried_each_with_their_own_window():
    r = raw(history=[swap('15:10', 'Al One 100'), swap('15:10', '0HnAAAAAAAAAAAAAAA'),
                     swap('15:40', 'Bo Two 100', old='Al One 100'), swap('15:40', '0HnBBBBBBBBBBBBBBB', old='0HnAAAAAAAAAAAAAAA'),
                     {'ServiceAppointmentId': 'SA1', 'Field': 'Status', 'NewValue': 'On Location', 'CreatedDate': '2026-09-28T16:10:00.000+0000'}])
    p = FakePuller()
    m = pull_map(r, p, snapshot_for=lambda t, d: snap())
    by = {d['name']: d for d in m['drivers']}
    assert by['Al One']['source'] == 'snapshot' and by['Bo Two']['source'] == 'salesforce' and p.calls == 1
    q = p.queries[0]
    assert "'0HnBBBBBBBBBBBBBBB'" in q and "'0HnAAAAAAAAAAAAAAA'" not in q
    assert 'CreatedDate >= 2026-09-28T15:10:00Z' in q and 'CreatedDate <= 2026-09-28T16:15:00Z' in q       # first pick - 30 min .. On Location + 5 min


def test_window_ends_at_the_unassignment_for_a_driver_who_was_replaced():
    r = raw(history=[swap('15:10', 'Al One 100'), swap('15:40', 'Bo Two 100', old='Al One 100'),
                     {'ServiceAppointmentId': 'SA1', 'Field': 'Status', 'NewValue': 'On Location', 'CreatedDate': '2026-09-28T16:10:00.000+0000'}])
    w = _windows(r, ['Al One 100', 'Bo Two 100'], r['sas'][0])
    assert [t.strftime('%H:%M') for t in w['Al One 100']] == ['14:40', '15:45']
    assert [t.strftime('%H:%M') for t in w['Bo Two 100']] == ['15:10', '16:15']


def test_window_without_on_location_ends_at_the_last_history_row_and_assigned_only_drivers_get_the_whole_call():
    r = raw(history=[swap('15:10', 'Al One 100'), {'ServiceAppointmentId': 'SA1', 'Field': 'Status', 'NewValue': 'Completed', 'CreatedDate': '2026-09-28T16:30:00.000+0000'}])
    w = _windows(r, ['Al One 100', 'Cy Three 100'], r['sas'][0])
    assert w['Al One 100'][1].strftime('%H:%M') == '16:35' and w['Cy Three 100'][0].strftime('%H:%M') == '14:40'


def test_map_carries_a_road_per_driver_with_a_track_and_the_garage_route(monkeypatch):
    road = [{'t': [1, 2], 'i': [0, 1], 'c': [[1.0, 2.0], [3.0, 4.0]]}]
    monkeypatch.setattr('wo_replay_map.snap_runs', lambda track, budget_s=6, max_requests=6: road if track else [])
    monkeypatch.setattr('wo_replay_map.garage_route', lambda g, m, timeout=6: {'c': [[g['lat'], g['lon']]], 'miles': 1.0, 'minutes': 2})
    m = pull_map(raw(), FakePuller(), snapshot_for=lambda t, d: snap())
    assert m['drivers'][0]['road'] == road and m['roads']['garage_to_member']['c'] == [[42.9, -78.8]]
    m = pull_map(raw(), FakePuller(), snapshot_for=lambda t, d: snap(gps=[]))        # no track: nothing to snap
    assert m['drivers'][0]['road'] == [] and m['drivers'][0]['track'] == []


def test_unpaired_names_still_use_the_serviceresource_query():
    class P(FakePuller):
        def all(self, soql):
            if 'FROM ServiceResource WHERE' in soql:
                self.calls += 1
                self.queries.append(soql)
                return [{'Id': '0HnQQQQQQQQQQQQQQQ', 'Name': 'Al One 100'}]
            return super().all(soql)
    p = P()
    pull_map(raw(history=[swap('15:10', 'Al One 100')]), p)
    assert any('FROM ServiceResource WHERE' in q for q in p.queries) and any("'0HnQQQQQQQQQQQQQQQ'" in q for q in p.queries)
