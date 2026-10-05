"""wo_explain.py and the warning steps: why something may have gone wrong. Synthetic data, no I/O."""

import re

import wo_takeaways
from wo_explain import CATALOG, explain, text_reason
from wo_replay import attach_explain, problem_steps
from tests.test_wo_replay import by_id, story as replay_story, build_replay


def test_a_zone_problem_names_this_calls_own_closed_garages_before_the_usual_causes():
    ladder = [{'rank': 2.0, 'garage': 'LS - LOCKSMITH', 'worktype': 'Locksmith', 'hours': '7a-10p', 'state': 'skipped_closed'},
              {'rank': 3.0, 'garage': '076DO', 'worktype': 'Tow Pick-Up;Battery', 'hours': '24/7', 'state': 'not_reached'}]
    e = explain('STUCK_GRID', ladder=ladder, work_type='Battery', grid='WM025', minutes=40)
    assert e['icon'] == 'zone' and e['why'][0].startswith('This call: LS - LOCKSMITH (rank 2) was closed (hours 7a-10p)')
    assert any('does not list Battery work' in w for w in e['why']) and any('wrong zone' in w for w in e['why'])
    assert e['check']


def test_every_problem_code_used_by_the_takeaways_exists_in_the_catalog():
    used = set(re.findall(r"code='([A-Z_]+)'", open(wo_takeaways.__file__).read())) | set(re.findall(r"explain\('([A-Z_]+)'", open('wo_replay.py').read()))
    assert used and used <= set(CATALOG)


def test_text_reasons_are_plain_and_unknown_ones_say_the_log_does_not_say():
    assert 'not agreed to receive texts' in text_reason('No-Consent', 'skipped')
    assert 'no messaging record' in text_reason('Skipped-No-MEU', 'skipped')
    assert 'no mobile number' in text_reason('No-Phone', 'skipped').lower()
    assert 'does not say why' in text_reason('Something-New', 'skipped')


def test_a_long_gap_becomes_a_visible_warning_step_at_the_moment_it_began():
    s = replay_story()
    s['segments'] = [{'id': 'G3', 'kind': 'S9', 'from': '2026-09-28T15:44:12.000Z', 'minutes': 41.0, 'severity': 'CRITICAL'},
                     {'id': 'G4', 'kind': 'S2', 'from': '2026-09-28T16:00:00.000Z', 'minutes': 2.0, 'severity': 'OK'}]
    s['header']['grid'] = {'name': 'WM025'}
    steps = problem_steps(s)
    assert [x['id'] for x in steps] == ['G3'] and steps[0]['title'] == 'Stuck in zone WM025 for 41 min'
    assert steps[0]['flag']['level'] == 'bad' and steps[0]['explain']['icon'] == 'zone'


def test_flagged_steps_get_their_reasons_and_the_third_pre_release_pick_is_flagged_as_churn():
    steps = [{'title': 'Garage declined in 33 s', 'kind': 'system', 'detail': 'x', 'flag': {'level': 'warn'}, 'explain': None},
             {'title': 'Driver rejected', 'kind': 'driver', 'detail': 'Out of Area', 'flag': {'level': 'warn'}, 'explain': None},
             {'title': 'Text NOT sent: Still working', 'kind': 'sms', 'detail': 'No-Consent', 'flag': {'level': 'bad'}, 'explain': None},
             {'title': 'Assigned to A', 'kind': 'system', 'detail': '', 'flag': None, 'explain': None},
             {'title': 'Assigned to B', 'kind': 'system', 'detail': '', 'flag': None, 'explain': None},
             {'title': 'Assigned to C', 'kind': 'system', 'detail': '', 'flag': None, 'explain': None}]
    attach_explain(steps, {})
    assert steps[0]['explain']['code'] == 'DECLINES' and '33 s' in steps[0]['explain']['why'][0]
    assert steps[1]['explain']['code'] == 'REJECT' and 'Out of Area' in steps[1]['explain']['why'][0]
    assert steps[2]['explain']['code'] == 'TEXT_FAILED' and 'not agreed to receive texts' in steps[2]['explain']['why'][0]
    assert steps[5]['explain']['code'] == 'CHURN' and steps[5]['flag']['text'].startswith('Assigned 3 times')
    assert steps[3]['explain'] is None


def test_the_replay_carries_the_takeaways_and_every_step_has_an_explain_key():
    r = build_replay(replay_story())
    assert r['takeaways']['verdict'] in ('good', 'mixed', 'poor') and r['takeaways']['headline']
    assert all('explain' in s for s in r['steps'])
