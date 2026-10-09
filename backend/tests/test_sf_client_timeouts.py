"""Salesforce read timeout: 20 s by default, longer only when a caller asks for it."""

import sf_client


class _Resp:
    status_code = 200

    def json(self):
        return {"records": [], "done": True}


class _Session:
    def __init__(self):
        self.timeouts = []

    def get(self, url, **kwargs):
        self.timeouts.append(kwargs["timeout"])
        return _Resp()


def test_default_is_20s_and_long_callers_can_ask_for_more(monkeypatch):
    fake = _Session()
    monkeypatch.setattr(sf_client, "_session", fake)
    monkeypatch.setattr(sf_client, "get_auth", lambda: ("t", "https://x.my.salesforce.com"))

    sf_client.sf_query_all("SELECT Id FROM Account")
    sf_client.sf_query_all("SELECT Id FROM ServiceResourceHistory", timeout=sf_client.TIMEOUT_LONG)

    assert fake.timeouts[0] == (5, 20)
    assert fake.timeouts[1] == sf_client.TIMEOUT_LONG
    assert sf_client.TIMEOUT_LONG[1] > 20


def test_history_and_bulk_callers_use_the_long_timeout():
    import inspect, sf_batch, report_card_build
    assert "TIMEOUT_LONG" in inspect.getsource(sf_batch)
    assert "TIMEOUT_LONG" in inspect.getsource(report_card_build.Puller.all)
