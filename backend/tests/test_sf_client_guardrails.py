"""sf_client guardrails: the breaker counts outages only, an API limit backs off, in-flight cap, row cap, counters."""

import threading
import time

import pytest

import sf_client


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._p = payload if payload is not None else {"records": [], "done": True}

    def json(self):
        return self._p


class _Session:
    def __init__(self, *responses, delay=0.0):
        self.responses = list(responses)
        self.calls = []
        self.delay = delay
        self.now = self.peak = 0
        self._l = threading.Lock()

    def get(self, url, **kw):
        with self._l:
            self.now += 1
            self.peak = max(self.peak, self.now)
        try:
            time.sleep(self.delay)
            self.calls.append((url, kw))
            return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        finally:
            with self._l:
                self.now -= 1

    post = get


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(sf_client, "get_auth", lambda: ("tok-1", "https://x.my.salesforce.com"))
    monkeypatch.setattr(sf_client, "_breaker_failures", 0)
    monkeypatch.setattr(sf_client, "_breaker_open_until", 0.0)
    monkeypatch.setattr(sf_client, "_RATE_LIMIT", 10_000)
    monkeypatch.setattr(sf_client._time, "sleep", lambda s: None)
    sf_client._call_timestamps.clear()
    sf_client._by_endpoint.clear()
    yield


def _install(monkeypatch, session):
    monkeypatch.setattr(sf_client, "_session", session)
    return session


BAD_QUERY = [{"errorCode": "INVALID_FIELD", "message": "no such column"}]


def test_query_mistakes_never_open_the_breaker(monkeypatch):
    _install(monkeypatch, _Session(_Resp(400, BAD_QUERY)))
    for _ in range(8):
        with pytest.raises(RuntimeError):
            sf_client.sf_query("SELECT Nope FROM Account")
    assert sf_client.get_stats()["breaker_open"] is False
    _install(monkeypatch, _Session(_Resp(200, {"records": [{"Id": "1"}], "done": True})))
    assert sf_client.sf_query("SELECT Id FROM Account")["records"] == [{"Id": "1"}]   # still answering


def test_rest_errors_do_not_open_the_breaker_either(monkeypatch):
    _install(monkeypatch, _Session(_Resp(400, [{"errorCode": "NOT_FOUND"}])))
    for _ in range(8):
        with pytest.raises(RuntimeError):
            sf_client.sf_rest_get("/sobjects/Nope")
    assert sf_client.get_stats()["breaker_open"] is False


def test_real_outages_open_the_breaker(monkeypatch):
    _install(monkeypatch, _Session(_Resp(503, {"x": 1})))
    for _ in range(sf_client._BREAKER_THRESHOLD):
        with pytest.raises(RuntimeError):
            sf_client.sf_query("SELECT Id FROM Account")
    assert sf_client.get_stats()["breaker_open"] is True
    with pytest.raises(sf_client.SalesforceUnavailable):
        sf_client.sf_query("SELECT Id FROM Account")


def test_api_limit_backs_off_without_login_or_retry(monkeypatch):
    sess = _install(monkeypatch, _Session(_Resp(403, [{"errorCode": "REQUEST_LIMIT_EXCEEDED", "message": "TotalRequests Limit exceeded."}])))
    logins = []
    monkeypatch.setattr(sf_client, "refresh_auth", lambda *a: logins.append(a) or ("tok-2", "https://x.my.salesforce.com"))

    with pytest.raises(RuntimeError, match="REQUEST_LIMIT_EXCEEDED"):
        sf_client.sf_query("SELECT Id FROM Account")

    assert len(sess.calls) == 1 and logins == []             # one request, no login, no instant retry
    assert sf_client.get_stats()["breaker_open"] is True
    with pytest.raises(sf_client.SalesforceUnavailable):      # and nothing else is sent for the cooldown
        sf_client.sf_query("SELECT Id FROM Account")
    assert len(sess.calls) == 1


def test_api_limit_on_rest_calls_backs_off_too(monkeypatch):
    sess = _install(monkeypatch, _Session(_Resp(403, [{"errorCode": "REQUEST_LIMIT_EXCEEDED"}])))
    monkeypatch.setattr(sf_client, "refresh_auth", lambda *a: pytest.fail("must not log in again"))
    with pytest.raises(RuntimeError, match="REQUEST_LIMIT_EXCEEDED"):
        sf_client.sf_rest_get("/limits")
    assert len(sess.calls) == 1 and sf_client.get_stats()["breaker_open"] is True


def test_expired_session_logs_in_once_with_the_failed_token(monkeypatch):
    sess = _install(monkeypatch, _Session(_Resp(401, [{"errorCode": "INVALID_SESSION_ID"}]), _Resp(200, {"records": [], "done": True})))
    seen = []
    monkeypatch.setattr(sf_client, "refresh_auth", lambda tok=None: seen.append(tok) or ("tok-2", "https://x.my.salesforce.com"))
    assert sf_client.sf_query("SELECT Id FROM Account")["records"] == []
    assert seen == ["tok-1"] and len(sess.calls) == 2
    assert sess.calls[1][1]["headers"]["Authorization"] == "Bearer tok-2"


