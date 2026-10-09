"""Two queries that used to fail silently and return nothing (F10)."""

from routers import accounting_audit, contractor_recommendations as cr


def test_same_day_lookup_sends_the_query_and_returns_the_members_other_calls(monkeypatch):
    seen = []

    def fake_all(soql):          # the real sf_query_all has no max_records: a TypeError here used to be swallowed
        seen.append(soql)
        return [
            {'WorkOrderNumber': '111', 'Status': 'Completed', 'Trouble_Code__c': 'TC1', 'CreatedDate': 'd',
             'ServiceTerritory': {'Name': 'Garage A'}},
            {'WorkOrderNumber': 'THIS', 'Status': 'Completed'},          # the audited work order itself is dropped
        ]

    monkeypatch.setattr(accounting_audit, 'sf_query_all', fake_all)
    out = accounting_audit._same_day_calls('001ACC', '2026-10-08', '0WOID', 'THIS')

    assert len(seen) == 1 and "AccountId = '001ACC'" in seen[0] and "Id != '0WOID'" in seen[0]
    assert out == [{'wo_number': '111', 'status': 'Completed', 'trouble_code': 'TC1', 'created_date': 'd',
                    'territory': 'Garage A'}]


def test_same_day_lookup_failure_is_logged_not_swallowed_silently(monkeypatch, caplog):
    def boom(soql):
        raise RuntimeError('SF down')

    monkeypatch.setattr(accounting_audit, 'sf_query_all', boom)
    with caplog.at_level('WARNING', logger='accounting'):
        assert accounting_audit._same_day_calls('001ACC', '2026-10-08', '0WOID', 'THIS') == []
    assert 'Same-day work orders lookup failed' in caplog.text


def test_er_miles_history_query_does_not_filter_on_new_value(monkeypatch):
    seen = []
    rows = [
        {'ServiceAppointmentId': 'a', 'NewValue': 'Dispatched', 'CreatedDate': '1'},
        {'ServiceAppointmentId': 'a', 'NewValue': 'En Route', 'CreatedDate': '2'},
        {'ServiceAppointmentId': 'a', 'NewValue': 'On Location', 'CreatedDate': '3'},
        {'ServiceAppointmentId': 'a', 'NewValue': 'Completed', 'CreatedDate': '4'},
    ]
    monkeypatch.setattr(cr, 'sf_query_all', lambda soql: seen.append(soql) or rows)

    out = cr._status_history_for_wos(['0WO1', '0WO2'])

    assert 'NewValue IN' not in seen[0]            # Salesforce: "field 'NewValue' can not be filtered in a query call"
    assert "Field = 'Status'" in seen[0] and 'LIMIT 50000' in seen[0]
    assert [r['NewValue'] for r in out] == ['En Route', 'On Location']
