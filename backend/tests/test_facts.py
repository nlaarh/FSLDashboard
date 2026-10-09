"""Speed batch 3, item 2: daily facts. The builder, storage, coverage rules and the two screens that read them.

The key tests feed the SAME fake Salesforce rows to today's Salesforce code (routers/reporting.py, routers/dispatch_trends.py)
and to the facts path, and require the same numbers. Local fakes only (SQLite in memory); no network, no real database."""

import copy
from datetime import datetime, timedelta, timezone

import pytest

import facts_build
import facts_job
import facts_reporting
import facts_store
import facts_trends
from tests import facts_synthetic as syn
from tests.speed3_fixtures import flags, speed3_sqlite  # noqa: F401

DAY0, DAY1, DAY2 = syn.DAYS
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
TIDS = [t for t, _ in syn.GARAGES]


@pytest.fixture(scope='module')
def data():
    return syn.make()


def day_of(sa):
    return sa['CreatedDate'][:10]


def store_all(conn, data, computed_at=NOW):
    """Build and store each fake day the way the job does (rows of that day only)."""
    for day in syn.DAYS:
        sas = [s for s in data['sas'] if day_of(s) == day]
        ids = {s['Id'] for s in sas}
        built = {'day': day, 'computed_at': computed_at, 'version': facts_build.FACTS_VERSION,
                 'garages': facts_build.compute_garage_facts(
                     sas, [h for h in data['history'] if h['ServiceAppointmentId'] in ids],
                     [a for a in data['assign'] if a['ServiceAppointmentId'] in ids]),
                 'reassignments': facts_build.count_reassignments(data['reassign'], day)}
        built['sa_count'] = sum(g['t_volume'] for g in built['garages'].values())
        import db_adapter
        with db_adapter.writer() as db:
            facts_store.write_day(db, built)
        conn.commit()


# ── reporting: same rows as today's Salesforce path ──────────────────────────────────────────────────────────────

def fake_reporting_sf(monkeypatch, data):
    import routers.reporting as rep

    def sf_query_all(soql):
        if 'Survey_Result__c' in soql:
            return copy.deepcopy(data['surveys'])
        lo = soql.split('CreatedDate >= ')[1].split(' ')[0]
        hi = soql.split('CreatedDate < ')[1].split('\n')[0].split(' ')[0]
        out = [s for s in data['sas'] if f'{lo[:10]}' <= s['CreatedDate'][:10] and s['CreatedDate'][:19] + 'Z' < hi
               and s['Status'] in facts_build.R_STATUSES]
        return copy.deepcopy(out)

    monkeypatch.setattr(rep, 'sf_query_all', sf_query_all)
    monkeypatch.setattr(rep, 'batch_soql_parallel',
                        lambda tpl, ids, chunk_size=200: copy.deepcopy([h for h in data['history'] if h['ServiceAppointmentId'] in set(ids)]))
    monkeypatch.setattr('repositories.accounting.bonus_for_pct', lambda pct: (2.0, 'Tier X') if pct and pct >= 90 else (0.0, 'None'))
    return rep


@pytest.mark.parametrize('first,last', [(DAY0, DAY0), (DAY1, DAY2), (DAY0, DAY2)])
def test_reporting_from_facts_equals_the_salesforce_path(speed3_sqlite, monkeypatch, data, first, last):
    rep = fake_reporting_sf(monkeypatch, data)
    old = rep._compute_bulk_report(TIDS, first, last)
    assert old and any(r['avg_ata'] is not None for r in old)
    store_all(speed3_sqlite, data)
    flags(monkeypatch, daily_facts=True)
    monkeypatch.setattr(facts_store, 'covered', lambda a, b, now=None: True)
    new = facts_reporting.rows_or_none(TIDS, first, last, lambda: rep._fetch_surveys(f'{first}T00:00:00Z', f'{last}T23:59:59Z'))
    assert new == old


