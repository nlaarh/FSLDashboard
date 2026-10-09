"""Speed batch 3: the migration is additive and idempotent, nothing runs with the flags off, and the lock behaves."""

import re

import pytest

import speed3_db
from feature_flags import DEFAULT_FEATURES
from tests.speed3_fixtures import flags, speed3_sqlite  # noqa: F401


def test_every_statement_only_creates_if_missing():
    assert speed3_db.SCHEMA_SQL
    for stmt in speed3_db.SCHEMA_SQL:
        assert re.match(r'^CREATE (TABLE|INDEX) IF NOT EXISTS ', stmt.strip()), stmt[:60]
        assert not re.search(r'\b(ALTER|DROP|DELETE|UPDATE|TRUNCATE|INSERT)\b', stmt, re.I), stmt[:60]


def test_the_ddl_can_run_twice(speed3_sqlite):
    for stmt in speed3_db.SCHEMA_SQL:
        speed3_sqlite.execute(stmt)
    names = {r[0] for r in speed3_sqlite.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {'driver_gps_points', 'driver_gps_samples', 'facts_day', 'facts_garage_day'} <= names


def test_all_three_flags_default_off():
    for name in ('replay_gps_store', 'daily_facts', 'revenue_semijoin'):
        assert DEFAULT_FEATURES[name] is False


def test_with_the_flags_off_the_background_loops_touch_no_table(monkeypatch):
    import facts_job
    import gps_store
    flags(monkeypatch)
    monkeypatch.setattr(speed3_db, 'ensure_schema', lambda group: pytest.fail('flag off must not create tables'))
    monkeypatch.setattr(gps_store, 'sample_once', lambda *a: pytest.fail('flag off must not sample'))
    monkeypatch.setattr(facts_job, 'run_once', lambda *a: pytest.fail('flag off must not build facts'))

    class Stop(Exception):
        pass

    def one_pass(_):
        raise Stop

    monkeypatch.setattr('time.sleep', one_pass)
    for loop in (gps_store.run_forever, facts_job.run_forever):
        with pytest.raises(Stop):
            loop()


def test_ensure_schema_reports_failure_instead_of_raising(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def broken():
        raise RuntimeError('no permission to create tables')
        yield
    monkeypatch.setattr('db_adapter.writer', broken)
    monkeypatch.setattr(speed3_db, '_ready', set())
    assert speed3_db.ensure_schema('gps') is False


def test_the_lock_key_is_stable_and_per_job():
    assert speed3_db.lock_key('gps_sampler') == speed3_db.lock_key('gps_sampler') != speed3_db.lock_key('facts_job')


def test_leader_on_the_test_fake_is_the_caller(speed3_sqlite):
    with speed3_db.leader('anything') as db:
        assert db is not None


def test_a_timestamp_in_the_database_session_zone_is_converted_to_utc():
    from datetime import datetime, timedelta, timezone
    est = datetime(2026, 10, 9, 15, 36, 56, tzinfo=timezone(timedelta(hours=-4)))     # what Postgres returned with a -04 session
    assert speed3_db.as_dt(est) == datetime(2026, 10, 9, 19, 36, 56, tzinfo=timezone.utc)
    assert speed3_db.as_dt(est).hour == 19
    assert speed3_db.as_dt('2026-10-09T19:36:56+00:00').hour == 19
