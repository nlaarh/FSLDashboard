"""wo_replay_map.py: locations for the replay. Fake Salesforce, no I/O."""

import pytest

from wo_replay_map import driver_names, pull_map


@pytest.fixture(autouse=True)
def no_roads(monkeypatch):
    """Roads come from OSRM (tests/test_wo_replay_roads.py); here nothing may touch the network."""
    monkeypatch.setattr('wo_replay_map.garage_route', lambda *a, **k: None)
    monkeypatch.setattr('wo_replay_map.snap_runs', lambda *a, **k: [])


class FakePuller:
    def __init__(self, gps=None, fail_gps=False):
        self.calls, self.queries, self.gps, self.fail_gps = 0, [], gps or [], fail_gps

    def all(self, soql):
        self.calls += 1
        self.queries.append(soql)
        if 'FROM ServiceResource WHERE' in soql:
            return [{'Id': 'R2', 'Name': 'Bo Two 100'}]
        if 'FROM ServiceTerritory' in soql:
            return [{'Id': 'T0', 'Name': 'First - Other', 'Latitude': 1.0, 'Longitude': 1.0},
                    {'Id': 'T1', 'Name': '100 - Fleet', 'Latitude': 42.9, 'Longitude': -78.8}]
        if self.fail_gps:
            raise RuntimeError('timeout')
        return self.gps


def raw():
    return {
        'sas': [{'WorkType': {'Name': 'Tow Drop-off'}, 'Latitude': 1.0, 'Longitude': 1.0, 'ServiceTerritoryId': 'T0', 'CreatedDate': '2026-09-28T15:00:00.000+0000'},
                {'WorkType': {'Name': 'Battery'}, 'Latitude': 42.92475, 'Longitude': -78.896304, 'ServiceTerritoryId': 'T1', 'CreatedDate': '2026-09-28T15:00:00.000+0000'}],
        'history': [{'Field': 'ERS_Assigned_Resource__c', 'NewValue': 'Bo Two 100', 'CreatedDate': '2026-09-28T15:10:00.000+0000'},
                    {'Field': 'ERS_Assigned_Resource__c', 'NewValue': 'Towbook-076DO 076DO', 'CreatedDate': '2026-09-28T15:11:00.000+0000'},
                    {'Field': 'ERS_Assigned_Resource__c', 'NewValue': '0HnPb0000000G8sKAE', 'CreatedDate': '2026-09-28T15:12:00.000+0000'},
                    {'Field': 'Status', 'NewValue': 'Completed', 'CreatedDate': '2026-09-28T16:00:00.000+0000'}],
        'assigned': [{'ServiceResourceId': 'R1', 'ServiceResource': {'Name': 'Al One 100'}}],
    }


def pings(rid, n):
    out = []
    for k in range(n):
        ts = f'2026-09-28T15:{10 + k * 5:02d}:00.000+0000'
        out += [{'ServiceResourceId': rid, 'Field': 'LastKnownLatitude', 'NewValue': str(42.9 + k * 0.01), 'CreatedDate': ts},
                {'ServiceResourceId': rid, 'Field': 'LastKnownLongitude', 'NewValue': str(-78.9 + k * 0.01), 'CreatedDate': ts}]
    return out


def test_driver_names_skip_ids_towbook_placeholders_and_spot():
    r = raw(); r['history'].append({'Field': 'ERS_Assigned_Resource__c', 'NewValue': '000-ST SPOT', 'CreatedDate': '2026-09-28T15:20:00.000+0000'})
    assert driver_names(r) == ['Al One 100', 'Bo Two 100']


def test_map_has_member_location_rounded_garage_and_tracks_per_driver():
    p = FakePuller(gps=pings('R1', 4) + pings('R2', 1))
    m = pull_map(raw(), p)
    assert m['wo'] == {'lat': 42.9248, 'lon': -78.8963}                      # about 11 m, from the member leg not the drop-off
    assert m['garage']['name'] == '100 - Fleet'                              # the member leg's garage, not the first row
    by = {d['name']: d for d in m['drivers']}
    assert len(by['Al One']['track']) == 4 and by['Bo Two']['track'] == []     # one ping is not a track
    assert any('No GPS pings for Bo Two' in n for n in m['notes'])
    assert m['sf_calls'] == p.calls <= 4


def test_gps_query_is_bounded_to_the_call_and_the_few_drivers():
    p = FakePuller(gps=pings('R1', 3))
    pull_map(raw(), p)
    q = p.queries[-1]
    assert 'ServiceResourceHistory' in q and "'R1'" in q and "'R2'" in q
    assert 'CreatedDate >= 2026-09-28T14:40:00Z' in q and 'CreatedDate <= 2026-09-28T16:05:00Z' in q


def test_gps_timeout_is_a_note_not_a_crash_and_nothing_is_guessed():
    m = pull_map(raw(), FakePuller(fail_gps=True))
    assert all(d['track'] == [] for d in m['drivers']) and any('could not be read' in n for n in m['notes'])


def test_no_location_on_the_work_order_is_reported():
    r = raw(); r['sas'][1]['Latitude'] = None
    assert pull_map(r, FakePuller())['wo'] is None


def test_towbook_leg_has_no_driver_location_and_says_so():
    r = raw()
    r['assigned'] = []                                   # the garage took it through Towbook: no On-Platform driver at all
    r['history'] = [{'Field': 'ERS_Assigned_Resource__c', 'NewValue': 'Towbook-076DO 076DO', 'CreatedDate': '2026-09-28T15:11:00.000+0000'}]
    r['sas'][1]['Off_Platform_Driver__r'] = {'Name': 'Sam Tow'}
    r['sas'][1]['Off_Platform_Truck_Id__c'] = 'T-9'
    p = FakePuller(gps=pings('R1', 4))
    m = pull_map(r, p)
    assert m['drivers'] == [] and m['towbook'] == {'driver': 'Towbook Driver', 'truck': 'T-9'}      # Salesforce has a name; we never return it
    assert 'Sam Tow' not in str(m)
    assert any('Towbook does not report driver location' in n for n in m['notes'])
    assert not any('ServiceResourceHistory' in q for q in p.queries)      # no GPS read when there is nobody to track
    assert m['wo'] and m['garage']                                         # the member and garage are still drawn


def test_on_platform_call_has_no_towbook_block():
    r = raw()
    r['history'] = [h for h in r['history'] if not str(h['NewValue']).startswith('Towbook-')]
    assert pull_map(r, FakePuller(gps=pings('R1', 3)))['towbook'] is None
