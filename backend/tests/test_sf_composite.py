"""sf_composite_query (one request, many queries) and Puller.composite (call counting, paging, errors)."""

import pytest

import report_card_build as rcb
import sf_client


def _resp(key, status=200, **body):
    return {'referenceId': key, 'httpStatusCode': status, 'body': body if status == 200 else [body]}


def test_url_encodes_soql_but_keeps_references_raw(monkeypatch):
    sent = {}
    monkeypatch.setattr(sf_client, 'sf_rest_post', lambda path, body=None, **k: sent.update(path=path, body=body) or {'compositeResponse': []})
    sf_client.sf_composite_query({'a': "SELECT Id FROM X WHERE Name = 'a b&c'",
                                  'b': "SELECT Id FROM Y WHERE ParentId = '@{a.records[0].Id}' AND Z = 'q'"})
    assert sent['path'] == '/composite'
    assert sent['body']['allOrNone'] is False
    ra, rb = sent['body']['compositeRequest']
    assert ra['method'] == 'GET' and ra['referenceId'] == 'a'
    assert ra['url'] == f"/services/data/{sf_client.SF_API_VERSION}/query?q=SELECT%20Id%20FROM%20X%20WHERE%20Name%20%3D%20%27a%20b%26c%27"
    assert "%27@{a.records[0].Id}%27" in rb['url']
    assert rb['url'].endswith('%27%20AND%20Z%20%3D%20%27q%27')


def test_returns_status_and_body_per_key(monkeypatch):
    monkeypatch.setattr(sf_client, 'sf_rest_post', lambda *a, **k: {'compositeResponse': [
        _resp('a', records=[{'Id': '1'}], done=True), {'referenceId': 'b', 'httpStatusCode': 400, 'body': [{'errorCode': 'X'}]}]})
    out = sf_client.sf_composite_query({'a': 'SELECT Id FROM A', 'b': 'SELECT Id FROM B'})
    assert out['a'] == {'status': 200, 'body': {'records': [{'Id': '1'}], 'done': True}}
    assert out['b']['status'] == 400


def test_more_than_five_queries_refused(monkeypatch):
    monkeypatch.setattr(sf_client, 'sf_rest_post', lambda *a, **k: pytest.fail('must not send'))
    with pytest.raises(ValueError):
        sf_client.sf_composite_query({str(i): 'SELECT Id FROM A' for i in range(6)})


def test_unexpected_response_raises(monkeypatch):
    monkeypatch.setattr(sf_client, 'sf_rest_post', lambda *a, **k: {'oops': 1})
    with pytest.raises(RuntimeError):
        sf_client.sf_composite_query({'a': 'SELECT Id FROM A'})


def _fake(monkeypatch, responses):
    monkeypatch.setattr(rcb, 'sf_composite_query', lambda named: responses)


def test_puller_composite_counts_one_call_and_returns_records(monkeypatch):
    _fake(monkeypatch, {'a': {'status': 200, 'body': {'records': [{'Id': '1'}], 'done': True}},
                        'b': {'status': 200, 'body': {'records': [], 'done': True}}})
    p = rcb.Puller()
    assert p.composite({'a': 'x', 'b': 'y'}) == {'a': [{'Id': '1'}], 'b': []}
    assert p.calls == 1


def test_puller_composite_follows_next_records_url(monkeypatch):
    _fake(monkeypatch, {'a': {'status': 200, 'body': {'records': [{'Id': '1'}], 'done': False, 'nextRecordsUrl': '/services/data/v65.0/query/01g-2000'}}})
    monkeypatch.setattr(rcb, 'sf_rest_get', lambda url: {'records': [{'Id': '2'}], 'done': True})
    p = rcb.Puller()
    assert p.composite({'a': 'x'}) == {'a': [{'Id': '1'}, {'Id': '2'}]}
    assert p.calls == 2


def test_puller_composite_failed_subrequest_raises(monkeypatch):
    _fake(monkeypatch, {'a': {'status': 400, 'body': [{'errorCode': 'INVALID_QUERY_FILTER_OPERATOR'}]}})
    with pytest.raises(rcb.CompositeError) as e:
        rcb.Puller().composite({'a': 'x'})
    assert e.value.key == 'a'


def test_puller_composite_truncated_child_raises(monkeypatch):
    rec = {'Id': '1', 'SMS_Send_Logs__r': {'records': [{}], 'done': False}}
    _fake(monkeypatch, {'a': {'status': 200, 'body': {'records': [rec], 'done': True}}})
    with pytest.raises(rcb.CompositeError):
        rcb.Puller().composite({'a': 'x'})


def test_puller_composite_respects_call_cap(monkeypatch):
    _fake(monkeypatch, {})
    with pytest.raises(rcb.CallCapReached):
        rcb.Puller(max_calls=0).composite({'a': 'x'})
