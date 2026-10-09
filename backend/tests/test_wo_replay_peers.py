"""wo_replay_peers.py: the other qualified, on-shift drivers when the call was given, from the day snapshot (no Salesforce)."""

from wo_replay_peers import build_peers, pull_peers

T_ASG, T_ACC = '2026-10-07T17:00:00Z', '2026-10-07T17:30:00Z'


def epoch(iso):
    from utils import parse_dt
    return int(parse_dt(iso).timestamp())


def sa(sid, driver=None, lat=None, lon=None, drop=False, skills=(), er=None, ol=None, busy=None, end=None, channel='fleet', asg=T_ASG, acc=T_ACC):
    return {'id': sid, 'is_drop_off': drop, 'final_driver_id': driver, 'lat': lat, 'lon': lon, 'required_skills': list(skills), 'channel': channel,
            'busy': busy, 'milestones': {'t_asg': asg, 't_acc': acc, 't_er': er, 't_ol': ol, 't_end': end, 'actual_end': None}}


def drv(did, name, skills=('Tow',), caps=(), on=True, gps=True, member=True, absent=False):
    return {'id': did, 'name': name, 'member': member, 'skills': list(skills),
            'logins': [{'start': '2026-10-07T12:00:00Z', 'end': '2026-10-07T23:00:00Z'}] if on else [],
            'absences': [{'start': '2026-10-07T16:00:00Z', 'end': '2026-10-07T20:00:00Z', 'type': 'Break'}] if absent else [],
            'trucks': [{'start': '2026-10-07T12:00:00Z', 'end': '2026-10-07T23:00:00Z', 'truck_caps': list(caps)}],
            'gps': [[epoch('2026-10-07T16:50:00Z'), 42.95, -78.8]] if gps else []}


def snap(drivers, sas, **kw):
    return {'drivers': drivers, 'sas': sas, **kw}


MEMBER = sa('M', driver='D0', lat=42.9, lon=-78.8, skills=['Tow'])


def test_only_qualified_on_shift_drivers_with_gps_are_listed_and_the_rest_counted():
    s = snap([drv('D0', 'Picked 100'), drv('D1', 'Ann Lee 100'), drv('D2', 'No Skill 100', skills=('Battery',)),
              drv('D3', 'Off Shift 100', on=False), drv('D4', 'On Break 100', absent=True), drv('D5', 'No Gps 100', gps=False),
              drv('D6', 'Not Roster 100', member=False)], [MEMBER])
    out = build_peers(s, 'M')
    m = out['moments'][0]
    assert [d['name'] for d in m['drivers']] == ['Ann Lee']
    assert (m['not_qualified'], m['no_gps']) == (1, 1)
    assert m['drivers'][0]['miles'] == 3.5 and m['drivers'][0]['status'] == 'free' and m['drivers'][0]['held'] == 0


def test_truck_capability_counts_towards_qualification_like_the_verdicts():
    d = drv('D1', 'Truck Man 100', skills=(), caps=('Tow',))
    assert [x['name'] for x in build_peers(snap([drv('D0', 'P 1'), d], [MEMBER]), 'M')['moments'][0]['drivers']] == ['Truck Man']


def test_status_and_calls_held_come_from_the_drivers_other_calls():
    busy = lambda a, b: [a, b]
    sas = [MEMBER,
           sa('J1', 'D1', skills=['Tow'], er='2026-10-07T16:40:00Z', ol='2026-10-07T16:50:00Z', busy=busy('2026-10-07T16:30:00Z', '2026-10-07T17:30:00Z')),
           sa('J2', 'D2', er='2026-10-07T16:50:00Z', busy=busy('2026-10-07T16:30:00Z', '2026-10-07T17:30:00Z')),
           sa('J3', 'D3', busy=busy('2026-10-07T16:30:00Z', '2026-10-07T17:30:00Z')),
           sa('J4', 'D3', busy=busy('2026-10-07T16:31:00Z', '2026-10-07T17:30:00Z')),
           sa('X5', 'D4', drop=True, er='2026-10-07T16:55:00Z', end='2026-10-07T17:20:00Z')]
    drivers = [drv('D0', 'P 1')] + [drv(f'D{i}', f'N{i} 100') for i in range(1, 6)]
    got = {d['name']: d for d in build_peers(snap(drivers, sas), 'M')['moments'][0]['drivers']}
    assert (got['N1']['status'], got['N1']['held']) == ('on_location', 1)
    assert got['N2']['status'] == 'en_route'
    assert (got['N3']['status'], got['N3']['held']) == ('waiting', 2)
    assert (got['N4']['status'], got['N4']['label'], got['N4']['held']) == ('towing', 'towing', 0)
    assert got['N5']['status'] == 'free'


