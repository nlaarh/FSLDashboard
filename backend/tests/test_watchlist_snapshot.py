"""Watchlist rebuild: one combined Salesforce read, alerts built in Python, last copy served while ONE rebuild refreshes it."""
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from routers import watchlist as wl
from routers import watchlist_alerts as wa
from routers import watchlist_snapshot as snapmod

NOW = datetime(2026, 10, 9, 15, 0, 0, tzinfo=timezone.utc)


def iso(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).strftime('%Y-%m-%dT%H:%M:%S.000+0000')


def sa_row(n, *, status='Dispatched', cat='Dispatched', account='001A', territory='0HhT1', woli=None, wo=None,
           work_type='Tow', lat=43.0, lon=-77.0, street='1 Main St', ars=(), hist=(), created=40, pta=None,
           facility='Facility', prio=''):
    row = {
        'Id': f'08pS{n}', 'AppointmentNumber': f'SA-{n}', 'Status': status, 'StatusCategory': cat,
        'ServiceTerritoryId': territory, 'ServiceTerritory': {'Name': 'Terr - A'},
        'WorkType': {'Name': work_type}, 'WorkTypeId': 'wt1', 'ERS_PTA__c': pta,
        'ParentRecordId': woli, 'WO_Priority_Code__c': prio,
        'AAA_ERS_Account_Facility__r': {'Name': facility, 'Phone': '555'},
        'AccountId': account, 'Account': {'Name': 'Member', 'Phone': '1'},
        'CreatedDate': iso(created), 'LastModifiedDate': iso(1), 'ActualEndTime': None,
        'Street': street, 'City': 'Rochester', 'Latitude': lat, 'Longitude': lon,
        'ServiceResources': {'done': True, 'records': list(ars)} if ars else None,
        'Histories': {'done': True, 'records': list(hist)} if hist else None,
        'ParentRecord': {'attributes': {'type': 'WorkOrderLineItem'}, 'WorkOrderId': wo['Id'], 'WorkOrder': wo} if wo else None,
    }
    return row


def work_order(n, **kw):
    return {'Id': f'0WO{n}', 'WorkOrderNumber': f'WO-{n}', 'Current_Wait__c': 12.0, 'Vehicle_Make__c': 'Ford',
            'Vehicle_Model__c': 'F150', 'License_Plate__c': 'ABC1', 'Type__c': None, 'Customer_Name__c': None,
            'ERS_Unable_To_Complete_Dupe__c': False, 'CreatedDate': iso(60), **kw}


def snapshot(rows, no_sa=()):
    sas, ar, hist, wo_by_woli, trunc = snapmod.split_rows(rows)
    assert not trunc
    return {'now': NOW, 'sas': sas, 'ar_by_sa': ar, 'hist_by_sa': hist, 'wo_by_woli': wo_by_woli,
            'dup_candidates': snapmod.duplicate_candidates(sas, wo_by_woli, NOW), 'no_sa_wos': list(no_sa)}


@pytest.fixture(autouse=True)
def no_salesforce(monkeypatch):
    def boom(*a, **k):
        raise AssertionError('unexpected Salesforce read')
    monkeypatch.setattr(wa, 'sf_query_all', boom)
    monkeypatch.setattr(wa, 'batch_soql_parallel', boom)
    monkeypatch.setattr(snapmod, 'sf_query_all', boom)
    monkeypatch.setattr(snapmod, 'batch_soql_parallel', boom)


# ── split_rows ───────────────────────────────────────────────────────────────

def test_split_rows_gives_plain_sa_rows_and_indexes_children_and_work_order():
    wo = work_order(1)
    ar = {'Id': 'ar1', 'ServiceResource': {'Name': 'Drv'}}
    h = {'Field': 'Status', 'NewValue': 'Dispatched', 'CreatedDate': iso(5)}
    rows = [sa_row(1, woli='0Wl1', wo=wo, ars=[ar], hist=[h]), sa_row(2)]
    sas, ar_by_sa, hist_by_sa, wo_by_woli, trunc = snapmod.split_rows(rows)
    assert [s['Id'] for s in sas] == ['08pS1', '08pS2']
    assert not ({'ServiceResources', 'Histories', 'ParentRecord'} & set(sas[0]))
    assert ar_by_sa == {'08pS1': [ar], '08pS2': []}
    assert hist_by_sa == {'08pS1': [h], '08pS2': []}
    assert wo_by_woli == {'0Wl1': {'wo_id': '0WO1', 'wo': wo}}
    assert trunc == set()


def test_split_rows_flags_cut_off_child_lists():
    row = sa_row(1, ars=[{'Id': 'a'}])
    row['ServiceResources']['done'] = False
    assert snapmod.split_rows([row])[4] == {'08pS1'}


# ── duplicate candidates keep the old query's rules ──────────────────────────

