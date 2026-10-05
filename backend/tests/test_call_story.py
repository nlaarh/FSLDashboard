"""Call Story pure modules: resolution, events, segments + severity, norms, SMS, causes, narrative validator.
Golden = call-story-spec 10.4 reproduced synthetically (tests/call_story_factories.py). No network."""

from datetime import datetime, timezone

import pytest

from call_story_compose import compose
from call_story_config import cs1
from call_story_narrative import fact_sheet, validate
from call_story_norms import Norms
from call_story_pull import Ambiguous, classify, resolve
from call_story_segments import place_kind, severity
from call_story_sms import timer_runs
from tests.call_story_factories import FakeNorms, towbook_cascade_raw

CFG = cs1()
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


@pytest.fixture(scope='module')
def story():
    return compose(towbook_cascade_raw(), CFG, snapshot_for=lambda t, d: None, norms_for=lambda d: FakeNorms(), now=NOW)


# ── resolution (spec 2) ──

@pytest.mark.parametrize('q, kind, value', [
    ('SA-1074304', 'sa', 'SA-1074304'), ('1074304', 'sa', 'SA-1074304'), ('sa-1074304', 'sa', 'SA-1074304'),
    ('05173612', 'wo', '05173612'), ('WO-05173612', 'wo', '05173612'),
    ('084-20260928-05173612', 'call_key', '084-20260928-05173612'),
    ('15211381', 'source_call_id', '15211381'), ('08pPb000009eT1JIAU', 'id', '08pPb000009eT1JIAU'),
])
def test_classify(q, kind, value):
    assert classify(q, CFG) == (kind, value)


@pytest.mark.parametrize('q', ['hello', 'SA-99999999', "05173612' OR Id != '", '', '084-2026-05173612'])
def test_classify_rejects_anything_else_before_soql(q):
    with pytest.raises(ValueError):
        classify(q, CFG)


class FakePuller:
    def __init__(self, rows):
        self.rows, self.soql, self.calls = rows, [], 0

    def all(self, soql):
        self.soql.append(soql)
        self.calls += 1
        return self.rows.pop(0) if self.rows else []


def test_eight_digits_matching_a_wo_and_a_source_call_id_is_ambiguous():
    p = FakePuller([[{'Id': 'a', 'WorkOrderNumber': '05211381', 'CreatedDate': 'x'},
                     {'Id': 'b', 'WorkOrderNumber': '05172864', 'CreatedDate': 'y'}]])
    with pytest.raises(Ambiguous) as e:
        resolve(p, 'wo', '05211381')
    assert [c['type'] for c in e.value.candidates] == ['wo', 'source_call_id'] and p.calls == 1


def test_sa_input_resolves_through_the_direct_work_order_link():
    p = FakePuller([[{'ERS_Work_Order__c': '0WOFAKE00000001AAA'}], [{'Id': '0WOFAKE00000001AAA', 'WorkOrderNumber': '1'}]])
    assert resolve(p, 'sa', 'SA-1074304')['Id'] == '0WOFAKE00000001AAA'
    assert "AppointmentNumber = 'SA-1074304'" in p.soql[0] and "Id = '0WOFAKE00000001AAA'" in p.soql[1]


# ── golden 10.4: Towbook cascade + SPOT ──

def test_golden_events_and_actor_classes(story):
    vis = [e for e in story['events'] if not e['hidden']]
    kinds = [e['kind'] for e in vis]
    assert kinds.count('E07_declined') == 2 and 'E07_rejected' in kinds and 'E10_pullback' not in kinds
    rej = next(e for e in vis if e['kind'] == 'E07_rejected')
    assert rej['actor_class'] == 'DRIVER' and rej['reason'] == 'Out of Area'              # E08 attach rule
    assert [e.get('seconds_from_offer') for e in vis if e['kind'] == 'E07_declined'] == [33, 36]
    assert next(e for e in vis if e['kind'] == 'E07_accepted')['actor_class'] == 'TOWBOOK_SYNC'
    assert any(e['hidden'] for e in story['events'])                                      # SchedStartTime noise


