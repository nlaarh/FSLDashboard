"""Shared dashboard reads (ref_data): one Salesforce read for many screens, each screen filtering like its own query did."""
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

import ref_data

NOW = datetime(2026, 10, 9, 15, 0, 0, tzinfo=timezone.utc)


def ts(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).strftime('%Y-%m-%dT%H:%M:%S.000+0000')


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    ref_data.reset()
    reads = []
    tables = {}

    def fake_query_all(soql):
        name = next(t for t in ('FROM Asset', 'FROM ServiceResource', 'FROM ServiceTerritoryMember',
                                'FROM ServiceAppointment', 'FROM AssignedResource') if t in soql)
        reads.append(name)
        if tables.get('error'):
            raise RuntimeError('SF down')
        return list(tables.get(name, []))

    monkeypatch.setattr(ref_data.sf_client, 'sf_query_all', fake_query_all)
    return {'reads': reads, 'tables': tables}


def test_trucks_active_filter_matches_the_old_where_clause(fresh):
    fresh['tables']['FROM Asset'] = [
        {'ERS_Driver__c': 'a', 'ERS_Driver__r': {'IsActive': True}},
        {'ERS_Driver__c': 'b', 'ERS_Driver__r': {'IsActive': False}},
        {'ERS_Driver__c': 'c', 'ERS_Driver__r': None},
    ]
    assert [t['ERS_Driver__c'] for t in ref_data.trucks()] == ['a']
    assert [t['ERS_Driver__c'] for t in ref_data.trucks(active_only=False)] == ['a', 'b', 'c']   # map / Scheduler Insights
    assert fresh['reads'] == ['FROM Asset']                                                         # one read served both


def test_drivers_gps_and_name_rules_match_the_old_queries(fresh):
    names = ['Ann 1', 'Towbook Joe', 'test user', '000-Spare', '0 Spare', '100A Truck', 'Big SPOT Van', 'travel user', 'Zed']
    fresh['tables']['FROM ServiceResource'] = (
        [{'Id': n, 'Name': n, 'LastKnownLatitude': 43.0} for n in names]
        + [{'Id': 'nogps', 'Name': 'No Gps', 'LastKnownLatitude': None}])
    everyone = {d['Name'] for d in ref_data.drivers()}
    assert 'No Gps' not in everyone and len(everyone) == len(names)                   # driver map / Ops Brief
    insights = {d['Name'] for d in ref_data.drivers(exclude_names=('Towbook%', 'Test %', '000-%', '0 %', '100A %'),
                                                    exclude_exact=('Travel User',))}
    assert insights == {'Ann 1', 'Big SPOT Van', 'Zed'}                               # Scheduler Insights
    command_center = {d['Name'] for d in ref_data.drivers(require_gps=False,
                                                          exclude_names=('Test %', '000-%', '0 %', '100A %', '%SPOT%'),
                                                          exclude_exact=('Travel User',))}
    assert command_center == {'Ann 1', 'Towbook Joe', 'No Gps', 'Zed'}                # Command Center (keeps no-GPS and Towbook)
    assert fresh['reads'] == ['FROM ServiceResource']


def test_like_is_case_insensitive_with_wildcards():
    assert ref_data.like('Test Driver', 'Test %') and ref_data.like('TEST x', 'test %')
    assert ref_data.like('a SPOT b', '%SPOT%') and not ref_data.like('Testing', 'Test %')
    assert ref_data.like('ab', 'a_') and not ref_data.like('abc', 'a_')
    assert not ref_data.like('a.c', 'abc') and ref_data.like('a.c', 'a.c')              # regex characters are literal


def _sa(i, hours_ago, status='Completed', rt='ERS Service Appointment'):
    return {'Id': f'sa{i}', 'Status': status, 'CreatedDate': ts(hours_ago), 'RecordType': {'Name': rt}}


def test_appointments_each_screen_cuts_its_own_window(fresh):
    fresh['tables']['FROM ServiceAppointment'] = [
        _sa(1, 20), _sa(2, 3), _sa(3, 1, status='En Route'), _sa(4, 1, rt='Lobby Service Appointment'),
    ]
    assert [s['Id'] for s in ref_data.appointments(NOW - timedelta(hours=24))] == ['sa1', 'sa2', 'sa3']
    assert [s['Id'] for s in ref_data.appointments(NOW - timedelta(hours=4))] == ['sa2', 'sa3']        # Command Center 4 h
    assert [s['Id'] for s in ref_data.appointments(NOW - timedelta(hours=24), statuses=('Completed',))] == ['sa1', 'sa2']
    assert [s['Id'] for s in ref_data.appointments(NOW - timedelta(hours=4), ers_only=False)] == ['sa2', 'sa3', 'sa4']  # PTA: any record type
    assert fresh['reads'] == ['FROM ServiceAppointment']


