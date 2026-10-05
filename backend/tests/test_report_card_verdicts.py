"""Scheduler Report Card verdicts (metrics-spec.md section 7, rules r1)."""

import copy
import json
from collections import Counter

import pytest

from report_card_verdicts import actor_class, rules_for, sa_features, score_snapshot, verdict
from tests.report_card_factories import D1, D2, cand, late, load_wny_0928, make_sa


def _code(sa, rules=None):
    rules = rules or rules_for('r1')
    return verdict(sa_features(sa, rules), rules)


# ── Golden day: 100 WNY Fleet, 2026-09-28 (Henry's validated output) ──

@pytest.fixture(scope='module')
def wny():
    fx = load_wny_0928()
    return fx, score_snapshot(fx, rules_for('r1'))


def test_wny_verdict_distribution_matches_henry(wny):
    fx, v = wny
    assert len(v) == 90
    assert dict(Counter(x['code'] for x in v.values())) == fx['expected']['verdict_counts']


def test_wny_flags_match_spec(wny):
    _, v = wny
    flags = Counter(f for x in v.values() for f in x['flags'])
    assert flags['BYPASSED_OPTIMIZER'] == 70
    assert flags['HUMAN_FINAL'] == 31
    assert flags['OPTIMIZER_CHURN'] == 15
    assert flags['SLOW_RELEASE'] == 12
    assert flags['MISSED_REBALANCE'] == 2
    assert flags['ASSIGNED_OFF_SHIFT'] == 8   # spec 4: "9/28 had 8 such SAs"


def test_wny_skill_mismatch_under_s9t(wny):
    """S9-T: the 4 pre-login picks are covered by the truck logged into before En Route; only the
    Locksmith call given to a driver with no locksmith skill or capability remains (spec 7.4)."""
    fx, v = wny
    flagged = [s['henry_ref'] for s in fx['sas'] if 'SKILL_MISMATCH' in v[s['id']]['flags']]
    assert flagged == ['SA-1075493'] and len(flagged) == fx['expected']['skill_mismatch']


def test_wny_closest_and_headline_metrics(wny):
    _, v = wny
    ev = [x['evidence'] for x in v.values()]
    graded = [e for e in ev if e['graded']]
    assert (sum(e['picked_closest'] for e in graded), len(graded)) == (38, 87)          # M17
    free = [e for e in graded if e['closest_free_driver_id']]
    assert (sum(e['picked_closest_free'] for e in free), len(free)) == (36, 43)        # M19
    m20 = [e for e in ev if e.get('m20_graded')]
    assert len(m20) == 80
    assert sum(1 for e in m20 if e['idle_q_closer_count']) == 3                        # M20 (a)
    assert sum(1 for e in m20 if e['less_loaded_q_closer_count']) == 0                 # M20 (b)
    pta = [e['pta_met'] for e in ev if e['pta_met'] is not None]
    assert (sum(pta), len(pta)) == (65, 82)                                            # M13
    assert Counter(e['final_actor_class'] for e in ev) == {'INTEGRATION': 39, 'HUMAN': 31, 'FSL_ENGINE': 20}


@pytest.mark.parametrize('ref, code', [
    ('SA-1074741', 'BOUNCED'), ('SA-1074927', 'BOUNCED'), ('SA-1075074', 'BOUNCED'),
    ('SA-1073632', 'CAPACITY_SHORT'), ('SA-1074304', 'CAPACITY_SHORT'), ('SA-1074449', 'CAPACITY_SHORT'),
    ('SA-1073520', 'GOOD'), ('SA-1073522', 'GOOD'), ('SA-1073550', 'GOOD'),
    ('SA-1074161', 'GOOD_NO_ARRIVAL'), ('SA-1074252', 'GOOD_NO_ARRIVAL'), ('SA-1075312', 'GOOD_NO_ARRIVAL'),
    ('SA-1074934', 'INBOUND_CASCADE'), ('SA-1075021', 'INBOUND_CASCADE'), ('SA-1075125', 'INBOUND_CASCADE'),
    ('SA-1074458', 'LATE_DESPITE_CAPACITY'), ('SA-1075605', 'LATE_DESPITE_CAPACITY'),
    ('SA-1074531', 'LATE_EXECUTION'), ('SA-1074664', 'LATE_EXECUTION'),
    ('SA-1075259', 'NOT_GRADED_INSUFFICIENT_DATA'), ('SA-1075278', 'NOT_GRADED_INSUFFICIENT_DATA'),
    ('SA-1074747', 'CAPACITY_SHORT'),
])
def test_wny_named_examples(wny, ref, code):
    fx, v = wny
    sa = next(s for s in fx['sas'] if s['henry_ref'] == ref)
    assert v[sa['id']]['code'] == code


