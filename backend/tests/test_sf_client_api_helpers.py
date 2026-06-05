"""Tests for shared Salesforce REST API helper primitives."""

import pytest
from copy import deepcopy


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, deepcopy(kwargs)))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, deepcopy(kwargs)))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_sf_state(monkeypatch):
    import sf_client

    sf_client._call_timestamps.clear()
    sf_client._stats.update({"total_calls": 0, "errors": 0, "rate_waits": 0, "breaker_trips": 0})
    sf_client._recent_errors.clear()
    monkeypatch.setattr(sf_client, "get_auth", lambda: ("token-1", "https://example.my.salesforce.com"))
    monkeypatch.setattr(sf_client, "refresh_auth", lambda: ("token-2", "https://example.my.salesforce.com"))


def test_sf_rest_get_builds_versioned_path_and_params(monkeypatch):
    import sf_client

    fake = _FakeSession([_FakeResponse(payload={"records": []})])
    monkeypatch.setattr(sf_client, "_session", fake)

    result = sf_client.sf_rest_get("/query", params={"q": "SELECT Id FROM Account"})

    assert result == {"records": []}
    method, url, kwargs = fake.calls[0]
    assert method == "GET"
    assert url == "https://example.my.salesforce.com/services/data/v65.0/query"
    assert kwargs["params"] == {"q": "SELECT Id FROM Account"}
    assert kwargs["headers"]["Authorization"] == "Bearer token-1"
    assert sf_client.get_stats()["total_calls"] == 1


def test_sf_rest_get_refreshes_auth_once_on_401(monkeypatch):
    import sf_client

    fake = _FakeSession([
        _FakeResponse(status_code=401, payload=[{"errorCode": "INVALID_SESSION_ID"}]),
        _FakeResponse(status_code=200, payload={"ok": True}),
    ])
    monkeypatch.setattr(sf_client, "_session", fake)

    result = sf_client.sf_rest_get("/limits")

    assert result == {"ok": True}
    assert fake.calls[0][2]["headers"]["Authorization"] == "Bearer token-1"
    assert fake.calls[1][2]["headers"]["Authorization"] == "Bearer token-2"
    assert sf_client.get_stats()["total_calls"] == 1


def test_sf_composite_batch_posts_subrequests(monkeypatch):
    import sf_client

    fake = _FakeSession([_FakeResponse(payload={"hasErrors": False, "results": []})])
    monkeypatch.setattr(sf_client, "_session", fake)

    result = sf_client.sf_composite_batch([
        {"method": "GET", "url": "/services/data/v65.0/query?q=SELECT+Id+FROM+Account"},
        {"method": "GET", "url": "/services/data/v65.0/limits"},
    ])

    assert result == {"hasErrors": False, "results": []}
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://example.my.salesforce.com/services/data/v65.0/composite/batch"
    assert kwargs["json"] == {
        "haltOnError": False,
        "batchRequests": [
            {"method": "GET", "url": "/services/data/v65.0/query?q=SELECT+Id+FROM+Account"},
            {"method": "GET", "url": "/services/data/v65.0/limits"},
        ],
    }


def test_sf_query_explain_uses_explain_param(monkeypatch):
    import sf_client

    fake = _FakeSession([_FakeResponse(payload={"plans": [{"cardinality": 1}]})])
    monkeypatch.setattr(sf_client, "_session", fake)

    result = sf_client.sf_query_explain("SELECT Id FROM ServiceAppointment LIMIT 1")

    assert result == {"plans": [{"cardinality": 1}]}
    method, url, kwargs = fake.calls[0]
    assert method == "GET"
    assert url == "https://example.my.salesforce.com/services/data/v65.0/query"
    assert kwargs["params"] == {"explain": "SELECT Id FROM ServiceAppointment LIMIT 1"}
