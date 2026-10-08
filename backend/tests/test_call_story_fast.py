"""Call Story fast path: the whole story from one bundled Salesforce request, with the sequential reads as fallback."""

from datetime import datetime, timezone

import pytest

import call_story_pull as cp
import report_card_build as rb
from call_story_compose import compose
from call_story_config import cs1
from tests.call_story_factories import FakeNorms, towbook_cascade_raw

CFG = cs1()
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def _bundle(monkeypatch, raw=None, wo_rows=None):
    """Fake the bundled request: the WO row carries its SAs, texts and survey as child records."""
    raw = raw or towbook_cascade_raw()
    sent = {}

    def child(rows):
        return {'totalSize': len(rows), 'done': True, 'records': rows}
    wo = {**raw['wo'], 'Service_Appointments_del__r': child(raw['sas']), 'SMS_Send_Logs__r': child(raw['sms']),
          'Work_Order_Survey_Results__r': child([])}

    def ok(rows):
        return {'status': 200, 'body': {'records': rows, 'done': True}}

    def fake(named):
        sent.update(named)
        return {'wo': ok([wo] if wo_rows is None else wo_rows), 'hist': ok(raw['history']), 'ar': ok(raw['assigned'])}
    monkeypatch.setattr(rb, 'sf_composite_query', fake)
    monkeypatch.setattr(cp, '_matrix', lambda p, sas: None)              # optional extras are not under test here
    monkeypatch.setattr(cp, '_optimizer', lambda p, raw: None)
    monkeypatch.setattr('cache.get', lambda key: None)
    monkeypatch.setattr('cache.put', lambda *a, **k: None)
    return raw, sent


def test_story_is_one_salesforce_call_and_the_same_raw_shape(monkeypatch):
    raw, sent = _bundle(monkeypatch)
    out = cp.pull_story('05164342', CFG, now=NOW)
    assert out['sf_calls'] == 1 and set(sent) == {'wo', 'hist', 'ar'}
    assert out['sas'] == raw['sas'] and out['history'] == raw['history'] and out['sms'] == raw['sms'] and out['survey'] == []
    assert out['sms_source'] == 'send_log' and out['resolution']['wo']['number'] == '05164342'
    assert not any(k.endswith('__r') for k in out['wo'])                    # child rows moved out of the WO
    assert '@{wo.records[0].Id}' in sent['hist'] and '@{wo.records[0].Id}' in sent['ar']
    assert 'Mobile_Phone__c' not in ''.join(sent.values())                  # phones are never read here


def test_fast_story_composes_like_the_slow_one(monkeypatch):
    _bundle(monkeypatch)
    out = cp.pull_story('05164342', CFG, now=NOW)
    s = compose(out, CFG, snapshot_for=lambda t, d: None, norms_for=lambda d: FakeNorms(), now=NOW)
    assert s['verdict']['primary'] == 'NOT_GRADED_TOWBOOK'


def test_fast_story_ambiguous_number_gives_the_same_candidates(monkeypatch):
    raw = towbook_cascade_raw()
    rows = [{**raw['wo'], 'WorkOrderNumber': '05211381'}, {**raw['wo'], 'WorkOrderNumber': '05172864'}]
    _bundle(monkeypatch, raw, rows)
    with pytest.raises(cp.Ambiguous) as e:
        cp.pull_story('05211381', CFG, now=NOW)
    assert [c['type'] for c in e.value.candidates] == ['wo', 'source_call_id']


def test_fast_story_no_work_order_is_not_found(monkeypatch):
    _bundle(monkeypatch, wo_rows=[])
    with pytest.raises(cp.NotFound):
        cp.pull_story('05164342', CFG, now=NOW)


def test_failed_bundle_falls_back_to_the_sequential_reads(monkeypatch):
    raw = towbook_cascade_raw()
    monkeypatch.setattr(rb, 'sf_composite_query', lambda named: {'wo': {'status': 400, 'body': [{'errorCode': 'X'}]}})

    def single(soql):
        if 'FROM WorkOrder' in soql:
            return [raw['wo']]
        if 'FROM ServiceAppointment WHERE' in soql:
            return raw['sas']
        if 'ServiceAppointmentHistory' in soql:
            return raw['history']
        return raw['sms'] if 'SMS_Send_Log__c' in soql else []
    monkeypatch.setattr(rb, 'sf_query_all', single)
    monkeypatch.setattr('cache.get', lambda key: None)
    monkeypatch.setattr('cache.put', lambda *a, **k: None)
    out = cp.pull_story('05164342', CFG, now=NOW)
    assert out['history'] == raw['history'] and out['sf_calls'] == 8        # 1 refused bundle + 7 single reads


def test_story_before_the_sms_log_still_reads_messaging_sessions(monkeypatch):
    raw = towbook_cascade_raw()
    raw['wo']['CreatedDate'] = '2026-08-20T10:00:00.000+0000'
    _bundle(monkeypatch, raw)
    asked = []
    monkeypatch.setattr(cp, '_texts', lambda p, r, wo, cfg: asked.append(wo['Id']) or r.update(sms=[], sms_source='messaging_session'))
    out = cp.pull_story('05164342', CFG, now=NOW)
    assert asked and out['sms_source'] == 'messaging_session'


@pytest.mark.parametrize('kind, value, want', [
    ('sa', 'SA-1', "Id IN (SELECT ERS_Work_Order__c FROM ServiceAppointment WHERE AppointmentNumber = 'SA-1')"),
    ('id', '0WOx', "Id = '0WOx'"),
    ('id', '08px', "Id IN (SELECT ERS_Work_Order__c FROM ServiceAppointment WHERE Id = '08px')"),
    ('id', '1WLx', "Id IN (SELECT WorkOrderId FROM WorkOrderLineItem WHERE Id = '1WLx')"),
    ('call_key', 'k', "ERS_Call_Key__c = 'k'"),
    ('wo', '0123', "(WorkOrderNumber = '0123' OR ERS_Source_Call_ID__c = '0123')"),
    ('source_call_id', '15', "ERS_Source_Call_ID__c = '15'"),
])
def test_resolve_filter_per_input_type(kind, value, want):
    assert cp._resolve_where(kind, value) == want