def test_duplicate_candidates_rules():
    ok = sa_row(1, woli='W1', wo=work_order(1))
    drop_off = sa_row(2, work_type='Tow Drop-Off')
    done = sa_row(3, status='Completed', cat='Completed')
    flagged = sa_row(4, woli='W4', wo=work_order(4, ERS_Unable_To_Complete_Dupe__c=True))
    flagged_old_wo = sa_row(5, woli='W5', wo=work_order(5, ERS_Unable_To_Complete_Dupe__c=True, CreatedDate=iso(60 * 30)))
    no_parent = sa_row(6)
    sas, _, _, wo_by_woli, _ = snapmod.split_rows([ok, drop_off, done, flagged, flagged_old_wo, no_parent])
    ids = [c['Id'] for c in snapmod.duplicate_candidates(sas, wo_by_woli, NOW)]
    # the flag only counts for work orders created in the last 24 h, like the old NOT IN sub-query
    assert ids == ['08pS1', '08pS5', '08pS6']
    cand = snapmod.duplicate_candidates(sas, wo_by_woli, NOW)[0]
    assert set(cand) == {'Id', 'AccountId', 'AppointmentNumber', 'Latitude', 'Longitude', 'Street', 'ParentRecordId'}


# ── assemble: alerts from a snapshot, no Salesforce ──────────────────────────

def test_assemble_builds_alerts_with_work_order_and_duplicates_and_scopes_by_territory(monkeypatch):
    monkeypatch.setattr(wa, 'fetch_kmi_cases', lambda ids: {'0WO1': {'case_number': 'C1', 'case_id': 'c', 'case_status': 'New'}})
    rows = [
        sa_row(1, status='Received', cat='None', woli='W1', wo=work_order(1), territory='T-IN'),
        sa_row(2, account='001B', territory='T-IN', woli='W2', wo=work_order(2)),
        sa_row(3, account='001B', territory='T-OUT', woli='W3', wo=work_order(3)),   # same member, same spot, other territory
    ]
    snap = snapshot(rows)
    everyone = wl.assemble(snap, None)
    flags = {a['sa_id']: a for a in everyone['operational_alerts']}
    a1 = flags['08pS1']
    assert (a1['flag'], a1['wo_number'], a1['wo_id'], a1['vehicle'], a1['kmi_case_number']) == \
        ('Call Not Assigned - Received', 'WO-1', '0WO1', 'Ford F150', 'C1')
    assert flags['08pS2']['flag'] == 'Potential Duplicate' and flags['08pS2']['duplicate_of'] == ['SA-3']
    assert '08pS3' in flags

    scoped = wl.assemble(snap, ['T-IN'])           # contractor: only own territory, same duplicates, still no Salesforce read
    assert {a['sa_id'] for a in scoped['operational_alerts']} == {'08pS1', '08pS2'}
    assert next(a for a in scoped['operational_alerts'] if a['sa_id'] == '08pS2')['duplicate_of'] == ['SA-3']
    assert scoped['last_updated'] == NOW.isoformat()


def test_assemble_no_appointments_returns_only_work_order_alerts():
    wo = {'Id': '0WOx', 'WorkOrderNumber': 'WO-9', 'CreatedDate': iso(30), 'LastModifiedDate': iso(30),
          'ServiceTerritoryId': 'T-IN', 'ServiceTerritory': {'Name': 'T'}}
    snap = snapshot([], no_sa=[(wo, NOW - timedelta(minutes=10))])
    snap['kmi_map'] = {}
    out = wl.assemble(snap, None)
    assert out['watchlist'] == [] and [a['flag'] for a in out['operational_alerts']] == [wa.NO_SA_FLAG]
    assert wl.assemble(snap, ['T-OTHER'])['operational_alerts'] == []
    young = snapshot([], no_sa=[(wo, NOW - timedelta(seconds=30))])     # inside the 2 minute grace period
    assert wl.assemble(young, None)['operational_alerts'] == []


# ── no-appointment work orders: few requests ─────────────────────────────────

def test_find_no_sa_wos_needs_two_requests_when_nothing_is_unresolved(monkeypatch):
    reads = []
    rows = [
        {'Id': 'A', 'Service_Appointments_del__r': {'records': [{'Id': 's'}]}},      # has an SA through ERS_Work_Order__c
        {'Id': 'B', 'Service_Appointments_del__r': None},                             # SA found via the main pull
    ]
    monkeypatch.setattr(wa, 'sf_query_all', lambda q: reads.append(q) or rows)
    assert wa.find_no_sa_wos(NOW, {'B'}) == []
    assert len(reads) == 1