def test_reporting_asks_salesforce_for_surveys_only_when_it_uses_the_facts(speed3_sqlite, monkeypatch, data):
    rep = fake_reporting_sf(monkeypatch, data)
    calls = []
    monkeypatch.setattr(rep, 'sf_query_all', lambda q: calls.append(q) or [])
    monkeypatch.setattr(facts_store, 'covered', lambda a, b, now=None: True)
    store_all(speed3_sqlite, data)
    flags(monkeypatch, daily_facts=True)
    rep._bulk_rows(TIDS, DAY0, DAY2)
    assert len(calls) == 1 and 'Survey_Result__c' in calls[0]


def test_reporting_flag_off_or_range_not_covered_takes_the_salesforce_path(speed3_sqlite, monkeypatch, data):
    rep = fake_reporting_sf(monkeypatch, data)
    old = rep._compute_bulk_report(TIDS, DAY0, DAY2)
    flags(monkeypatch)                                                       # flag off: the facts are not even consulted
    monkeypatch.setattr(facts_store, 'covered', lambda *a, **k: pytest.fail('flag off must not read the facts'))
    assert rep._bulk_rows(TIDS, DAY0, DAY2) == old
    flags(monkeypatch, daily_facts=True)
    monkeypatch.setattr(facts_store, 'covered', lambda *a, **k: False)       # on, but a day is missing
    assert rep._bulk_rows(TIDS, DAY0, DAY2) == old


# ── trends: same days and rankings as today's Salesforce path ────────────────────────────────────────────────────

def fake_trends_sf(monkeypatch, data):
    import routers.dispatch_trends as tr

    def sf_query_all(soql):
        if 'Survey_Result__c' in soql:
            return []
        if 'FROM ServiceAppointmentHistory' in soql:
            if 'CreatedBy.Name' in soql:
                return copy.deepcopy(data['assign'])
            if "Field = 'ERS_Assigned_Resource__c'" in soql:
                return copy.deepcopy(data['reassign'])
            return copy.deepcopy([h for h in data['history'] if h['Field'] == 'Status'])
        return copy.deepcopy(data['sas'])

    monkeypatch.setattr(tr, 'sf_query_all', sf_query_all)
    monkeypatch.setattr('sf_client.sf_query_all', sf_query_all)
    return tr


def old_trends_30d(monkeypatch, tr):
    """Run today's api_trends()._fetch() synchronously with the cache and the thread faked out."""
    import cache
    import threading
    got = {}
    monkeypatch.setattr(cache, 'get', lambda k: None)
    monkeypatch.setattr(cache, 'disk_get', lambda *a, **k: None)
    monkeypatch.setattr(cache, 'put', lambda k, v, ttl=0: got.setdefault('v', v))
    monkeypatch.setattr(cache, 'disk_put', lambda *a, **k: None)

    real_thread = threading.Thread

    class Inline(real_thread):                                              # only the trends builder runs inline
        def start(self):
            if getattr(self._target, '__name__', '') == '_bg':
                self._target()
            else:
                super().start()
    monkeypatch.setattr(threading, 'Thread', Inline)
    tr.api_trends()
    return got['v']


def test_trends_from_facts_equal_the_salesforce_path(speed3_sqlite, monkeypatch, data):
    flags(monkeypatch)
    tr = fake_trends_sf(monkeypatch, data)
    old = old_trends_30d(monkeypatch, tr)
    assert [d['date'] for d in old['days']] == list(syn.DAYS) and old['top_garages'] and old['bottom_garages']
    store_all(speed3_sqlite, data)
    new = facts_trends.build_trends(facts_store.read_garage_days(DAY0, DAY2),
                                    {d: facts_build.count_reassignments(data['reassign'], d) for d in syn.DAYS}, [])
    assert new['days'] == old['days']
    assert new['top_garages'] == old['top_garages']
    assert new['bottom_garages'] == old['bottom_garages']
    assert any(d['reassignments'] for d in new['days']) and any(d['fleet_ata'] for d in new['days'])


