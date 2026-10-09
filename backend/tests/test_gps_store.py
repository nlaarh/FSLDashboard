"""Speed batch 3, item 1: our own record of driver positions (gps_store) and its use by the Replay map. Local fakes only."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

import gps_store
import speed3_db
from tests.speed3_fixtures import flags, speed3_sqlite  # noqa: F401
from tests.test_wo_replay_map_fast import FakePuller, epoch, raw, snap  # noqa: F401
from wo_replay_map import pull_map

T0 = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


def rec(rid, ts, lat=43.0, lon=-78.0):
    return {'Id': rid, 'LastKnownLatitude': lat, 'LastKnownLongitude': lon, 'LastKnownLocationDate': ts.strftime('%Y-%m-%dT%H:%M:%S.000+0000')}


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(gps_store, '_last', {})
    monkeypatch.setattr('wo_replay_map.garage_route', lambda *a, **k: None)
    monkeypatch.setattr('wo_replay_map.snap_runs', lambda *a, **k: [])


def test_a_point_is_kept_when_first_moved_or_a_heartbeat():
    assert gps_store.keep_point(None, 100, 43.0, -78.0)
    assert not gps_store.keep_point((100, 43.0, -78.0), 130, 43.00001, -78.0)           # parked, 30 s later
    assert gps_store.keep_point((100, 43.0, -78.0), 130, 43.0005, -78.0)                # moved about 55 m
    assert gps_store.keep_point((100, 43.0, -78.0), 100 + 300, 43.0, -78.0)             # 5 min heartbeat
    assert not gps_store.keep_point((100, 43.0, -78.0), 90, 44.0, -78.0)                # older fix never replaces a newer one


def test_sample_stores_new_points_once_and_records_the_run(speed3_sqlite, monkeypatch):
    queries = []
    monkeypatch.setattr(gps_store, 'sf_query_all', lambda q: queries.append(q) or [rec('A', T0), rec('B', T0 + timedelta(seconds=5), lat=None)])
    assert gps_store.sample_once(T0 + timedelta(seconds=30)) == {'rows_seen': 2, 'points_written': 1}      # B has no position
    assert gps_store.sample_once(T0 + timedelta(seconds=90)) == {'rows_seen': 2, 'points_written': 0}      # same fix again
    pts = speed3_sqlite.execute('SELECT resource_id, lat FROM driver_gps_points').fetchall()
    assert [tuple(p) for p in pts] == [('A', 43.0)]
    assert speed3_sqlite.execute('SELECT count(*) FROM driver_gps_samples').fetchone()[0] == 2
    assert 'FROM ServiceResource' in queries[0] and "ResourceType = 'T'" in queries[0] and 'SystemModstamp >=' in queries[0]
    assert 'SystemModstamp >= 2026-10-08T15:00:25Z' in queries[1]                      # last run (15:00:30) minus 5 s


def test_only_one_worker_samples(speed3_sqlite, monkeypatch):
    @contextmanager
    def not_leader(name):
        yield None
    monkeypatch.setattr(speed3_db, 'leader', not_leader)
    monkeypatch.setattr(gps_store, 'sf_query_all', lambda q: pytest.fail('a worker that is not the leader must not query Salesforce'))
    assert gps_store.sample_once(T0) is None


def test_a_failed_salesforce_read_records_no_sample(speed3_sqlite, monkeypatch):
    def boom(q):
        raise RuntimeError('SF down')
    monkeypatch.setattr(gps_store, 'sf_query_all', boom)
    with pytest.raises(RuntimeError):
        gps_store.sample_once(T0)
    assert speed3_sqlite.execute('SELECT count(*) FROM driver_gps_samples').fetchone()[0] == 0


def test_coverage_needs_samples_with_no_hole_longer_than_five_minutes():
    s = [T0 + timedelta(seconds=60 * i) for i in range(0, 31)]                      # 15:00 .. 15:30 every minute
    now = T0 + timedelta(hours=2)
    assert gps_store.covered(s, T0, T0 + timedelta(minutes=30), now)
    assert not gps_store.covered(s, T0 - timedelta(minutes=20), T0 + timedelta(minutes=30), now)     # starts before the sampler
    assert not gps_store.covered(s, T0, T0 + timedelta(minutes=45), now)                             # runs past the last sample
    holed = [x for x in s if not (T0 + timedelta(minutes=10) < x < T0 + timedelta(minutes=18))]
    assert not gps_store.covered(holed, T0, T0 + timedelta(minutes=30), now)                         # an 8 minute hole
    assert gps_store.covered(s, T0, T0 + timedelta(hours=9), T0 + timedelta(minutes=32))             # an open call is judged up to now


def seed(conn, rid='A', minutes=range(0, 31)):
    for m in minutes:
        ts = T0 + timedelta(minutes=m)
        conn.execute('INSERT INTO driver_gps_samples VALUES (?, 1, 1)', (speed3_db.iso(ts),))
        conn.execute('INSERT INTO driver_gps_points VALUES (?, ?, ?, ?)', (rid, speed3_db.iso(ts), 43.0 + m * 0.001, -78.0))
    conn.commit()


def test_stored_rows_are_shaped_like_salesforce_history_and_only_for_covered_drivers(speed3_sqlite):
    seed(speed3_sqlite)
    now = T0 + timedelta(hours=2)
    rows, ok = gps_store.stored_gps_rows({'A': (T0, T0 + timedelta(minutes=10)), 'B': (T0 - timedelta(hours=1), T0)}, now)
    assert ok == {'A'}                                                                # B's window starts before any sample
    assert len(rows) == 22 and {r['Field'] for r in rows} == {'LastKnownLatitude', 'LastKnownLongitude'}
    assert rows[0]['ServiceResourceId'] == 'A' and rows[0]['CreatedDate'] == '2026-10-08T15:00:00.000+0000'


def test_a_database_problem_means_nothing_is_covered(monkeypatch):
    def boom(group):
        raise RuntimeError('db down')
    monkeypatch.setattr(speed3_db, 'ensure_schema', boom)
    assert gps_store.stored_gps_rows({'A': (T0, T0 + timedelta(minutes=5))}) == ([], set())


def test_purge_drops_only_old_rows(speed3_sqlite):
    now = T0 + timedelta(days=50)
    speed3_sqlite.execute('INSERT INTO driver_gps_points VALUES (?, ?, 1, 1)', ('A', speed3_db.iso(T0)))
    speed3_sqlite.execute('INSERT INTO driver_gps_points VALUES (?, ?, 1, 1)', ('A', speed3_db.iso(now - timedelta(days=1))))
    speed3_sqlite.execute('INSERT INTO driver_gps_samples VALUES (?, 1, 1)', (speed3_db.iso(T0),))
    speed3_sqlite.commit()
    assert gps_store.purge(now, keep_days=45) == {'points': 1, 'samples': 1}
    assert speed3_sqlite.execute('SELECT count(*) FROM driver_gps_points').fetchone()[0] == 1


# ── the Replay map ───────────────────────────────────────────────────────────────────────────────────────────────

def _map(monkeypatch, conn=None, **flag):
    flags(monkeypatch, **flag)
    p = FakePuller()
    return pull_map(raw(), p), p


def test_flag_off_the_map_reads_salesforce_exactly_as_before(monkeypatch):
    called = []
    monkeypatch.setattr(gps_store, 'stored_gps_rows', lambda *a, **k: called.append(1) or ([], set()))
    m, p = _map(monkeypatch)
    assert not called and any('ServiceResourceHistory' in q for q in p.queries)
    assert m['drivers'][0]['source'] == 'salesforce'


def test_flag_on_and_covered_the_map_needs_no_salesforce_history_read(speed3_sqlite, monkeypatch):
    # the call is open 15:00-16:30 on 2026-09-28; the driver's window is 14:40 to 16:35
    base = datetime(2026, 9, 28, 14, 30, tzinfo=timezone.utc)
    for m in range(0, 130):
        ts = base + timedelta(minutes=m)
        speed3_sqlite.execute('INSERT INTO driver_gps_samples VALUES (?, 1, 1)', (speed3_db.iso(ts),))
        speed3_sqlite.execute('INSERT INTO driver_gps_points VALUES (?, ?, ?, ?)', ('0HnAAAAAAAAAAAAAAA', speed3_db.iso(ts), 42.9 + m * 0.002, -78.8))
    speed3_sqlite.commit()
    m, p = _map(monkeypatch, replay_gps_store=True)
    assert p.calls == 0 and not any('ServiceResourceHistory' in q for q in p.queries)
    d = m['drivers'][0]
    assert d['source'] == 'store' and len(d['track']) >= 2 and d['pings'] == len(d['track'])
    assert d['track'] == sorted(d['track'])                                              # oldest first, epoch seconds, lat, lon


def test_flag_on_but_not_covered_falls_back_to_salesforce(speed3_sqlite, monkeypatch):
    m, p = _map(monkeypatch, replay_gps_store=True)                                        # empty store
    assert any('ServiceResourceHistory' in q for q in p.queries) and m['drivers'][0]['source'] == 'salesforce'
