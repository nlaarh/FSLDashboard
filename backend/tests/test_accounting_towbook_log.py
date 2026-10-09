"""Accounting audit: the Towbook log query must be date-bounded (a full scan of 367k rows took 6 s) and must
use the reference Towbook really writes ('084-<date>-<work order number>')."""

import inspect

import pytest

import sf_client
from routers import accounting_audit
from routers.accounting_towbook_log import towbook_log_soql


def test_query_is_bounded_to_the_work_orders_dates():
    soql = towbook_log_soql('05199467', '2026-10-09T07:10:20.000+0000')
    assert 'CreatedDate >= 2026-10-08T07:10:20Z' in soql      # 1 day before creation
    assert 'CreatedDate < 2026-10-12T07:10:20Z' in soql       # 3 days after creation
    assert "'084-20261009-05199467'" in soql                  # the reference Towbook writes
    assert "'05199467'" in soql                               # plain number kept for older logs
    assert soql.rstrip().endswith('LIMIT 50')


def test_late_evening_call_tries_both_the_eastern_and_the_utc_date():
    soql = towbook_log_soql('05200001', '2026-10-10T02:30:00.000+0000')   # 22:30 on Oct 9 in New York
    assert "'084-20261009-05200001'" in soql
    assert "'084-20261010-05200001'" in soql


def test_unknown_creation_date_never_sends_an_unbounded_scan():
    assert towbook_log_soql('05199467', None) is None
    assert towbook_log_soql('05199467', 'not a date') is None
    assert towbook_log_soql('', '2026-10-09T07:10:20.000+0000') is None


def test_work_order_number_cannot_inject_soql():
    with pytest.raises(ValueError):
        towbook_log_soql("1;x", '2026-10-09T07:10:20.000+0000')


def test_audit_reads_the_log_through_the_shared_single_flight_read():
    src = inspect.getsource(accounting_audit._build_woa_data)
    assert 'sf_query_all_shared(soql' in src
    assert 'Work_Order__r.CreatedDate' in src


def test_five_identical_reads_make_one_salesforce_query(monkeypatch):
    calls = []
    monkeypatch.setattr(sf_client, 'sf_query_all', lambda soql, **kw: calls.append(soql) or [{'CreatedDate': 'x'}])
    sf_client._shared.clear()
    soql = towbook_log_soql('05199467', '2026-10-09T07:10:20.000+0000')
    for _ in range(5):
        assert sf_client.sf_query_all_shared(soql, ttl=300) == [{'CreatedDate': 'x'}]
    assert len(calls) == 1