def test_wny_churn_is_not_a_bounce(wny):
    """SA-1074747: 7 picks, reshuffled before dispatch, final pick by a dispatcher (spec 6.1)."""
    fx, v = wny
    sa = next(s for s in fx['sas'] if s['henry_ref'] == 'SA-1074747')
    r = v[sa['id']]
    assert sa['decision']['n_picks'] == 7
    assert 'OPTIMIZER_CHURN' in r['flags'] and r['code'] != 'BOUNCED'
    assert r['evidence']['final_actor_class'] == 'HUMAN'


def test_scoring_is_deterministic(wny):
    fx, v = wny
    again = score_snapshot(copy.deepcopy(fx), rules_for('r1'))
    assert json.dumps(again, sort_keys=True) == json.dumps(v, sort_keys=True)


# ── One hand-built SA per code, and precedence ──

def test_baseline_is_good():
    assert _code(make_sa())['code'] == 'GOOD'


def test_stacked_busy_pick_with_closer_idle_driver():
    sa = make_sa(candidate_sets=[{'event_idx': 0, 'ts': 'x', 'c': [cand(D1, 3.0, open_jobs=1), cand(D2, 1.0)]}])
    r = _code(sa)
    assert r['code'] == 'STACKED' and r['is_failure']


def test_far_pick_and_threshold_flip():
    sa = make_sa(candidate_sets=[{'event_idx': 0, 'ts': 'x', 'c': [cand(D1, 9.0), cand(D2, 2.0)]}])
    assert _code(sa)['code'] == 'FAR_PICK'
    rules = rules_for('r1')
    rules['params']['FAR_PICK']['extra_mi'] = 8.0
    assert _code(sa, rules)['code'] == 'GOOD'
    assert _code(make_sa(), rules)['code'] == 'GOOD'   # the clone changes nothing else


def test_late_despite_capacity_when_free_driver_existed_before_assignment():
    sa = late(make_sa(candidate_sets=[{'event_idx': 0, 'ts': 'x', 'c': [cand(D1, 3.0, open_jobs=1)]}],
                      free_samples={'step_min': 2, 'pre': [[[D2, 4.0]]], 'queue': []}))
    assert _code(sa)['code'] == 'LATE_DESPITE_CAPACITY'


def test_late_execution_quick_pick_to_free_driver():
    assert _code(late(make_sa()))['code'] == 'LATE_EXECUTION'


def test_capacity_short_when_nobody_was_free():
    sa = late(make_sa(candidate_sets=[{'event_idx': 0, 'ts': 'x', 'c': [cand(D1, 3.0, open_jobs=1)]}]))
    assert _code(sa)['code'] == 'CAPACITY_SHORT'


def test_good_no_arrival_when_canceled():
    assert _code(make_sa(milestones={'arrival': None, 't_ol': None}))['code'] == 'GOOD_NO_ARRIVAL'


def test_inbound_beats_bounced_and_bounced_beats_missing_gps():
    moved = make_sa(territory_moves={'in': 1, 'from': ['053']}, decision={'pullbacks': 1})
    assert _code(moved)['code'] == 'INBOUND_CASCADE'
    no_gps = [{'event_idx': 0, 'ts': 'x', 'c': [cand(D1, None)]}]
    assert _code(make_sa(decision={'pullbacks': 1}, candidate_sets=no_gps))['code'] == 'BOUNCED'
    assert _code(make_sa(candidate_sets=no_gps))['code'] == 'NOT_GRADED_INSUFFICIENT_DATA'


def test_towbook_and_never_assigned_are_not_graded():
    assert _code(make_sa(channel='towbook'))['code'] == 'NOT_GRADED_TOWBOOK'
    r = _code(make_sa(final_driver_id=None, decision={'final': None}))
    assert r['code'] == 'NOT_GRADED_CANCELED_PRE_ASSIGN' and not r['graded']


def test_missed_rebalance_needs_ten_idle_minutes():
    busy = [{'event_idx': 0, 'ts': 'x', 'c': [cand(D1, 3.0, open_jobs=1)]}]
    run = lambda n: {'step_min': 2, 'pre': [], 'queue': [[[D2, 2.5]]] * n}
    assert 'MISSED_REBALANCE' in _code(make_sa(candidate_sets=busy, free_samples=run(5)))['flags']
    assert 'MISSED_REBALANCE' not in _code(make_sa(candidate_sets=busy, free_samples=run(4)))['flags']