def test_refresh_skips_the_login_when_another_thread_already_renewed_the_token(monkeypatch):
    monkeypatch.setattr(sf_client, "_token", "new-token")
    monkeypatch.setattr(sf_client, "_instance", "https://y")
    monkeypatch.setattr(sf_client, "_authenticate", lambda: pytest.fail("second login"))
    assert sf_client.refresh_auth("old-token") == ("new-token", "https://y")


def test_no_more_than_the_cap_is_in_flight(monkeypatch):
    monkeypatch.setattr(sf_client, "_inflight", threading.BoundedSemaphore(3))
    sess = _install(monkeypatch, _Session(_Resp(200, {"records": [], "done": True}), delay=0.05))
    threads = [threading.Thread(target=sf_client.sf_query, args=("SELECT Id FROM Account",)) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(sess.calls) == 12 and sess.peak <= 3


def test_waiting_for_a_slot_gives_up_instead_of_piling_up(monkeypatch):
    sem = threading.BoundedSemaphore(1)
    sem.acquire()                                              # every slot is busy
    monkeypatch.setattr(sf_client, "_inflight", sem)
    monkeypatch.setattr(sf_client, "_INFLIGHT_WAIT", 0.05)
    sess = _install(monkeypatch, _Session(_Resp()))
    with pytest.raises(sf_client.SalesforceUnavailable):
        sf_client.sf_query("SELECT Id FROM Account")
    assert sess.calls == [] and sf_client.get_stats()["breaker_open"] is False


def _pages(n, per=2):
    out = []
    for i in range(n):
        last = i == n - 1
        out.append(_Resp(200, {"records": [{"Id": f"{i}-{j}"} for j in range(per)], "done": last,
                               **({} if last else {"nextRecordsUrl": f"/services/data/v65.0/query/p{i + 1}"})}))
    return out


def test_row_cap_stops_paging_and_returns_exactly_that_many(monkeypatch):
    sess = _install(monkeypatch, _Session(*_pages(5)))
    rows = sf_client.sf_query_all("SELECT Id FROM Account", max_records=3)
    assert len(rows) == 3 and len(sess.calls) == 2             # 2 pages were enough; the other 3 were never requested


def test_without_a_cap_every_page_is_read(monkeypatch):
    sess = _install(monkeypatch, _Session(*_pages(3)))
    assert len(sf_client.sf_query_all("SELECT Id FROM Account")) == 6 and len(sess.calls) == 3


def test_requests_are_counted_per_endpoint(monkeypatch):
    _install(monkeypatch, _Session(_Resp()))
    tok = sf_client.sf_endpoint.set("/api/watchlist")
    try:
        sf_client.sf_query("SELECT Id FROM Account")
        sf_client.sf_query("SELECT Id FROM Account")
    finally:
        sf_client.sf_endpoint.reset(tok)
    sf_client.sf_query("SELECT Id FROM Account")
    by = sf_client.get_stats()["requests_by_endpoint"]
    assert by["/api/watchlist"] == 2 and by["background"] == 1


def test_endpoint_label_hides_ids():
    assert sf_client.endpoint_label("/api/garages/0HhPb0000004Cb5/scorecard") == "/api/garages/{id}/scorecard"
    assert sf_client.endpoint_label("/api/map/drivers") == "/api/map/drivers"


def test_parallel_threads_are_counted_for_the_same_endpoint(monkeypatch):
    _install(monkeypatch, _Session(_Resp()))
    tok = sf_client.sf_endpoint.set("/api/command-center")
    try:
        sf_client.sf_parallel(a=lambda: sf_client.sf_query("SELECT Id FROM A"), b=lambda: sf_client.sf_query("SELECT Id FROM B"))
    finally:
        sf_client.sf_endpoint.reset(tok)
    assert sf_client.get_stats()["requests_by_endpoint"] == {"/api/command-center": 2}


def test_web_middleware_pattern_reaches_sync_endpoints():
    """The tag set in an http middleware (main.py) is visible inside a normal (threadpool) endpoint."""
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    app = FastAPI()

    @app.middleware("http")
    async def tag(request: Request, call_next):
        sf_client.sf_endpoint.set(sf_client.endpoint_label(request.url.path))
        return await call_next(request)

    @app.get("/api/garages/{gid}/scorecard")
    def ep(gid: str):
        return {"seen": sf_client.sf_endpoint.get()}

    assert TestClient(app).get("/api/garages/0Hh123/scorecard").json() == {"seen": "/api/garages/{id}/scorecard"}
