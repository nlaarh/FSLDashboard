"""Live Dispatch 'completed in the last hour' must carry a CreatedDate bound (without it: full scan of ~1M appointments)."""

from routers import live_dispatch


def test_completed_last_hour_query_is_bounded_by_created_date(monkeypatch):
    seen = []

    def fake_all(soql, **kw):
        seen.append(soql)
        return []

    monkeypatch.setattr(live_dispatch, 'sf_query_all', fake_all)
    monkeypatch.setattr(live_dispatch, 'sf_parallel', lambda **fns: {k: f() for k, f in fns.items()})

    live_dispatch._build_live_dispatch()

    completed = next(q for q in seen if "StatusCategory IN ('Completed')" in q)
    assert 'ActualEndTime >=' in completed
    assert 'CreatedDate >=' in completed
