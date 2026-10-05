"""Scheduler Report Card driver-day metrics and driver health h1 (metrics-spec.md section 5A)."""

import os
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from report_card_metrics import band, driver_day, garage_summary
from report_card_verdicts import rules_for, score_snapshot
from tests.report_card_factories import D1, D2, make_sa

RULES = rules_for('r1')
T0 = datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc)


def _iso(minutes):
    return (T0 + timedelta(minutes=minutes)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


@pytest.mark.parametrize('metric, value, expected', [
    ('M06', 2, 'good'), ('M06', 3, 'watch'), ('M06', 4, 'bad'),          # <= 2 / 3 / >= 4
    ('M08', 30, 'good'), ('M08', 45, 'watch'), ('M08', 61, 'bad'),       # p90 <= 30 / <= 60 / > 60
    ('M13', 0.85, 'good'), ('M13', 0.80, 'watch'), ('M13', 0.70, 'bad'),  # >= 85 / >= 75 / < 75
    ('M04', 0.5, None), ('M13', None, None),
])
def test_band(metric, value, expected):
    assert band(metric, value, RULES) == expected


def _driver(did, name, shift_min=120, gps=True):
    """On shift 16:00 for shift_min, in a Tire truck, parked at the call location with a fix every 10 min."""
    return {'id': did, 'name': name, 'channel': 'fleet', 'member': True, 'skills': [],
            'logins': [{'start': _iso(0), 'end': _iso(shift_min)}], 'absences': [],
            'trucks': [{'start': _iso(0), 'end': _iso(shift_min), 'truck_caps': ['Tire']}],
            'gps': [[int((T0 + timedelta(minutes=m)).timestamp()), 43.0, -78.8] for m in range(0, shift_min, 10)]
            if gps else []}


def _job(i, start, end, t_er=None, driver=D1, **kw):
    sa = make_sa(id=f'08pFAKE0000000{i}AAA', number=f'SA-{i}', final_driver_id=driver, required_skills=['Tire'],
                 busy=[_iso(start), _iso(end)], created=_iso(start), **kw)
    sa['milestones'] = {**sa['milestones'], 't_asg': _iso(start), 't_disp': _iso(start), 't_end': _iso(end),
                        't_er': _iso(t_er if t_er is not None else start + 1), 't_ol': _iso(end - 5),
                        'arrival': _iso(end - 5)}
    sa['pta_due'] = _iso(start + 60)
    return sa


def _rows(sas, drivers):
    snap = {'window': {'day_start_utc': '2026-09-28T04:00:00.000Z', 'day_end_utc': '2026-09-29T04:00:00.000Z'},
            'drivers': drivers, 'sas': sas}
    v = score_snapshot(snap, RULES)
    return snap, v, {r['id']: r for r in driver_day(snap, v, RULES)}


def test_driver_day_stacking_idle_and_utilisation():
    snap, v, rows = _rows([_job(1, 10, 50), _job(2, 30, 90, t_er=60)], [_driver(D1, 'Driver One')])
    row = rows[D1]
    m = row['metrics']
    assert row['on_shift_min'] == 120 and row['assigned'] == 2
    assert m['M06']['value'] == 2 and m['M07']['value'] == 20           # 16:30-16:50 stacked
    assert m['M04']['value'] == pytest.approx(80 / 120, abs=1e-4)       # busy 16:10-17:30
    assert row['idle'] == [['2026-09-28T16:00:00Z', '2026-09-28T16:10:00Z'],
                           ['2026-09-28T17:30:00Z', '2026-09-28T18:00:00Z']]
    assert row['stacked'] == [['2026-09-28T16:30:00Z', '2026-09-28T16:50:00Z', 2]]
    assert garage_summary(snap, v, [row], RULES)['M07']['value'] == 20


def test_h1_avoidable_stacking_is_the_schedulers_and_names_the_idle_partner():
    sas = [_job(1, 10, 50), _job(2, 30, 90, t_er=60)]       # queued 16:30-16:50 behind job 1
    _, _, rows = _rows(sas, [_driver(D1, 'Driver One'), _driver(D2, 'Driver Two')])
    h = rows[D1]['health_detail']
    h1 = next(i for i in h['inputs'] if i['id'] == 'H1')
    assert h1['value'] == pytest.approx(20 / 120, abs=0.01) and h1['band'] == 'watch'
    assert (h['health'], h['owner']) == ('watch', 'scheduler')
    assert 'Driver Two' in h['reasons'][0]['text']


def test_h2_idle_while_work_waited():
    """Driver Two sits idle and qualified next to job 2 while it waits (16:40 to En Route at 17:00)."""
    sas = [_job(1, 10, 50), _job(2, 30, 90, t_er=60)]
    _, _, rows = _rows(sas, [_driver(D1, 'Driver One'), _driver(D2, 'Driver Two')])
    h2 = next(i for i in rows[D2]['health_detail']['inputs'] if i['id'] == 'H2')
    assert h2['value'] == pytest.approx(20 / 120, abs=0.01) and h2['band'] == 'watch'


def test_short_shift_is_not_banded_on_h1_h2():
    sas = [_job(1, 10, 50), _job(2, 30, 90, t_er=60)]
    _, _, rows = _rows(sas, [_driver(D1, 'Driver One', shift_min=100), _driver(D2, 'Driver Two')])
    assert rows[D1]['health'] == 'healthy'


def test_h4_two_late_executions_make_the_driver_unhealthy():
    late = lambda i, s: {**_job(i, s, s + 100), 'pta_due': _iso(s + 30)}
    _, v, rows = _rows([late(1, 0), late(2, 110)], [_driver(D1, 'Driver One', shift_min=240)])
    assert Counter(x['code'] for x in v.values()) == {'LATE_EXECUTION': 2}
    h = rows[D1]['health_detail']
    assert (h['health'], h['owner']) == ('unhealthy', 'driver')
    assert h['context']['pta_misses'] == {'system': 0, 'bounce': 0, 'driver': 2}


def _pullback_events(wait_min):
    ev = lambda m, field, **kw: {'ts': _iso(m), 'field': field, **kw}
    return [ev(1, 'assigned', driver_id=D2, driver='Driver Two'), ev(2, 'status', value='Dispatched'),
            ev(2 + wait_min, 'status', value='Spotted'), ev(3 + wait_min, 'assigned', driver_id=D1, driver='Driver One')]


@pytest.mark.parametrize('wait_min, expected', [(20, 1), (1, 0)])   # 1-min pull-backs are dispatcher corrections
def test_h5_non_response_pullbacks(wait_min, expected):
    sa = _job(1, 30, 90, events=_pullback_events(wait_min), decision={'pullbacks': 1})
    _, _, rows = _rows([sa], [_driver(D1, 'Driver One'), _driver(D2, 'Driver Two')])
    h5 = next(i for i in rows[D2]['health_detail']['inputs'] if i['id'] == 'H5')
    assert h5['value'] == expected


def test_h6_slow_to_accept_when_free_needs_three_calls():
    def slow(i, s):
        sa = _job(i, s, s + 50, t_er=s + 20)
        sa['milestones']['t_disp'] = _iso(s)
        return sa
    _, _, rows = _rows([slow(1, 0), slow(2, 60), slow(3, 120)], [_driver(D1, 'Driver One', shift_min=240)])
    h6 = next(i for i in rows[D1]['health_detail']['inputs'] if i['id'] == 'H6')
    assert (h6['value'], h6['band']) == (20.0, 'watch')
    _, _, rows = _rows([slow(1, 0), slow(2, 60)], [_driver(D1, 'Driver One', shift_min=240)])
    assert next(i for i in rows[D1]['health_detail']['inputs'] if i['id'] == 'H6')['band'] is None


def test_carryover_counts_as_open_job_but_not_as_assigned():
    carry = _job(3, -60, 20, in_day=False)
    _, _, rows = _rows([carry, _job(1, 10, 50)], [_driver(D1, 'Driver One')])
    assert rows[D1]['assigned'] == 1 and rows[D1]['metrics']['M06']['value'] == 2


def test_drop_off_never_counts():
    _, v, rows = _rows([_job(4, 10, 50, is_drop_off=True)], [_driver(D1, 'Driver One')])
    assert v == {} and rows[D1]['assigned'] == 0 and rows[D1]['metrics']['M06']['value'] == 0


_SNAP = os.path.expanduser('~/.fslapp/report_card/0HhPb00000007qGKAQ_2026-09-28.snapshot.json')


@pytest.mark.skipif(not os.path.exists(_SNAP), reason='local 9/28 snapshot not built on this machine')
def test_golden_h1_on_the_saved_wny_snapshot():
    """Spec 5A: 4 healthy / 6 watch / 2 unhealthy; both unhealthy drivers are scheduler-owned."""
    import json
    snap = json.load(open(_SNAP))
    v = score_snapshot(snap, RULES)
    rows = driver_day(snap, v, RULES)
    assert Counter(r['health'] for r in rows) == {'healthy': 4, 'watch': 6, 'unhealthy': 2}
    assert {r['health_owner'] for r in rows if r['health'] == 'unhealthy'} == {'scheduler'}