def test_golden_segments_and_severity(story):
    s7 = next(g for g in story['segments'] if g['kind'] == 'S7' and g['minutes'] > 40)
    assert (s7['minutes'], s7['severity'], s7['stuck_type']) == (48.1, 'CRITICAL', 'NO_OWNER')
    s8 = next(g for g in story['segments'] if g['kind'] == 'S8')
    assert (s8['minutes'], s8['stuck_type'], s8['garage']) == (26.1, 'PARKED_IN_SPOT', '000- ST SPOT')


def test_golden_pta_graded_on_the_original_promise(story):
    p = story['pta']
    assert (p['initial_min'], p['final_min'], p['met_initial'], p['met_final']) == (90.0, 120, False, True)
    assert p['margin_initial_min'] == pytest.approx(-14.9) and p['arrival_source'] == 'history'
    assert p['rebased']['actor'] == 'Integrations Towbook'


def test_golden_causes_headline_and_verdict(story):
    codes = [c['code'] for c in story['causes']]
    assert sorted(set(codes)) == ['C02', 'C03', 'C04', 'C05', 'C16', 'C17', 'C19'] and codes.count('C02') == 2
    head = next(c for c in story['causes'] if c['headline'])
    assert head['code'] == 'C04' and head['evidence']['acted_by'] == 'Domingo Santiago'
    c05 = next(c for c in story['causes'] if c['code'] == 'C05')
    assert c05['evidence']['other_region'] and c05['evidence']['matrix_spot'] == '000- WNY M SPOT'
    v = story['verdict']
    assert (v['source'], v['primary']) == ('partial', 'NOT_GRADED_TOWBOOK')                 # candidate-free code shown
    assert story['performer'] == 'Adam Lucas' and story['header']['channel'] == 'towbook'


def test_golden_ladder_path_sms_legs_notes(story):
    assert [r['state'] for r in story['header']['matrix_ladder']] == ['final', 'declined', 'rejected', 'not_reached', 'not_reached']
    assert story['header']['channel_path'][-1] == {**story['header']['channel_path'][-1], 'channel': 'towbook'}
    assert [r['label'] for r in story['sms']['rows']] == ['Call received', 'Garage and PTA']   # dispatcher text excluded
    w = story['sms']['why_not'][0]
    assert (w['code'], w['restarts']) == ('TIMER_RESTARTED', 4)
    assert story['sms']['delivery']['available'] is False
    assert [(l['role'], l['selected']) for l in story['resolution']['legs']] == [('member', True), ('drop_off', False)]
    assert {n['code'] for n in story['data_notes']} >= {'TOWBOOK_ACTUALSTART_EMPTY', 'NO_BASELINE'}


def test_no_address_or_phone_in_the_story(story):
    text = str(story)
    assert '12 Member Lane' not in text and '10 Member Lane' not in text and 'Mobile_Phone' not in text


def test_unbuilt_day_never_shows_a_candidate_dependent_verdict():
    raw = towbook_cascade_raw()
    for h in raw['history']:                         # make it an FSL call: no Towbook acceptance
        if h['CreatedBy']['Name'] == 'Integrations Towbook' and h['Field'] == 'Status' and h['NewValue'] == 'Accepted':
            h['CreatedBy'] = {'Name': 'Mulesoft Integration', 'Profile': {'Name': 'x'}}
    st = compose(raw, CFG, snapshot_for=lambda t, d: None, norms_for=lambda d: FakeNorms(), now=NOW)
    assert st['verdict']['primary'] in (None, 'NOT_GRADED_TOWBOOK', 'NOT_GRADED_CANCELED_PRE_ASSIGN', 'INBOUND_CASCADE', 'BOUNCED')
    if st['verdict']['primary'] is None:
        assert st['verdict']['note'] == 'Decision not graded: garage-day not built' and st['verdict']['build']['allowed']


# ── severity rules (spec 5.3, O2 / O3) ──

def _seg(kind, minutes, a='2026-09-28T16:00:00.000Z', b=None):
    from datetime import timedelta
    from utils import parse_dt
    b = b or (parse_dt(a) + timedelta(minutes=minutes)).isoformat().replace('+00:00', 'Z')
    return {'kind': kind, 'minutes': minutes, 'from': a, 'to': b}


B = lambda p75, p90, p95, n=100: {'p75': p75, 'p90': p90, 'p95': p95, 'n': n}


def test_o2_battery_on_scene_56_5_is_slow_not_stuck():
    """10.2: above battery p75 40.8 and p90 56.3, but under the 60-min S6 floor -> SLOW, C15 does not fire."""
    assert severity(_seg('S6', 56.5), B(40.8, 56.3, 73.5), None, CFG) == ('SLOW', 'p75')