def test_sorted_by_distance_and_picked_driver_and_the_members_own_call_are_excluded():
    far = drv('D2', 'Far 100'); far['gps'] = [[epoch('2026-10-07T16:50:00Z'), 43.5, -78.8]]
    out = build_peers(snap([drv('D0', 'Picked 1'), far, drv('D1', 'Near 100')], [MEMBER, sa('M', 'D0')]), 'M')
    assert [d['name'] for d in out['moments'][0]['drivers']] == ['Near', 'Far']


def test_accept_is_a_second_moment_only_when_it_came_later():
    assert [m['kind'] for m in build_peers(snap([drv('D0', 'P 1')], [MEMBER]), 'M')['moments']] == ['given', 'accepted']
    one = sa('M', 'D0', lat=42.9, lon=-78.8, acc=None)
    assert [m['kind'] for m in build_peers(snap([drv('D0', 'P 1')], [one]), 'M')['moments']] == ['given']


def test_a_stale_gps_fix_is_not_placed():
    old = drv('D1', 'Old Fix 100'); old['gps'] = [[epoch('2026-10-07T15:00:00Z'), 42.95, -78.8]]
    m = build_peers(snap([drv('D0', 'P 1'), old], [MEMBER]), 'M')['moments'][0]
    assert m['drivers'] == [] and m['no_gps'] == 1


def test_towbook_garage_lists_nobody_and_says_why():
    out = build_peers(snap([drv('D1', 'Ann Lee 100')], [sa('M', channel='towbook', lat=1, lon=1)]), 'M')
    assert out['available'] is False and out['moments'] == [] and 'Towbook' in out['notes'][0]


def test_no_snapshot_is_reported_not_guessed():
    out = build_peers(None, 'M')
    assert out['available'] is False and 'not been built' in out['notes'][0]


def test_pull_peers_reads_the_snapshot_of_the_members_garage_and_day_with_zero_salesforce_calls():
    seen = []
    raw = {'sas': [{'Id': 'M', 'WorkType': {'Name': 'Tow'}, 'ServiceTerritoryId': 'T1', 'CreatedDate': '2026-10-08T02:30:00.000+0000'}]}
    out = pull_peers(raw, lambda t, d: seen.append((t, d)) or snap([drv('D0', 'P 1'), drv('D1', 'Ann Lee 100')], [MEMBER]))
    assert seen == [('T1', '2026-10-07')]      # 10:30 PM Eastern on the 7th, not the 8th
    assert out['sf_calls'] == 0 and out['moments'][0]['drivers'][0]['name'] == 'Ann Lee'


def test_each_driver_carries_the_queue_he_held_in_order_and_what_he_did_next():
    def job(sid, n, asg, **kw):
        return {**sa(sid, 'D1', lat=42.95, lon=-78.8, asg=asg, **kw), 'number': n, 'work_type': 'Tow Pick-Up'}
    drop = {**sa('X1', 'D1', drop=True, er='2026-10-07T16:55:00Z', end='2026-10-07T17:20:00Z', asg='2026-10-07T16:20:00Z'), 'number': 'SA-3'}
    sas = [MEMBER,
           job('J1', 'SA-1', '2026-10-07T16:10:00Z', er='2026-10-07T16:20:00Z', ol='2026-10-07T16:40:00Z', busy=['2026-10-07T16:10:00Z', '2026-10-07T17:30:00Z']),
           job('J2', 'SA-2', '2026-10-07T16:45:00Z', busy=['2026-10-07T16:45:00Z', '2026-10-07T17:30:00Z']),
           drop,
           job('J9', 'SA-9', '2026-10-07T17:10:00Z', ol='2026-10-07T17:35:00Z', busy=['2026-10-07T17:10:00Z', '2026-10-07T18:00:00Z'])]
    d = build_peers(snap([drv('D0', 'P 1'), drv('D1', 'Ann Lee 100')], sas), 'M')['moments'][0]['drivers'][0]
    assert [(j['sa'], j['label']) for j in d['queue']] == [('SA-1', 'on scene'), ('SA-3', 'towing'), ('SA-2', 'not started')]
    assert d['queue'][0]['miles'] == 3.5 and d['queue'][1]['miles'] is None and d['queue'][0]['given_at'] == '2026-10-07T16:10:00Z'
    assert (d['next']['sa'], d['next']['given_at'], d['next']['reached_at']) == ('SA-9', '2026-10-07T17:10:00Z', '2026-10-07T17:35:00Z')


def test_a_towbook_call_is_recognised_from_the_story_without_a_snapshot():
    raw = {'sas': [{'Id': 'M', 'WorkType': {'Name': 'Tow'}, 'ServiceTerritoryId': 'T1', 'CreatedDate': '2026-10-07T17:00:00.000+0000', 'Off_Platform_Driver__r': {'Name': 'Secret Name'}}], 'history': []}
    out = pull_peers(raw, lambda *a: (_ for _ in ()).throw(AssertionError('no snapshot read needed')))
    assert out['channel'] == 'towbook' and 'Secret Name' not in str(out) and out['sf_calls'] == 0