def _pre_login_pick(truck_start, truck_caps, t_er='2026-09-28T16:05:00.000Z'):
    """Pick at 16:01 to D1, who was not logged in yet (qualified=0, off shift); needs Tire."""
    sa = make_sa(required_skills=['Tire'], milestones={'t_er': t_er},
                 candidate_sets=[{'event_idx': 0, 'ts': 'x', 'c': [cand(D1, 3.0, qualified=0, on_shift=0)]}])
    driver = {'id': D1, 'skills': [], 'trucks': [{'start': truck_start, 'end': '2026-09-29T02:00:00.000Z',
                                                  'truck_caps': truck_caps}]}
    rules = rules_for('r1')
    return verdict(sa_features(sa, rules, driver), rules)['flags']


def test_s9t_truck_logged_into_before_en_route_qualifies_the_pick():
    flags = _pre_login_pick('2026-09-28T16:03:00.000Z', ['Tire'])
    assert 'SKILL_MISMATCH' not in flags and 'ASSIGNED_OFF_SHIFT' in flags


def test_s9t_truck_without_the_skill_is_a_mismatch():
    assert 'SKILL_MISMATCH' in _pre_login_pick('2026-09-28T16:03:00.000Z', ['Battery Service'])


@pytest.mark.parametrize('start, t_er', [
    ('2026-09-28T16:40:00.000Z', '2026-09-28T17:00:00.000Z'),   # > 30 min after the pick
    ('2026-09-28T16:06:00.000Z', '2026-09-28T16:05:00.000Z'),   # after En Route
])
def test_s9t_no_usable_login_is_unknown_not_a_mismatch(start, t_er):
    assert 'SKILL_MISMATCH' not in _pre_login_pick(start, ['Battery Service'], t_er)


def test_logged_in_pick_without_the_skill_is_a_mismatch():
    sa = make_sa(required_skills=['Locksmith'],
                 candidate_sets=[{'event_idx': 0, 'ts': 'x', 'c': [cand(D1, 3.0, qualified=0)]}])
    driver = {'id': D1, 'skills': [], 'trucks': [{'start': '2026-09-28T12:00:00.000Z',
                                                  'end': '2026-09-29T02:00:00.000Z', 'truck_caps': ['Tire']}]}
    rules = rules_for('r1')
    assert 'SKILL_MISMATCH' in verdict(sa_features(sa, rules, driver), rules)['flags']


# ── Actor classes (spec B4) ──

@pytest.mark.parametrize('actor, profile, is_driver, expected', [
    ('Platform Integration User', None, False, 'FSL_ENGINE'),
    ('FSL System User', 'System Administrator', False, 'FSL_ENGINE'),
    ('Mulesoft Integration', 'AAACRM Mulesoft Integration User', False, 'INTEGRATION'),
    ('Some Driver', 'Membership User', True, 'DRIVER'),          # a driver whose profile is Membership User
    ('Garage Person', 'Partner Community User', False, 'GARAGE_DISPATCHER'),
    ('Dispatcher', 'Membership User', False, 'HUMAN'),
    ('Someone', 'Standard User', False, 'OTHER'),
])
def test_actor_class(actor, profile, is_driver, expected):
    a = {'actor': actor, 'actor_profile': profile, 'actor_is_driver': is_driver}
    assert actor_class(a, rules_for('r1')) == expected


def test_pta_target_drives_m13_band():
    rules = rules_for('r1')
    assert rules['metric_bands']['M13']['good'][0] == rules['user_pending']['pta_target'] == 0.85
    with pytest.raises(ValueError):
        rules_for('r9')


def test_garage_portal_user_on_the_roster_decides_as_garage_dispatcher():
    """Spec 6.2: Todd Kryszak is on the 076DO roster but assigns other drivers from the garage portal."""
    a = {'actor': 'Garage Owner', 'actor_profile': 'Partner Community User', 'actor_is_driver': True}
    assert actor_class(a, rules_for('r1'), decision=True) == 'GARAGE_DISPATCHER'
    assert actor_class(a, rules_for('r1')) == 'DRIVER'          # his own status updates stay driver actions


# ── r2: graded on the original PTA (metrics-spec 7.7) ──

def test_r2_is_the_default_and_differs_from_r1_only_in_pta_basis():
    from report_card_verdicts import DEFAULT_RULES
    r1, r2 = rules_for('r1'), rules_for()
    assert DEFAULT_RULES == 'r2' and r2['rules_version'] == 'r2'
    assert {k for k in r2 if r2[k] != r1.get(k)} == {'rules_version', 'pta_basis', 'pta_initial_window_sec', 'auto_schedule'}


