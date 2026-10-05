"""While a day is still building, the page can already show its calls: the build publishes them as it goes."""

from report_card_build import preview_from_raw
from report_card_snapshot import build_snapshot
from tests.report_card_factories import tiny_raw


def test_preview_lists_the_days_calls_without_the_slow_data():
    raw = tiny_raw()
    p = preview_from_raw({k: raw[k] for k in ('sas', 'territory', 'window')})      # only the first stage is read
    assert p['drivers_known'] is False and len(p['sas']) == len([s for s in raw['sas'] if (s['CreatedDate'] or '')[:19] >= raw['window']['day_start'][:19]])
    one = p['sas'][0]
    assert {'id', 'number', 'work_type', 'status', 'created', 'woli_id', 'is_drop_off', 'driver_name'} <= set(one)
    assert [c['created'] for c in p['sas']] == sorted(c['created'] for c in p['sas'])


def test_preview_gains_driver_names_once_assignments_are_read():
    raw = tiny_raw()
    p = preview_from_raw(raw)
    assert p['drivers_known'] is True and any(c['driver_name'] for c in p['sas'])


def test_preview_leaves_out_the_carry_over_from_the_day_before():
    raw = tiny_raw()
    carry = {**raw['sas'][0], 'Id': 'CARRY', 'CreatedDate': '2000-01-01T00:00:00.000+0000'}
    assert 'CARRY' not in {c['id'] for c in preview_from_raw({**raw, 'sas': raw['sas'] + [carry]})['sas']}


def test_a_broken_progress_hook_never_breaks_the_build(monkeypatch):
    import report_card_build as rb
    class P:
        calls = 0
        def __init__(self, max_calls=None): pass
        def all(self, q): return [{'Id': 'T', 'Name': 'G', 'Latitude': 1, 'Longitude': 1}] if 'ServiceTerritory WHERE Id' in q else []
        def count(self, q): return 0
        def batched(self, *a, **k): return []
    monkeypatch.setattr(rb, 'Puller', P)
    monkeypatch.setattr(rb, '_pull_policies', lambda p, r: [])
    def boom(stage, raw): raise RuntimeError('hook failed')
    raw = rb.pull_garage_day('0HhPb00000007s3KAA', '2026-10-03', progress=boom)
    assert raw['sas'] == []                                  # finished normally despite the hook failing twice
