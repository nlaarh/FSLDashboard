"""wo_replay_why.py: why the driver changed. Synthetic snapshot and steps, no I/O."""

from wo_replay_why import attach_why, pick_trail


def cand(d, mi, q=1, sh=1, oj=1, age=-1.0):
    return [d, 42.9, -78.8, mi, q, sh, oj, age, 1]


def snap_and_sa():
    snap = {'drivers': [{'id': 'D1', 'name': 'Al One 100'}, {'id': 'D2', 'name': 'Bo Two 100'}, {'id': 'D3', 'name': 'Cy Three 100'}]}
    sa = {'events': [{'field': 'assigned', 'driver_id': 'D1', 'driver': 'Al One 100'}, {'field': 'assigned', 'driver_id': 'D2', 'driver': 'Bo Two 100'},
                     {'field': 'assigned', 'driver_id': 'D3', 'driver': 'Cy Three 100'}],
          'candidate_sets': [
              {'event_idx': 0, 'ts': '2026-09-28T15:00:00.000Z', 'c': [cand('D1', 3.0), cand('D2', 4.0, oj=2), cand('D3', 6.0), cand('D9', None, q=0, sh=0, oj=0)]},
              {'event_idx': 1, 'ts': '2026-09-28T15:01:00.000Z', 'c': [cand('D1', 3.0), cand('D2', 4.0, oj=1), cand('D3', 6.0)]},
              {'event_idx': 2, 'ts': '2026-09-28T15:05:00.000Z', 'c': [cand('D1', 5.0), cand('D2', 4.1), cand('D3', 2.5)]}]}
    return snap, sa


def step(ts, title, driver=None, role='FSL optimizer', detail=''):
    return {'ts': ts, 'title': title, 'names': {'driver': driver} if driver else {}, 'role': role, 'actor': 'x', 'detail': detail}


def test_trail_keeps_only_drivers_with_a_fresh_position_and_the_pick():
    snap, sa = snap_and_sa()
    t = pick_trail(snap, sa)
    assert len(t) == 3 and [c['name'] for c in t[0]['cands']] == ['Al One', 'Bo Two', 'Cy Three']      # D9 has no GPS and was not picked
    assert t[0]['picked'] == 'Al One' and t[1]['picked'] == 'Bo Two'


def test_first_pick_repick_became_available_and_closer():
    snap, sa = snap_and_sa()
    steps = [step('2026-09-28T15:00:00.000Z', 'Assigned to Al One', 'Al One', 'FSL auto-schedule'),
             step('2026-09-28T15:01:00.000Z', 'Assigned to Bo Two', 'Bo Two'),
             step('2026-09-28T15:05:00.000Z', 'Assigned to Cy Three', 'Cy Three')]
    attach_why(steps, pick_trail(snap, sa))
    w0, w1, w2 = (s['why'] for s in steps)
    assert w0['headline'].startswith('First pick: FSL auto-schedule') and 'This was the closest qualified driver' in w0['lines']
    assert w1['headline'] == 'FSL optimizer re-ran and chose a different driver'
    assert any('Bo Two became available since the last pick (2 open jobs to 1 open job)' in l for l in w1['lines'])
    assert any('Cy Three is closer (2.5 mi against 4.1 mi)' in l for l in w2['lines'])
    assert w2['source'] == 'candidates'


def test_rejection_between_picks_is_the_reason_and_carries_salesforces_own_reason_text():
    snap, sa = snap_and_sa()
    steps = [step('2026-09-28T15:00:00.000Z', 'Assigned to Al One', 'Al One'), step('2026-09-28T15:00:30.000Z', 'Driver rejected', detail='Out of Area'),
             step('2026-09-28T15:01:00.000Z', 'Assigned to Bo Two', 'Bo Two')]
    attach_why(steps, pick_trail(snap, sa))
    assert steps[2]['why']['headline'] == 'Al One rejected the call (Out of Area), so it was assigned again'
    assert not any(l.startswith('Computed from the candidate list') for l in steps[2]['why']['lines'])   # a rejection needs no comparison


def test_without_a_built_day_the_reason_falls_back_to_events_and_says_so():
    steps = [step('2026-09-28T15:00:00.000Z', 'Assigned to Al One', 'Al One'), step('2026-09-28T15:01:00.000Z', 'Assigned to Bo Two', 'Bo Two')]
    attach_why(steps, None)
    assert steps[1]['why']['source'] == 'events' and 'not recorded in Salesforce' in steps[1]['why']['lines'][0]


def test_driver_not_on_the_roster_and_spot_queue_get_honest_lines():
    snap, sa = snap_and_sa()
    steps = [step('2026-09-28T15:00:00.000Z', 'Assigned to Zed Away', 'Zed Away'), step('2026-09-28T15:01:00.000Z', 'Assigned to SPOT queue (no driver)', 'SPOT queue (no driver)')]
    attach_why(steps, pick_trail(snap, sa))
    assert any('not on this garage-day' in l for l in steps[0]['why']['lines'])
    assert any('SPOT queue' in l for l in steps[1]['why']['lines'])


def test_no_snapshot_means_no_trail():
    assert pick_trail(None, None) is None and pick_trail({'drivers': []}, {'candidate_sets': []}) is None
