"""Work Order Replay of a call that is still OPEN: the GPS window runs to now, and the other drivers come from the live call map."""

from datetime import datetime, timezone

from wo_replay_map import _hold_last, _windows
from wo_replay_peers import open_peers

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc)


def row(field, value, stamp, sa='M'):
    return {'ServiceAppointmentId': sa, 'Field': field, 'NewValue': value, 'CreatedDate': stamp}


def raw(closed=False):
    return {'closed': closed, 'sas': [{'Id': 'M', 'CreatedDate': '2026-10-07T16:50:00.000+0000', 'WorkType': {'Name': 'Tow'}}],
            'assigned': [{'ServiceResourceId': 'R0', 'ServiceResource': {'Name': 'Picked 100'}}],
            'history': [row('ERS_Assigned_Resource__c', 'Picked 100', '2026-10-07T17:00:00.000+0000'),
                        row('ERS_Assigned_Resource__c', '0HnPb0000000G8sKAE', '2026-10-07T17:00:00.000+0000'),
                        row('Status', 'Accepted', '2026-10-07T17:30:00.000+0000')]}


def test_an_open_call_follows_the_driver_who_holds_it_to_now_a_closed_one_stops_at_its_last_row():
    sa = raw()['sas'][0]
    open_end = _windows(raw(), ['Picked 100'], sa, now=NOW)['Picked 100'][1]
    closed_end = _windows(raw(closed=True), ['Picked 100'], sa, now=NOW)['Picked 100'][1]
    assert open_end == datetime(2026, 10, 7, 18, 5, tzinfo=timezone.utc)
    assert closed_end == datetime(2026, 10, 7, 17, 35, tzinfo=timezone.utc)        # last history row + 5 min


# ── the other drivers: the live call map's roster and our own GPS record ──

def live():
    q = {'sa': 'SA-7', 'work_type': 'Tow Pick-Up', 'label': 'driving to it', 'lat': 42.95, 'lon': -78.8}
    return {'sa': {'lat': 42.9, 'lon': -78.8}, 'peer_counts': {'not_qualified': 2}, 'peers': [
        {'id': 'R1', 'name': 'Ann Lee 100', 'queue': [{**q, 'given_at': '2026-10-07T16:00:00Z'}, {**q, 'sa': 'SA-8', 'given_at': '2026-10-07T17:20:00Z'}]},
        {'id': 'R2', 'name': 'Bo Two 100', 'queue': []},
        {'id': 'R3', 'name': 'No Record 100', 'queue': []},
        {'id': 'R4', 'name': 'Picked 100', 'queue': []}]}       # the call moved since: the first driver is a live peer now, but not a candidate at the time he got it


def fixes(rid, lat, lon, stamp):
    return [{'ServiceResourceId': rid, 'Field': 'LastKnownLatitude', 'NewValue': repr(lat), 'CreatedDate': stamp},
            {'ServiceResourceId': rid, 'Field': 'LastKnownLongitude', 'NewValue': repr(lon), 'CreatedDate': stamp}]


def store(window):
    rows = (fixes('R1', 42.95, -78.8, '2026-10-07T16:55:00.000+0000') + fixes('R1', 42.99, -78.8, '2026-10-07T17:10:00.000+0000')
            + fixes('R2', 42.92, -78.8, '2026-10-07T16:58:00.000+0000'))
    return rows, {i for i in window if i != 'R3'}                    # R3 is not covered by the record


def test_open_call_lists_live_qualified_drivers_at_their_recorded_position_at_each_moment(monkeypatch):
    monkeypatch.setattr('wo_replay_peers.is_on', lambda f: True)
    out = open_peers(raw(), live(), store)
    given, accepted = out['moments']
    assert (given['kind'], accepted['kind'], given['at']) == ('given', 'accepted', '2026-10-07T17:00:00Z')
    ann = next(d for d in given['drivers'] if d['name'] == 'Ann Lee')
    assert (ann['lat'], ann['held'], ann['status']) == (42.95, 1, 'busy')                       # the 16:55 fix; only the call given before 17:00
    ann2 = next(d for d in accepted['drivers'] if d['name'] == 'Ann Lee')
    assert (ann2['lat'], ann2['held']) == (42.99, 2)                                             # the 17:10 fix; both calls held at 17:30
    assert [d['name'] for d in given['drivers']] == ['Bo Two', 'Ann Lee'] and given['drivers'][0]['status'] == 'free'   # nearest first
    assert 'Picked' not in str(out['moments'])
    assert (given['no_gps'], given['not_qualified'], out['sf_calls']) == (1, 2, 0)              # the uncovered driver is counted, never guessed


def test_open_call_without_the_flag_a_roster_or_a_given_driver_has_no_peers(monkeypatch):
    monkeypatch.setattr('wo_replay_peers.is_on', lambda f: False)
    assert open_peers(raw(), live(), store) is None
    monkeypatch.setattr('wo_replay_peers.is_on', lambda f: True)
    assert open_peers(raw(), None, store) is None
    assert open_peers({**raw(), 'history': []}, live(), store) is None


def test_a_parked_driver_on_an_open_call_keeps_his_last_position_up_to_now():
    track = [[100, 42.9, -78.8], [160, 42.91, -78.81]]
    assert _hold_last(track, 400) == track + [[400, 42.91, -78.81]]
    assert _hold_last(track, 160) == track and _hold_last([], 400) == []