def test_trends_fetch_uses_the_facts_only_when_flag_on_and_all_thirty_days_are_covered(speed3_sqlite, monkeypatch, data):
    flags(monkeypatch, daily_facts=True)
    monkeypatch.setattr(facts_store, 'covered', lambda *a, **k: False)
    assert facts_trends.trends_or_none(NOW) is None                          # a day is missing: today's path
    flags(monkeypatch)
    monkeypatch.setattr(facts_store, 'covered', lambda *a, **k: pytest.fail('flag off must not read the facts'))
    assert facts_trends.trends_or_none(NOW) is None


# ── the reassignment count ───────────────────────────────────────────────────────────────────────────────────────

def test_reassignments_count_second_and_later_name_rows_by_the_day_of_the_row():
    rows = [{'ServiceAppointmentId': 'S1', 'CreatedDate': '2026-10-05T23:50:00.000+0000', 'NewValue': 'Al One'},
            {'ServiceAppointmentId': 'S1', 'CreatedDate': '2026-10-05T23:50:00.000+0000', 'NewValue': '0Hn000000000000001'},
            {'ServiceAppointmentId': 'S1', 'CreatedDate': '2026-10-06T00:10:00.000+0000', 'NewValue': 'Bo Two'},
            {'ServiceAppointmentId': 'S1', 'CreatedDate': '2026-10-06T00:10:00.000+0000', 'NewValue': '0Hn000000000000002'},
            {'ServiceAppointmentId': 'S2', 'CreatedDate': '2026-10-06T01:00:00.000+0000', 'NewValue': 'Cy One'}]
    assert facts_build.count_reassignments(rows, '2026-10-06') == 1          # S1's second driver; S2's first is not one
    assert facts_build.count_reassignments(rows, '2026-10-05') == 0


# ── coverage and schedule ────────────────────────────────────────────────────────────────────────────────────────

def row(computed_at, version=facts_build.FACTS_VERSION):
    return {'computed_at': computed_at, 'version': version, 'sa_count': 1, 'reassignments': 0}


def test_a_past_day_counts_only_after_it_settled_today_only_while_fresh_future_days_always():
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert facts_store.is_covered('2026-10-07', row(datetime(2026, 10, 8, 4, 5, tzinfo=timezone.utc)), now)         # 4 h after the day ended (settles at 3 h)
    assert not facts_store.is_covered('2026-10-07', row(datetime(2026, 10, 7, 23, 0, tzinfo=timezone.utc)), now)    # computed before it ended
    assert not facts_store.is_covered('2026-10-07', None, now)
    assert not facts_store.is_covered('2026-10-07', row(datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc), version=0), now)
    assert facts_store.is_covered('2026-10-09', row(now - timedelta(minutes=80)), now)
    assert not facts_store.is_covered('2026-10-09', row(now - timedelta(minutes=100)), now)
    assert facts_store.is_covered('2026-10-12', None, now)


def test_job_schedule_today_hourly_a_past_day_after_settling_and_once_more_at_28_hours():
    end = datetime(2026, 10, 8, 0, 0, tzinfo=timezone.utc)                    # day 2026-10-07 ended here
    r = lambda h: row(end + timedelta(hours=h))                                # noqa: E731
    assert facts_store.needs_refresh('2026-10-07', None, end)
    assert not facts_store.needs_refresh('2026-10-07', r(-0.5), end + timedelta(hours=1))      # settle point not reached yet
    assert facts_store.needs_refresh('2026-10-07', r(-0.5), end + timedelta(hours=3))          # computed live: redo once settled
    assert not facts_store.needs_refresh('2026-10-07', r(4.1), end + timedelta(hours=27))
    assert facts_store.needs_refresh('2026-10-07', r(4.1), end + timedelta(hours=28))
    assert not facts_store.needs_refresh('2026-10-07', r(28.1), end + timedelta(hours=60))     # final
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert not facts_store.needs_refresh('2026-10-09', row(now - timedelta(minutes=30)), now)
    assert facts_store.needs_refresh('2026-10-09', row(now - timedelta(minutes=61)), now)