def test_wny_r2_pta_met_and_no_verdict_changes(wny):
    """Spec 7.7 golden: 9/28 PTA met 65/82 under r1, 64/82 under r2 (SA-1075021 re-based by Towbook), 0 code changes."""
    fx, v1 = wny
    v2 = score_snapshot(fx, rules_for('r2'))
    met = lambda v: [sum(1 for x in v.values() if x['evidence']['pta_met'] is True),
                     sum(1 for x in v.values() if x['evidence']['pta_met'] is not None)]
    assert met(v1) == fx['expected']['pta_met']['r1'] and met(v2) == fx['expected']['pta_met']['r2']
    assert all(v1[k]['code'] == v2[k]['code'] for k in v1)
    flipped = [s['henry_ref'] for s in fx['sas'] if v1[s['id']]['evidence']['pta_met'] != v2[s['id']]['evidence']['pta_met']]
    assert flipped == ['SA-1075021']
    for rv, v in (('r1', v1), ('r2', v2)):
        assert sum('BYPASSED_OPTIMIZER' in x['flags'] for x in v.values()) == fx['expected']['bypassed'][rv]
        assert sum(x['evidence']['final_actor_class'] == 'FSL_AUTO_SCHEDULE' for x in v.values()) ==             fx['expected']['fsl_auto_schedule_finals'][rv]


@pytest.mark.parametrize('lag_s, rules_v, expected', [
    (7, 'r2', 'FSL_AUTO_SCHEDULE'), (0, 'r2', 'FSL_AUTO_SCHEDULE'), (60, 'r2', 'FSL_AUTO_SCHEDULE'),
    (61, 'r2', 'INTEGRATION'), (-1, 'r2', 'INTEGRATION'), (7, 'r1', 'INTEGRATION'),
])
def test_b4a_integration_pick_after_the_auto_schedule_stamp_is_fsl_auto_schedule(lag_s, rules_v, expected):
    """Spec B4a: FSL's batch scheduler runs as the account that set FSL__Auto_Schedule__c (pick ~7 s after the stamp)."""
    from datetime import timedelta
    from report_card_verdicts import pick_class
    from utils import parse_dt
    stamp = '2026-09-28T16:00:00.000Z'
    pick = {'actor': 'Mulesoft Integration', 'actor_profile': 'AAACRM Mulesoft Integration User', 'actor_is_driver': False,
            'ts': (parse_dt(stamp) + timedelta(seconds=lag_s)).isoformat()}
    assert pick_class(pick, {'auto_schedule_requested': stamp}, rules_for(rules_v)) == expected


def test_fsl_auto_schedule_is_not_a_bypass():
    sa = make_sa(auto_schedule_requested='2026-09-28T16:00:53.000Z', pta_initial_min=60, pta_initial_src='history',
                 pta_initial_due='2026-09-28T17:00:00.000Z',
                 decision={'final': {'actor': 'Mulesoft Integration', 'actor_profile': 'x', 'actor_is_driver': False,
                                     'ts': '2026-09-28T16:01:00.000Z'}})
    r = _code(sa, rules_for('r2'))
    assert r['evidence']['final_actor_class'] == 'FSL_AUTO_SCHEDULE' and 'BYPASSED_OPTIMIZER' not in r['flags']
    assert 'BYPASSED_OPTIMIZER' in _code(sa, rules_for('r1'))['flags']


def test_r2_grades_the_original_promise():
    """Promise 60 at creation, re-based to 120 later; arrival at +90 min is met under r1, missed under r2."""
    sa = make_sa(pta_min=120, pta_due='2026-09-28T18:00:00.000Z', pta_initial_min=60.0, pta_initial_src='history',
                 pta_initial_due='2026-09-28T17:00:00.000Z',
                 milestones={'arrival': '2026-09-28T17:30:00.000Z', 't_ol': '2026-09-28T17:30:00.000Z',
                             't_end': '2026-09-28T18:00:00.000Z'})
    assert _code(sa, rules_for('r1'))['evidence']['pta_met'] is True
    r2 = _code(sa, rules_for('r2'))
    assert r2['evidence']['pta_met'] is False and r2['code'] == 'LATE_EXECUTION' and r2['rules_version'] == 'r2'


def test_r2_refuses_a_snapshot_built_without_the_original_pta():
    from report_card_verdicts import RulesNotAvailable
    snap = {'builder_version': 'rc-build-1.0', 'drivers': [], 'sas': [make_sa()]}
    with pytest.raises(RulesNotAvailable):
        score_snapshot(snap, rules_for('r2'))
    assert score_snapshot(snap, rules_for('r1'))      # r1 still works on old snapshots