def test_find_no_sa_wos_checks_only_unresolved_work_orders(monkeypatch):
    calls = []
    rows = [{'Id': 'C', 'LastModifiedDate': iso(9), 'Service_Appointments_del__r': None},
            {'Id': 'D', 'LastModifiedDate': iso(9), 'Service_Appointments_del__r': None}]
    monkeypatch.setattr(wa, 'sf_query_all', lambda q: rows)

    def fake_batch(template, ids, chunk_size=200):
        calls.append((template.split('FROM')[1].split()[0], list(ids)))
        if 'FROM WorkOrderLineItem' in template:
            return [{'Id': 'L1', 'WorkOrderId': 'D'}]
        if 'FROM ServiceAppointment' in template:
            return [{'ParentRecordId': 'L1'}]                                         # D does have an SA after all
        return [{'WorkOrderId': 'C', 'NewValue': 'Submitted', 'CreatedDate': iso(5)}]
    monkeypatch.setattr(wa, 'batch_soql_parallel', fake_batch)
    found = wa.find_no_sa_wos(NOW, set())
    assert [w['Id'] for w, _ in found] == ['C']
    assert found[0][1] == wa._parse_dt(iso(5))
    assert calls[-1] == ('WorkOrderHistory', ['C'])                                   # history only for the survivor


# ── serving: instant copy, one background rebuild ────────────────────────────

@pytest.fixture
def served(monkeypatch):
    """Replace the Salesforce read with a counter and reset the copy."""
    state = {'builds': 0, 'gate': None}

    def fake_fetch(now_utc=None):
        state['builds'] += 1
        if state['gate']:
            state['gate'].wait(5)
        return {**snapshot([sa_row(1, status='Received', cat='None')]), 'now': datetime.now(timezone.utc), 'kmi_map': {}}
    monkeypatch.setattr(wl, 'fetch_snapshot', fake_fetch)
    monkeypatch.setattr(wl.cache, 'disk_put', lambda *a, **k: None)
    monkeypatch.setattr(wl.cache, 'disk_get_stale', lambda k: None)
    monkeypatch.setattr(wl.cache, 'fs_lock_acquire', lambda *a, **k: True)
    monkeypatch.setattr(wl.cache, 'fs_lock_release', lambda *a, **k: None)
    monkeypatch.setattr(wl, '_state', {'snap': None, 'result': None, 'built': 0.0})
    state['wait_bg'] = lambda: [t.join(5) for t in threading.enumerate() if t.name == 'watchlist-rebuild']
    return state


def test_first_request_builds_then_fresh_copy_is_served_without_reading(served):
    first = wl.watchlist_for([])
    assert served['builds'] == 1 and first['operational_alerts']
    assert wl.watchlist_for([]) is first
    assert served['builds'] == 1


def test_stale_copy_is_served_at_once_and_refreshed_by_exactly_one_rebuild(served):
    old = wl.watchlist_for([])
    wl._state['built'] -= 45                       # 45 s old: past fresh (30 s), inside max staleness (60 s)
    served['gate'] = threading.Event()             # hold the background rebuild open
    for _ in range(5):                             # five dispatchers poll while it runs
        assert wl.watchlist_for([]) is old         # instant, from the last copy
    time.sleep(0.2)
    assert served['builds'] == 2                   # the first build + ONE rebuild, not five
    served['gate'].set()
    served['wait_bg']()
    assert wl._state['result'] is not old          # refreshed
    assert wl.watchlist_for([]) is wl._state['result']


def test_copy_older_than_max_staleness_waits_for_a_rebuild(served):
    old = wl.watchlist_for([])
    wl._state['built'] -= 120
    old['last_updated'] = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    new = wl.watchlist_for([])
    assert new is not old and served['builds'] == 2


def test_failed_rebuild_serves_the_last_copy_with_its_true_age(served, monkeypatch):
    old = wl.watchlist_for([])
    wl._state['built'] -= 120
    monkeypatch.setattr(wl, 'fetch_snapshot', lambda now_utc=None: (_ for _ in ()).throw(RuntimeError('SF down')))
    assert wl.watchlist_for([]) is old             # still the old copy; its last_updated is unchanged
    wl._state.update(snap=None, result=None, built=0.0)
    wl.cache._store.pop(wl.CACHE_KEY, None)                  # and with no copy at all: an error body, not a crash
    out = wl.watchlist_for([])
    assert out['watchlist'] == [] and out['error']


def test_contractor_is_served_from_the_shared_snapshot(served):
    wl.watchlist_for([])
    served_builds = served['builds']
    out = wl.watchlist_for(['0HhT1'])
    assert served['builds'] == served_builds       # no extra read for a contractor
    assert {a['territory_id'] for a in out['operational_alerts']} <= {'0HhT1'}


def test_last_updated_is_when_salesforce_was_read(served):
    out = wl.watchlist_for([])
    assert 0 <= wl._age_of(out['last_updated']) < 5