def test_store_roundtrip_coverage_and_retention(speed3_sqlite, data):
    store_all(speed3_sqlite, data, computed_at=datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc))
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert facts_store.covered(DAY0, DAY2, now)
    assert not facts_store.covered('2026-10-04', DAY2, now)                  # a day with no facts
    assert facts_store.covered(DAY0, '2026-10-12', now) is False             # 10-08 and 10-09 have none
    rows = facts_store.read_garage_days(DAY0, DAY0)
    assert {r['territory_id'] for r in rows} <= set(TIDS) and all(isinstance(r['ata'], list) for r in rows)


def test_purge_removes_only_old_days(speed3_sqlite, data):
    store_all(speed3_sqlite, data, computed_at=datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc))
    total = len(facts_store.read_garage_days(DAY0, DAY2))
    res = facts_store.purge(datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc) + timedelta(days=1), keep_days=3)     # keeps 10-05 onward? cut = 10-05
    assert res == {'garage_days': 0, 'days': 0}
    res = facts_store.purge(datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc), keep_days=3)                         # cut = 10-06: drops 10-05
    assert res['days'] == 1 and res['garage_days'] > 0
    assert len(facts_store.read_garage_days(DAY0, DAY2)) < total


# ── the job and the backfill tool ────────────────────────────────────────────────────────────────────────────────

def fake_build(monkeypatch, log):
    def build_day(day, now=None):
        log.append(day)
        return {'day': day, 'computed_at': NOW, 'version': facts_build.FACTS_VERSION, 'sa_count': 1, 'reassignments': 0,
                'garages': {}, 'requests': 13}
    monkeypatch.setattr(facts_build, 'build_day', build_day)


def test_job_builds_missing_days_oldest_first_and_then_leaves_them_alone(speed3_sqlite, monkeypatch):
    log = []
    fake_build(monkeypatch, log)
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    facts_job.run_once(now)
    assert log == ['2026-10-07', '2026-10-08', '2026-10-09']
    # NOW (fake computed_at) is 12:00 on the 9th, so the past days were computed after settling and today is fresh
    log.clear()
    assert facts_job.run_once(now + timedelta(minutes=10)) == [] and log == []


def test_backfill_dry_run_writes_nothing_and_a_real_run_goes_one_day_at_a_time(speed3_sqlite, monkeypatch):
    log, out = [], []
    fake_build(monkeypatch, log)
    assert facts_job.backfill('2026-09-01', '2026-09-03', yes=False, out=out.append) == [] and log == []
    assert 'dry run' in out[-1]
    done = facts_job.backfill('2026-09-01', '2026-09-03', pause_s=0, yes=True, out=out.append)
    assert log == ['2026-09-01', '2026-09-02', '2026-09-03'] and len(done) == 3
    with pytest.raises(SystemExit):
        facts_job.backfill('2026-01-01', '2026-12-31', yes=True, out=out.append)       # more than 120 days at once


def test_a_day_build_makes_four_sequential_reads(monkeypatch):
    seen = []
    monkeypatch.setattr(facts_build, 'sf_query_all', lambda q: seen.append(q) or [])
    built = facts_build.build_day('2026-10-07', NOW)
    assert len(seen) == 4 and built['garages'] == {} and built['sa_count'] == 0
    assert "ServiceAppointmentId IN (SELECT Id FROM ServiceAppointment WHERE CreatedDate >= 2026-10-07T00:00:00Z" in seen[1]
    assert 'CreatedDate >= 2026-10-06T00:00:00Z AND CreatedDate < 2026-10-08T00:00:00Z' in seen[3]     # reassignments look one day back