def test_o3_pta_passing_during_a_slow_pre_arrival_segment_is_critical():
    from utils import parse_dt
    seg = _seg('S3', 68.7)                               # 10.3: busy p90 58.2 -> STUCK; PTA 12:44 passed during it
    assert severity(seg, B(40.2, 58.2, 77.9), None, CFG) == ('STUCK', 'p90')
    assert severity(seg, B(40.2, 58.2, 77.9), parse_dt('2026-09-28T16:40:00Z'), CFG) == ('CRITICAL', 'pta_passed')
    ok = _seg('S4', 2.0)                                  # a normal 2-min segment straddling the deadline stays OK
    assert severity(ok, B(3.0, 6.6, 12.3), parse_dt('2026-09-28T16:01:00Z'), CFG) == ('OK', None)


def test_small_baselines_use_floors_only():
    assert severity(_seg('S5', 50), B(20, 30, 40, n=12), None, CFG) == ('SLOW', 'floor')
    assert severity(_seg('S7', 1), None, None, CFG) == ('SLOW', 'always_flag')


@pytest.mark.parametrize('name, kind', [('000- ST SPOT', 'SPOT'), ('000-ST Spot', 'SPOT'), ('WM003', 'GRID'),
                                        ('SPOT - UNASSIGNED GRIDS', 'UNASSIGNED'), ('076DO - TRANSIT AUTO DETAIL', 'GARAGE')])
def test_place_kind(name, kind):
    assert place_kind(name, CFG) == kind


# ── norms fallback chain (architecture 5) ──

def _rows(n, **kw):
    base = {'g': 'G1', 'c': 'fleet', 'k': 'S5', 'm': 10.0, 'b': 12, 'd': 'weekday'}
    return [{**base, **kw, 'm': float(i)} for i in range(n)]


def test_norms_fall_back_until_n_reaches_30():
    seg = {'kind': 'S5', 'garage': 'G1', 'channel': 'fleet', 'et_hour_block': 12, 'daytype': 'weekday'}
    n = Norms({('a', 'd'): _rows(10) + _rows(25, b=8)}, ('2026-08-03', '2026-09-27'), CFG)
    b = n.baseline(seg)
    assert (b['key_level'], b['n']) == ('garage_channel_segment', 35)
    n2 = Norms({('a', 'd'): _rows(5, k='S7', c='towbook', g='X') + _rows(30, k='S7', c='fleet', g='Y')}, ('a', 'b'), CFG)
    s7 = {**seg, 'kind': 'S7', 'garage': 'X', 'channel': 'towbook'}
    assert n2.baseline(s7)['key_level'] == 'segment_all_channels'                # level 4 only for S7/S8/S9
    assert n2.baseline({**seg, 'garage': 'Z'}) is None


# ── SMS timer (spec 7.4) ──

def test_timer_restarts_count_exits_from_assigned_dispatched():
    ev = [('2026-09-24T14:35:49Z', 'Spotted'), ('2026-09-24T14:35:50Z', 'Dispatched'), ('2026-09-24T14:36:22Z', 'Declined'),
          ('2026-09-24T14:36:30Z', 'Dispatched'), ('2026-09-24T15:58:07Z', 'Accepted')]
    assert timer_runs(ev, CFG) == (1, 81.6)


# ── narrative validator (architecture 7.3) ──

def test_narrative_facts_are_anonymised_and_validated(story):
    facts, labels = fact_sheet(story)
    assert 'Domingo Santiago' not in str(facts) and labels['Domingo Santiago'].startswith('Dispatcher')
    who = labels['Domingo Santiago']
    good = {'sentences': [{'text': f'{who} moved the call after 48.1 min with no owner.', 'event_ids': ['E1'],
                           'cause_codes': ['C04']}]}
    assert validate(good, facts, labels) == []
    bad = {'sentences': [{'text': 'Dispatcher Z waited 61 min, caused by C08.', 'event_ids': ['E99'], 'cause_codes': ['C08']}]}
    errs = ' '.join(validate(bad, facts, labels))
    for want in ('numbers', 'unknown people', 'event ids', 'cause codes', 'caused by'):
        assert want in errs
