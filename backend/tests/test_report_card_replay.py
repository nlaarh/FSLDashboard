"""Day replay payload: driver tracks (GPS or estimated) and call holds, built from the snapshot only."""

from report_card_replay import _s, estimated_track, holds, parked, replay_view, vehicle
from report_card_snapshot import build_snapshot
from tests.report_card_factories import D1, D2, tiny_raw

SA1 = '08pFAKE00000001AAA'


def _snap(**gps):
    snap = build_snapshot(tiny_raw())
    for d in snap['drivers']:
        if d['id'] in gps:
            d['gps'] = gps[d['id']]
    return snap


def test_holds_follow_each_pick_until_the_next_or_the_end():
    snap = build_snapshot(tiny_raw())
    sa = next(s for s in snap['sas'] if s['id'] == SA1)
    end = _s(sa['milestones']['t_end'])
    # Picked to Driver Two at 16:00:30, re-picked to Driver One at 16:04, completed 17:10.
    assert holds(sa, end) == [[D2, _s('2026-09-28T16:00:30Z'), _s('2026-09-28T16:04:00Z')],
                              [D1, _s('2026-09-28T16:04:00Z'), end]]


def test_holds_skip_picks_to_drivers_off_the_roster():
    sa = {'events': [{'field': 'assigned', 'ts': '2026-09-28T16:00:00Z', 'driver_id': None},
                     {'field': 'assigned', 'ts': '2026-09-28T16:10:00Z', 'driver_id': 'X'}]}
    assert holds(sa, _s('2026-09-28T17:00:00Z')) == [['X', _s('2026-09-28T16:10:00Z'), _s('2026-09-28T17:00:00Z')]]


def test_estimated_track_drives_en_route_to_arrival_then_waits_on_scene():
    call = {'lat': 43.1, 'lon': -78.9, 'milestones': {'t_er': '2026-09-28T16:10:00Z', 'arrival': '2026-09-28T16:40:00Z',
                                                       't_end': '2026-09-28T17:10:00Z'}}
    assert estimated_track((43.0, -78.8), [call]) == [
        [_s('2026-09-28T16:10:00Z'), 43.0, -78.8],
        [_s('2026-09-28T16:40:00Z'), 43.1, -78.9],
        [_s('2026-09-28T17:10:00Z'), 43.1, -78.9]]


def test_estimated_track_never_goes_back_in_time_when_calls_overlap():
    a = {'lat': 43.1, 'lon': -78.9, 'milestones': {'t_er': '2026-09-28T16:00:00Z', 'arrival': '2026-09-28T16:30:00Z',
                                                    't_end': '2026-09-28T17:00:00Z'}}
    b = {'lat': 43.2, 'lon': -79.0, 'milestones': {'t_er': '2026-09-28T16:20:00Z', 'arrival': '2026-09-28T16:50:00Z',
                                                    't_end': '2026-09-28T17:20:00Z'}}
    times = [p[0] for p in estimated_track((43.0, -78.8), [b, a])]
    assert times == sorted(times)
    assert times[-1] == _s('2026-09-28T17:20:00Z')


def test_gps_drivers_use_real_pings_and_others_are_estimated():
    pings = [[_s('2026-09-28T15:00:00Z'), 43.0, -78.8], [_s('2026-09-28T15:30:00Z'), 43.05, -78.85],
             [_s('2026-09-27T10:00:00Z'), 40.0, -70.0]]  # outside the day window: dropped
    view = replay_view(_snap(**{D2: pings}))
    by_id = {d['id']: d for d in view['drivers']}
    assert by_id[D2]['mode'] == 'gps' and by_id[D2]['track'] == pings[:2]
    assert by_id[D1]['mode'] == 'estimated'     # one ping only, ran SA1
    assert _s('2026-09-28T16:40:00Z') in [p[0] for p in by_id[D1]['track']]


def test_calls_carry_only_in_day_sas_with_original_promise_and_rounded_location():
    view = replay_view(build_snapshot(tiny_raw()))
    assert {c['id'] for c in view['calls']} == {SA1, '08pFAKE00000004AAA'}
    c = next(c for c in view['calls'] if c['id'] == SA1)
    assert c['promise_due'] == _s('2026-09-28T17:00:00Z')   # original 60 min, not the re-based 120
    assert c['arrival'] == _s('2026-09-28T16:40:00Z')
    assert isinstance(c['lat'], float) and len(str(c['lat']).split('.')[1]) <= 4


def test_towbook_calls_become_estimated_vehicles_driving_garage_to_customer():
    """Towbook has no drivers or GPS in Salesforce: one estimated vehicle per call, between En Route and arrival."""
    snap = build_snapshot(tiny_raw())
    sa = next(s for s in snap['sas'] if s['id'] == SA1)
    sa['channel'], sa['final_driver_id'], sa['off_platform_driver'] = 'towbook', None, 'Sam Tow'   # a name exists in Salesforce; we still do not show it
    sa['events'] = [e for e in sa['events'] if e['field'] != 'assigned']
    snap['territory']['lat'], snap['territory']['lon'] = 42.9, -78.8
    view = replay_view(snap)
    veh = [d for d in view['drivers'] if d.get('towbook')]
    assert len(veh) == 1 and veh[0]['name'] == 'Towbook Driver 1' and veh[0]['mode'] == 'estimated' and veh[0]['gps_points'] == 0
    t_er, arr = _s(sa['milestones']['t_er']), _s(sa['milestones'].get('arrival') or sa['milestones']['t_ol'])
    terr = view['territory']
    assert veh[0]['track'][0] == [t_er, round(terr['lat'], 5), round(terr['lon'], 5)]       # leaves the garage when En Route
    assert veh[0]['track'][1][0] == arr and veh[0]['track'][1][1:] == [round(sa['lat'], 5), round(sa['lon'], 5)]
    call = next(c for c in view['calls'] if c['id'] == SA1)
    assert [veh[0]['id'], t_er] == call['holds'][-1][:2]


def test_on_platform_calls_get_no_towbook_vehicles():
    assert not [d for d in replay_view(_snap())['drivers'] if d.get('towbook')]


def test_towbook_garage_without_coordinates_gets_no_estimated_vehicles_and_does_not_crash():
    snap = build_snapshot(tiny_raw())
    sa = next(s for s in snap['sas'] if s['id'] == SA1)
    sa['channel'], sa['final_driver_id'] = 'towbook', None
    snap['territory']['lat'] = None
    assert not [d for d in replay_view(snap)['drivers'] if d.get('towbook')]


def test_estimated_drivers_are_parked_on_the_map_all_day_not_only_while_driving():
    track = [[1200, 43.0, -78.8], [1800, 43.1, -78.9]]
    assert parked(track, (43.0, -78.8), 1000, 2000) == [[1000, 43.0, -78.8], *track, [2000, 43.1, -78.9]]
    assert parked([], (43.0, -78.8), 1000, 2000) == [[1000, 43.0, -78.8], [2000, 43.0, -78.8]]   # no GPS and no calls: stays at the origin


def test_vehicle_is_the_last_truck_with_its_capabilities_and_the_drivers_skills():
    d = {'trucks': [{'start': '2026-09-28T08:00:00Z', 'truck': 'old', 'truck_caps': ['Tow']},
                    {'start': '2026-09-28T12:00:00Z', 'truck': '421 14F1', 'truck_caps': ['Flat Bed', 'Tow']}], 'skills': ['Battery']}
    assert vehicle(d) == {'truck': '421 14F1', 'skills': ['Battery', 'Flat Bed', 'Tow']}
    assert vehicle({}) == {'truck': None, 'skills': []}
