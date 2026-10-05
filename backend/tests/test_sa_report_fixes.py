"""SA report fixes (call-story architecture section 6, bugs 1, 3, 4, 5). Fake Salesforce rows, no network."""

import pytest

from dispatch_utils import _STATUS_LABEL
from routers import sa_report
from routers.sa_report_timeline import _build_phases, _build_sa_summary, _build_timeline, _garage_type

SA_ID = '08pFAKE00000001AAA'


def _sa(**over):
    sa = {'Id': SA_ID, 'AppointmentNumber': 'SA-0000001', 'Status': 'Completed',
          'CreatedDate': '2026-09-24T14:35:49.000+0000', 'ActualStartTime': None, 'ActualEndTime': None,
          'WorkType': {'Name': 'Tow Pick-Up'}, 'ServiceTerritoryId': '0HhFAKE00000001AAA',
          'ServiceTerritory': {'Name': '076DO - TRANSIT AUTO DETAIL'}, 'ERS_PTA__c': 120,
          'ERS_Dispatch_Method__c': 'Field Services', 'ParentRecordId': None}
    sa.update(over)
    return sa


def _h(field, ts, new, old=None, actor='Integrations Towbook', profile='Towbook Integrations'):
    return {'ServiceAppointmentId': SA_ID, 'Field': field, 'OldValue': old, 'NewValue': new,
            'CreatedDate': f'2026-09-24T{ts}.000+0000', 'CreatedBy': {'Name': actor, 'Profile': {'Name': profile}}}


def test_bug3_accepted_is_its_own_status():
    assert _STATUS_LABEL['Accepted'] == 'Accepted'
    tl = _build_timeline([_h('Status', '15:58:07', 'Accepted'), _h('Status', '16:13:36', 'En Route')], SA_ID)
    assert [e['event'] for e in tl] == ['Accepted', 'En Route']
    phases = _build_phases(tl + [{'event': 'On Location', 'ts': None}], {})
    assert phases[0]['label'] == 'Accepted, not rolling' and phases[0]['minutes'] == pytest.approx(15.5, abs=0.1)


@pytest.mark.parametrize('channel, territory, expected', [
    ('towbook', '076DO - TRANSIT AUTO DETAIL', 'Towbook'),
    ('fleet', '100 - WESTERN NEW YORK FLEET', 'Fleet'),
    ('on_platform_contractor', '642 - AUTO WRENCH', 'On-Platform Contractor'),
    (None, '100 - WESTERN NEW YORK FLEET', 'Fleet'),
])
def test_bug5_garage_type_comes_from_the_driver_type_not_the_formula(channel, territory, expected):
    assert _garage_type(territory, channel) == expected


def test_bug4_towbook_response_uses_history_on_location(monkeypatch):
    monkeypatch.setattr('routers.sa_report_timeline._sf_record_url', lambda rid: None)
    s = _build_sa_summary(_sa(ActualStartTime='2026-09-25T04:00:00.000+0000'), channel='towbook',
                          on_location='2026-09-24T16:20:44.000+0000')
    assert (s['response_min'], s['arrival_source'], s['garage_type']) == (105, 'history', 'Towbook')
    fleet = _build_sa_summary(_sa(ActualStartTime='2026-09-24T15:15:49.000+0000'), channel='fleet',
                              on_location='2026-09-24T16:20:44.000+0000')
    assert (fleet['response_min'], fleet['arrival_source']) == (40, 'actual_start')


def test_bug5_channel_from_ar_or_last_assigned_name():
    ar = {'ServiceResource': {'ERS_Driver_Type__c': 'Off-Platform Contractor Driver'}}
    assert sa_report._sa_channel(ar, []) == 'towbook'
    assert sa_report._sa_channel({'ServiceResource': {'ERS_Driver_Type__c': 'Fleet Driver'}}, []) == 'fleet'
    rows = [_h('ERS_Assigned_Resource__c', '15:58:07', 'Towbook-076DO')]
    assert sa_report._sa_channel(None, rows) == 'towbook'
    assert sa_report._sa_channel(None, []) is None


def test_report_end_to_end_towbook_call(monkeypatch):
    """Formula says Field Services (the facility's current method); the driver type says Towbook. Bug 1: the history
    query now selects OldValue, so the creation row is the only row with OldValue null (the real origin)."""
    queries = []
    hist = [
        _h('ServiceTerritory', '14:35:49', '0HhFAKE00000001AAA', actor='Mulesoft Integration', profile='X'),
        _h('ServiceTerritory', '14:36:22', '0HhFAKE00000002AAA', old='0HhFAKE00000001AAA'),
        _h('ERS_Assigned_Resource__c', '15:58:00', 'Towbook-076DO', actor='Domingo', profile='Membership User'),
        _h('Status', '15:58:07', 'Accepted'),
        _h('Status', '16:13:36', 'En Route'),
        _h('Status', '16:20:44', 'On Location'),
        _h('Status', '16:32:36', 'Completed'),
    ]

    def fake_query_all(soql):
        queries.append(soql)
        return [_sa()] if 'FROM ServiceAppointment\n' in soql else []

    def fake_parallel(**fns):
        if 'hist' in fns:
            fns['hist']()
            return {'hist': hist, 'ar': [{'ServiceResourceId': 'x', 'ServiceResource': {
                'Name': 'Towbook-076DO', 'ERS_Driver_Type__c': 'Off-Platform Contractor Driver'}}], 'woli_wo': []}
        return {k: [] for k in fns}
    monkeypatch.setattr(sa_report, 'sf_query_all', fake_query_all)
    monkeypatch.setattr(sa_report, 'sf_parallel', fake_parallel)
    monkeypatch.setattr('routers.sa_report_timeline._sf_record_url', lambda rid: None)
    monkeypatch.setattr(sa_report.cache, 'cached_query', lambda key, fn, ttl=0: fn())
    r = sa_report.sa_report('SA-0000001')
    hist_soql = next(q for q in queries if 'ServiceAppointmentHistory' in q)
    assert 'OldValue, NewValue' in hist_soql and 'ORDER BY CreatedDate ASC, Id ASC' in hist_soql
    assert r['is_towbook'] is True and r['sa_summary']['garage_type'] == 'Towbook'
    assert r['sa_summary']['response_min'] == 105 and r['sa_summary']['arrival_source'] == 'history'
    assert 'Accepted' in [e['event'] for e in r['timeline']]