def test_assigned_filters_by_appointment_fields(fresh):
    def ar(i, hours_ago, status, method='Field Services', rt='ERS Service Appointment'):
        return {'ServiceAppointmentId': f'sa{i}', 'ServiceAppointment': {
            'Status': status, 'CreatedDate': ts(hours_ago), 'RecordType': {'Name': rt}, 'ERS_Dispatch_Method__c': method}}
    fresh['tables']['FROM AssignedResource'] = [
        ar(1, 2, 'Completed'), ar(2, 2, 'Dispatched', method='Towbook'), ar(3, 30, 'Completed'), ar(4, 2, 'Completed', rt='Counter Service')]
    since = NOW - timedelta(hours=6)
    assert [r['ServiceAppointmentId'] for r in ref_data.assigned(since, sa_statuses=('Completed',),
                                                                  dispatch_method='field services')] == ['sa1', 'sa4']
    assert [r['ServiceAppointmentId'] for r in ref_data.assigned(since, ers_only=True)] == ['sa1', 'sa2']
    assert [r['ServiceAppointmentId'] for r in ref_data.assigned(since, sa_statuses=('Dispatched',))] == ['sa2']


def test_reads_are_shared_until_the_copy_expires(fresh, monkeypatch):
    fresh['tables']['FROM Asset'] = [{'ERS_Driver__c': 'a', 'ERS_Driver__r': {'IsActive': True}}]
    for _ in range(5):
        ref_data.trucks()
    assert fresh['reads'].count('FROM Asset') == 1
    ref_data._entries['trucks']['at'] -= ref_data.TTL_REFERENCE + 1
    ref_data.trucks()
    assert fresh['reads'].count('FROM Asset') == 2


def test_callers_get_private_copies(fresh):
    fresh['tables']['FROM Asset'] = [{'ERS_Driver__c': 'a', 'ERS_Driver__r': {'IsActive': True}}]
    ref_data.trucks()[0]['ERS_Driver__c'] = 'mutated'
    assert ref_data.trucks()[0]['ERS_Driver__c'] == 'a'


def test_concurrent_callers_make_one_read(fresh, monkeypatch):
    gate = threading.Event()
    real = ref_data.sf_client.sf_query_all

    def slow(soql):
        gate.wait(2)
        return real(soql)
    monkeypatch.setattr(ref_data.sf_client, 'sf_query_all', slow)
    fresh['tables']['FROM ServiceTerritoryMember'] = [{'ServiceResourceId': 'r', 'ServiceTerritoryId': 't'}]
    out = []
    threads = [threading.Thread(target=lambda: out.append(ref_data.members())) for _ in range(6)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    gate.set()
    for t in threads:
        t.join(3)
    assert len(out) == 6 and fresh['reads'].count('FROM ServiceTerritoryMember') == 1


def test_failed_read_serves_the_previous_copy_and_is_not_remembered(fresh):
    fresh['tables']['FROM Asset'] = [{'ERS_Driver__c': 'a', 'ERS_Driver__r': {'IsActive': True}}]
    ref_data.trucks()
    ref_data._entries['trucks']['at'] -= ref_data.TTL_REFERENCE + 1
    fresh['tables']['error'] = True
    assert [t['ERS_Driver__c'] for t in ref_data.trucks()] == ['a']          # Salesforce down: last good copy
    assert ref_data.stats['stale_served'] == 1
    ref_data.reset()
    with pytest.raises(RuntimeError):                                          # nothing to fall back on: the error surfaces
        ref_data.trucks()
    fresh['tables']['error'] = False
    fresh['tables']['FROM Asset'] = []
    assert ref_data.trucks() == []                                             # and the failure was not cached


def test_hourly_baseline_is_cached_per_weekday(fresh, monkeypatch):
    seen = []
    monkeypatch.setattr(ref_data.sf_client, 'sf_query_all', lambda soql: seen.append(soql) or [{'hr': 14, 'cnt': 80}])
    assert ref_data.hourly_baseline(6, NOW) == [{'hr': 14, 'cnt': 80}]
    ref_data.hourly_baseline(6, NOW)
    ref_data.hourly_baseline(2, NOW)
    assert len(seen) == 2 and 'DAY_IN_WEEK(CreatedDate) = 6' in seen[0]
