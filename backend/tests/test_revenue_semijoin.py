"""Speed batch 3, item 3: garage revenue with the AssetHistory semi-join and the work-order fields folded into the line-item
read (flag revenue_semijoin). Flag off must send exactly the old fan-out; flag on must give the identical result in fewer reads.
Fake Salesforce only."""

import json
import re

import pytest

from routers import garages_revenue as gr
from tests.speed3_fixtures import flags

TERR = '0Hh000000000001AAA'
TRUCKS = [f'02i{n:015d}' for n in range(450)]                       # 3 chunks of 200 on the old path


def fake_salesforce(monkeypatch, log):
    n_sa = 30
    ars = [{'ServiceAppointmentId': f'08p{i:015d}', 'ServiceResource': {'Name': f'Driver {i % 4} 076DO'},
            'ServiceAppointment': {'ParentRecordId': f'1WL{i:015d}', 'CreatedDate': f'2026-10-0{1 + i % 5}T1{i % 10}:00:00.000+0000',
                                   'WorkType': {'Name': ['Tow', 'Battery', 'Tow Drop-Off', 'Light Service'][i % 4]}}} for i in range(n_sa)]
    wolis = {f'1WL{i:015d}': {'Id': f'1WL{i:015d}', 'WorkOrderId': f'0WO{i // 2:015d}'} for i in range(n_sa)}     # two line items per work order
    wos = {f'0WO{k:015d}': {'Id': f'0WO{k:015d}', 'WorkOrderNumber': f'0519{k:04d}' if k % 5 else None,
                            'Est_Tow_Over_Mileage_Cost_to_Member1__c': 12.5 * (k % 3)} for k in range(n_sa // 2 + 1)}
    billing = [{'WorkOrderId': f'0WO{k:015d}', 'PricebookEntryId': '01u0', 'Basic_Cost__c': 40.0 + k, 'Plus_Cost__c': 3.0,
                'Premier_Cost__c': None, 'RV_Cost__c': None, 'Other_Cost__c': 1.5} for k in range(n_sa // 2 + 1)]
    history = []
    for t in range(0, 450, 37):
        history.append({'AssetId': TRUCKS[t], 'OldValue': None, 'NewValue': f'Driver {t % 4} 076DO', 'CreatedDate': '2026-10-02T08:00:00.000+0000'})
        history.append({'AssetId': TRUCKS[t], 'OldValue': f'Driver {t % 4} 076DO', 'NewValue': None, 'CreatedDate': '2026-10-02T15:30:00.000+0000'})

    def ids_in(soql):
        return re.findall(r"'([0-9A-Za-z]{15,18})'", soql.split(' IN (', 1)[1].split(')')[0]) if ' IN (' in soql else []

    def sf_query_all(soql, timeout=None):
        log.append(soql)
        if 'FROM AssignedResource' in soql:
            return json.loads(json.dumps(ars))
        if 'FROM WorkOrderLineItem WHERE Id IN' in soql:
            out = []
            for i in ids_in(soql):
                row = dict(wolis[i])
                if 'WorkOrder.WorkOrderNumber' in soql:
                    wo = wos[row['WorkOrderId']]
                    row['WorkOrder'] = {'WorkOrderNumber': wo['WorkOrderNumber'], 'Est_Tow_Over_Mileage_Cost_to_Member1__c': wo['Est_Tow_Over_Mileage_Cost_to_Member1__c']}
                out.append(row)
            return out
        if 'FROM WorkOrderLineItem' in soql and 'WorkOrderId IN' in soql:
            want = set(ids_in(soql))
            return [b for b in billing if b['WorkOrderId'] in want]
        if 'FROM WorkOrder WHERE' in soql:
            return [dict(wos[i]) for i in ids_in(soql)]
        if 'FROM AssetHistory' in soql:
            if 'FROM Asset WHERE' in soql:                                     # the semi-join: every truck
                return json.loads(json.dumps(history))
            want = set(ids_in(soql))
            return [h for h in history if h['AssetId'] in want]
        raise AssertionError(f'unexpected query: {soql[:80]}')

    monkeypatch.setattr(gr, 'sf_query_all', sf_query_all)
    monkeypatch.setattr(gr, '_get_trucks', lambda: list(TRUCKS))


def run(monkeypatch, on):
    log = []
    flags(monkeypatch, revenue_semijoin=on)
    fake_salesforce(monkeypatch, log)
    return gr._compute_revenue(TERR, '2026-10-01', '2026-10-07'), log


def daily(monkeypatch, on):
    log = []
    flags(monkeypatch, revenue_semijoin=on)
    fake_salesforce(monkeypatch, log)
    return gr._compute_driver_daily(TERR, 'Driver 1', '2026-10-01', '2026-10-07'), log


def kinds(log):
    return {'asset_history': sum('FROM AssetHistory' in q for q in log), 'work_order': sum('FROM WorkOrder WHERE' in q for q in log),
            'woli': sum('FROM WorkOrderLineItem' in q for q in log)}


def test_revenue_is_identical_with_the_flag_on_and_uses_fewer_reads(monkeypatch):
    old, old_log = run(monkeypatch, False)
    new, new_log = run(monkeypatch, True)
    assert old['drivers'] and old['summary']['total_attributed'] > 0 and any(d['hours'] for d in old['drivers'])
    assert any(d['member_wo_details'] for d in old['drivers'])
    assert new == old
    assert kinds(old_log)['asset_history'] == 3 and kinds(old_log)['work_order'] >= 1
    assert kinds(new_log)['asset_history'] == 1 and kinds(new_log)['work_order'] == 0
    assert 'IN (SELECT Id FROM Asset WHERE RecordType.Name = \'ERS Truck\')' in next(q for q in new_log if 'FROM AssetHistory' in q)
    assert len(new_log) < len(old_log)


def test_flag_off_sends_the_old_queries(monkeypatch):
    _, log = run(monkeypatch, False)
    assert not any('FROM Asset WHERE' in q or 'WorkOrder.WorkOrderNumber' in q for q in log)


def test_flag_on_does_not_need_the_cached_truck_list(monkeypatch):
    flags(monkeypatch, revenue_semijoin=True)
    log = []
    fake_salesforce(monkeypatch, log)
    monkeypatch.setattr(gr, '_get_trucks', lambda: pytest.fail('the semi-join does not use the cached truck list'))
    assert gr._compute_revenue(TERR, '2026-10-01', '2026-10-07')['drivers']


def test_driver_daily_drilldown_is_identical_too(monkeypatch):
    old, _ = daily(monkeypatch, False)
    new, new_log = daily(monkeypatch, True)
    assert old['days'] and any(d['hours'] for d in old['days'])
    assert new == old and kinds(new_log)['asset_history'] == 1
