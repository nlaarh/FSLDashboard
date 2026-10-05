"""Scheduler Report Card snapshot builder (raw Salesforce rows -> snapshot), on synthetic rows."""

from datetime import datetime, timezone

import pytest

from report_card_build import day_window
from report_card_snapshot import build_snapshot
from report_card_verdicts import actor_class, rules_for, score_snapshot
from tests.report_card_factories import D1, D2, tiny_raw

BUILT = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize('day, hours, start', [
    ('2026-09-28', 24, '2026-09-28 04:00:00+00:00'),
    ('2026-11-01', 25, '2026-11-01 04:00:00+00:00'),   # fall back
    ('2026-03-08', 23, '2026-03-08 05:00:00+00:00'),   # spring forward
])
def test_day_window_is_the_eastern_calendar_day(day, hours, start):
    w = day_window(day)
    assert str(w['day_start']) == start
    assert (w['day_end'] - w['day_start']).total_seconds() == hours * 3600


@pytest.fixture(scope='module')
def snap():
    return build_snapshot(tiny_raw(), built_at=BUILT)


def _sa(snap, suffix):
    return next(s for s in snap['sas'] if s['id'].endswith(suffix))


def test_final_decider_is_last_assignment_row_not_record_creator(snap):
    sa = _sa(snap, '001AAA')
    d = sa['decision']
    assert d['final']['actor'] == 'Dispatcher One'
    assert d['ar_creator']['name'] == 'Mulesoft Integration'
    assert d['first']['actor'] == 'Mulesoft Integration'
    assert d['n_picks'] == 2                      # the Id row is dropped
    assert d['pullbacks'] == 1 and d['reassign_after_dispatch'] == 1
    assert sa['milestones']['t_asg'] == '2026-09-28T16:04:00.000Z'
    assert sa['channel'] == 'fleet' and sa['milestones']['arrival_source'] == 'actual_start'


def test_status_rows_by_the_driver_are_driver_actions(snap):
    sa = _sa(snap, '001AAA')
    en_route = next(e for e in sa['events'] if e.get('value') == 'En Route')
    assert actor_class(en_route, rules_for('r1')) == 'DRIVER'


def test_candidates_use_truck_caps_and_fresh_gps(snap):
    sa = _sa(snap, '001AAA')
    cs = sa['candidate_sets'][sa['decision_set_idx']]['c']
    one = next(c for c in cs if c[0] == D1)
    two = next(c for c in cs if c[0] == D2)
    assert one[4] == 1 and one[5] == 1            # Tire comes from the logged-in truck
    assert one[3] == pytest.approx(1.38, abs=0.01) and one[7] == 5.0
    assert two[4] == 0                            # truck 2 has no Tire
    assert two[3] is None and two[7] is None      # its last fix is 64 min old (> 30)


def test_carryover_and_drop_off_handling(snap):
    ids = {s['id'][-6:]: s for s in snap['sas']}
    assert '002AAA' not in ids                    # ended before the day started
    assert ids['003AAA']['in_day'] is False       # still open at day start: context only
    assert ids['004AAA']['is_drop_off']
    scored = score_snapshot(snap, rules_for('r1'))
    assert set(k[-6:] for k in scored) == {'001AAA'}
    assert scored[_sa(snap, '001AAA')['id']]['code'] == 'BOUNCED'


def test_snapshot_meta(snap):
    assert snap['schema_version'] == 1
    assert snap['provisional'] is False
    assert snap['channel_summary'] == {'by_channel': {'fleet': 1}, 'mode': 'fsl'}
    assert snap['completeness']['sa_count_loaded'] == 4
    d1 = next(d for d in snap['drivers'] if d['id'] == D1)
    assert d1['logins'] == [{'start': '2026-09-28T12:00:00.000Z', 'end': '2026-09-28T20:00:00.000Z'}]
    assert d1['trucks'][0]['truck_caps'] == ['Lockout', 'Tire']


def test_original_pta_is_the_last_value_within_5s_of_creation(snap):
    """90 -> 60 at creation (same second, chained), re-based to 120 at +15 s: the promise is 60 (spec 7.7)."""
    sa = _sa(snap, '001AAA')
    assert (sa['pta_min'], sa['pta_initial_min'], sa['pta_initial_src']) == (120, 60.0, 'history')
    assert sa['pta_due'] == '2026-09-28T18:00:00.000Z' and sa['pta_initial_due'] == '2026-09-28T17:00:00.000Z'
    assert [e['to'] for e in sa['events'] if e['field'] == 'pta'] == ['90', '60', '120']
    assert snap['builder_version'] == 'rc-build-1.2'


@pytest.mark.parametrize('rows, stored, expected', [
    ([], 75, (75, 'stored')),                                                      # no history row
    ([('16:00:00', None, '999')], 999, (None, 'invalid')),                         # 999 = no promise
    ([('16:00:06', None, '45')], 60, (60, 'stored')),                              # outside the 5 s window
    ([('16:00:01', '90', '60'), ('16:00:01', None, '90')], 60, (60.0, 'history')),  # chained regardless of row order
])
def test_initial_pta_rules(rows, stored, expected):
    from report_card_snapshot import initial_pta
    from utils import parse_dt
    hist = [{'CreatedDate': f'2026-09-28T{t}.000+0000', 'OldValue': o, 'NewValue': n} for t, o, n in rows]
    assert initial_pta(parse_dt('2026-09-28T16:00:00.000+0000'), hist, stored) == expected


def test_gps_read_cools_down_and_retries_in_halves(monkeypatch):
    import report_card_build as b
    sleeps, sizes = [], []
    p = b._Puller()

    def fake_all(soql):
        n = soql.count("'")// 2
        sizes.append(n)
        if n > 3:
            raise RuntimeError('SF query timed out after retries')
        return [{'n': n}]
    monkeypatch.setattr(p, 'all', fake_all)
    monkeypatch.setattr(b.time, 'sleep', sleeps.append)
    monkeypatch.setattr(b, 'MIN_SPLIT', 2)
    ids = [f'0HnFAKE0000000{i:02d}AA' for i in range(12)]
    rows = p.batched('SELECT Id FROM X WHERE Id IN ({ids})', ids, size=12, split_on_timeout=True)
    assert sum(r['n'] for r in rows) == 12 and sizes[0] == 12 and max(r['n'] for r in rows) <= 3
    assert sleeps and all(s == b.SPLIT_COOLDOWN_S for s in sleeps)


def test_gps_read_gives_up_below_the_minimum_batch(monkeypatch):
    import report_card_build as b
    p = b._Puller()
    monkeypatch.setattr(p, 'all', lambda soql: (_ for _ in ()).throw(RuntimeError('timeout')))
    monkeypatch.setattr(b.time, 'sleep', lambda s: None)
    with pytest.raises(RuntimeError):
        p.batched('SELECT Id FROM X WHERE Id IN ({ids})', ['a1', 'a2', 'a3', 'a4'], split_on_timeout=True)
