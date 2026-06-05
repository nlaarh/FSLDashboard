"""Tests for data quality Salesforce query batching helpers."""

from urllib.parse import parse_qs, urlparse


def test_data_quality_query_requests_use_single_composite_batch_window():
    from routers.data_quality_queries import COMPOSITE_QUERY_KEYS, data_quality_query_requests

    requests = data_quality_query_requests("2026-05-08T00:00:00Z")

    assert len(requests) == 14
    assert {request["method"] for request in requests} == {"GET"}
    assert "dispatch_sample" not in COMPOSITE_QUERY_KEYS
    assert "referenceId" not in requests[0]
    assert all(request["url"].startswith("/services/data/v65.0/query?") for request in requests)


def test_service_appointment_queries_exclude_tow_drop_off():
    from routers.data_quality_queries import data_quality_soql

    queries = data_quality_soql("2026-05-08T00:00:00Z")
    service_appointment_keys = {
        key
        for key, soql in queries.items()
        if "\nFROM ServiceAppointment\n" in f"\n{soql}\n"
    }

    assert service_appointment_keys
    for key in service_appointment_keys:
        assert "WorkType.Name != 'Tow Drop-Off'" in queries[key]


def test_composite_urls_preserve_soql_in_query_param():
    from routers.data_quality_queries import data_quality_query_requests

    request = data_quality_query_requests("2026-05-08T00:00:00Z")[0]
    parsed = urlparse(request["url"])

    assert parsed.path == "/services/data/v65.0/query"
    assert parse_qs(parsed.query)["q"] == [
        "SELECT COUNT(Id) cnt\n"
        "FROM ServiceAppointment\n"
        "WHERE CreatedDate >= 2026-05-08T00:00:00Z\n"
        "  AND ServiceTerritoryId != null\n"
        "  AND WorkType.Name != 'Tow Drop-Off'"
    ]


def test_parse_composite_query_results_returns_keyed_records():
    from routers.data_quality_queries import parse_composite_query_results

    response = {
        "hasErrors": False,
        "results": [
            {
                "statusCode": 200,
                "result": {"records": [{"cnt": 12}], "done": True},
            },
            {
                "statusCode": 200,
                "result": {"records": [{"ERS_Dispatch_Method__c": "Towbook"}], "done": True},
            },
        ],
    }

    parsed = parse_composite_query_results(["total", "dispatch_sample"], response)

    assert parsed == {
        "total": [{"cnt": 12}],
        "dispatch_sample": [{"ERS_Dispatch_Method__c": "Towbook"}],
    }


def test_parse_composite_query_results_raises_on_subrequest_error():
    from routers.data_quality_queries import parse_composite_query_results

    response = {
        "hasErrors": True,
        "results": [
            {"statusCode": 200, "result": {"records": []}},
            {"statusCode": 400, "result": [{"message": "bad query"}]},
        ],
    }

    try:
        parse_composite_query_results(["total", "completed"], response)
    except RuntimeError as exc:
        assert "completed" in str(exc)
        assert "400" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


def test_data_quality_fetch_defaults_to_parallel(monkeypatch):
    from routers import data_quality

    calls = []
    monkeypatch.delenv("SF_DATA_QUALITY_COMPOSITE", raising=False)
    monkeypatch.setattr(data_quality, "data_quality_soql", lambda since: {"total": "SELECT COUNT(Id) cnt FROM ServiceAppointment"})
    monkeypatch.setattr(data_quality, "_fetch_data_quality_parallel", lambda queries: calls.append(("parallel", queries)) or {"total": [{"cnt": 1}]})
    monkeypatch.setattr(data_quality, "_fetch_data_quality_composite", lambda queries, since: calls.append(("composite", queries)) or {})

    result = data_quality._fetch_salesforce_data_quality("2026-05-08T00:00:00Z")

    assert result == {"total": [{"cnt": 1}]}
    assert calls == [("parallel", {"total": "SELECT COUNT(Id) cnt FROM ServiceAppointment"})]


def test_data_quality_fetch_uses_composite_when_enabled(monkeypatch):
    from routers import data_quality

    calls = []
    monkeypatch.setenv("SF_DATA_QUALITY_COMPOSITE", "true")
    monkeypatch.setattr(data_quality, "data_quality_soql", lambda since: {"total": "SELECT COUNT(Id) cnt FROM ServiceAppointment"})
    monkeypatch.setattr(data_quality, "_fetch_data_quality_parallel", lambda queries: calls.append(("parallel", queries)) or {})
    monkeypatch.setattr(data_quality, "_fetch_data_quality_composite", lambda queries, since: calls.append(("composite", since)) or {"total": [{"cnt": 2}]})

    result = data_quality._fetch_salesforce_data_quality("2026-05-08T00:00:00Z")

    assert result == {"total": [{"cnt": 2}]}
    assert calls == [("composite", "2026-05-08T00:00:00Z")]
