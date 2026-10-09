"""Watchlist call map: lateness colours, who is working it, driver queues and qualification, cases as events, permissions, and the Salesforce cost."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import sf_client
import watchlist_call_map as w

NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)
ago = lambda m: (NOW - timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%M:%S.000+0000')


@pytest.mark.parametrize('late,level', [(None, 'ok'), (-20, 'ok'), (0, 'ok'), (1, 'yellow'), (30, 'yellow'), (30.5, 'orange'), (89, 'orange'), (90, 'red'), (300, 'red')])
def test_lateness_colours(late, level):
    assert w.lateness(late)['level'] == level


def _hist(profile, who, mins, field='Status', sa='SA1'):
    return {'ServiceAppointmentId': sa, 'Field': field, 'CreatedDate': ago(mins), 'CreatedBy': {'Name': who, 'Profile': {'Name': profile}}}


def test_working_now_is_the_latest_membership_user_only():
    hist = [_hist('Membership User', 'Jane Dee', 20), _hist('Membership User', 'Pat Lee', 4, 'ERS_Assigned_Resource__c'),
            _hist('Contact Center', 'Cc Agent', 1), _hist('System Administrator', 'Admin', 1), _hist('Integration', 'Mulesoft', 0),
            _hist('Membership User', 'Other Call', 2, sa='SA2')]
    got = w.working_now(hist, [], 'SA1', NOW)
    assert (got['name'], got['minutes_ago']) == ('Pat Lee', 4)


def test_working_now_counts_the_assigner_of_the_driver():
    ar = [{'CreatedDate': ago(3), 'CreatedBy': {'Name': 'Jane Dee', 'Profile': {'Name': 'membership user'}}}]
    got = w.working_now([_hist('Membership User', 'Pat Lee', 9)], ar, 'SA1', NOW)
    assert (got['name'], got['what']) == ('Jane Dee', 'assigned a driver')


def test_working_now_is_none_when_only_system_users_touched_it():
    ar = [{'CreatedDate': ago(3), 'CreatedBy': {'Name': 'Platform Integration User', 'Profile': {'Name': 'Integration'}}}]
    assert w.working_now([_hist('Contact Center', 'Cc', 2)], ar, 'SA1', NOW) is None
    assert w.working_now([], [], 'SA1', NOW) is None


def _job(sa, status, mins, wt='Tow'):
    return {'ServiceAppointment': {'AppointmentNumber': sa, 'Status': status, 'WorkType': {'Name': wt}, 'Latitude': 43.0, 'Longitude': -78.8}, 'CreatedDate': ago(mins)}


def _sr(i, name, lat, lon, skills=('Tow',), caps=('Flat Bed',), jobs=(), trucks=True, absent=False, gps=2):
    return {'Id': i, 'Name': name, 'LastKnownLatitude': lat, 'LastKnownLongitude': lon, 'LastKnownLocationDate': ago(gps),
            'RelatedRecord': {'Phone': '5855550100', 'MobilePhone': None},
            'ServiceResourceSkills': {'records': [{'Skill': {'MasterLabel': s}} for s in skills]},
            'Assets__r': {'records': [{'Name': f'T-{i}', 'ERS_Truck_Capabilities__c': ';'.join(caps)}] if trucks else []},
            'ResourceAbsences': {'records': [{'Id': 'x'}] if absent else []}, 'ServiceAppointments': {'records': list(jobs)}}


def test_driver_state_orders_the_queue_and_reads_the_status():
    status, q = w.driver_state([{'sa': 'B', 'status': 'Dispatched', 'work_type': 'Tow', 'given_at': ago(5)},
                                {'sa': 'A', 'status': 'En Route', 'work_type': 'Tow', 'given_at': ago(30)},
                                {'sa': 'ME', 'status': 'Dispatched', 'work_type': 'Tow', 'given_at': ago(1)}], 'ME')
    assert status == 'driving' and [j['sa'] for j in q] == ['A', 'B']
    assert w.driver_state([{'sa': 'D', 'status': 'On Location', 'work_type': 'Tow Drop-Off', 'given_at': ago(5)}])[0] == 'towing'
    assert w.driver_state([]) == ('free', [])


def test_qualified_is_skills_plus_truck_capabilities_case_insensitive():
    assert w.qualified({'Tow', 'Flat Bed'}, {'tow'}, {'FLAT BED'})
    assert not w.qualified({'Tow', 'Winch'}, {'Tow'}, {'Flat Bed'})
    assert w.qualified(set(), set(), set())


def test_peers_are_qualified_on_shift_fresh_and_sorted_by_distance():
    member = (43.0, -78.8)
    rows = [_sr('far', 'Far Driver', 43.3, -78.8), _sr('near', 'Near Driver', 43.01, -78.8),
            _sr('unq', 'Unqualified', 43.0, -78.8, skills=('Battery',), caps=()), _sr('out', 'No Truck', 43.0, -78.8, trucks=False),
            _sr('abs', 'Absent', 43.0, -78.8, absent=True), _sr('old', 'Stale GPS', 43.0, -78.8, gps=120),
            _sr('asg', 'Assigned Driver', 43.05, -78.8, jobs=[_job('SA-9', 'Dispatched', 40), _job('SA-1', 'Dispatched', 5)])]
    peers, mine, counts = w.build_drivers(rows, {'Tow'}, member, 'SA-1', 'asg', NOW)
    assert [p['name'] for p in peers] == ['Near Driver', 'Far Driver']
    assert counts == {'not_qualified': 1, 'no_gps': 1}
    assert mine['name'] == 'Assigned Driver' and mine['held'] == 1 and mine['truck'] == 'T-asg' and mine['phone'] == '5855550100'
    assert peers[0]['held'] == 0 and peers[0]['status'] == 'free'
    assert mine['status'] == 'waiting'                      # dispatched to this call but not started: never "free"
    _, mine2, _ = w.build_drivers(rows, {'Tow'}, member, 'SA-1', 'asg', NOW, 'En Route')
    assert mine2['status'] == 'driving'


def test_suggestion_only_when_a_free_qualified_driver_is_closer():
    free = {'name': 'Driver A', 'miles': 3.8, 'held': 0, 'status': 'free'}
    busy = {'name': 'B', 'miles': 1.0, 'held': 2, 'status': 'driving'}
    mine = {'name': 'Mike', 'miles': 9.0, 'held': 2}
    s = w.suggestion('Dispatched', mine, [busy, free])
    assert s['text'].startswith('Driver A is free, qualified and 3.8 mi away.') and '2 jobs ahead' in s['text']
    assert w.suggestion('Dispatched', {**mine, 'miles': 2.0}, [free]) is None
    assert w.suggestion('On Location', mine, [free]) is None
    assert w.suggestion('Dispatched', mine, [busy]) is None
    assert 'No driver has the call yet' in w.suggestion('Dispatched', None, [free])['text']


CASES = [{'Id': '500A', 'CaseNumber': '01037263', 'Status': 'Closed', 'Subject': 'Spot', 'Type': None, 'Reason': 'Late', 'RecordType': {'Name': 'ERS KMI Alerts'},
          'CreatedDate': ago(50), 'ClosedDate': ago(10), 'IsClosed': True, 'CreatedBy': {'Name': 'IT System User'},
          'Histories': {'records': [{'Field': 'Status', 'OldValue': 'New', 'NewValue': 'Working', 'CreatedDate': ago(30), 'CreatedBy': {'Name': 'Joe H'}},
                                    {'Field': 'Status', 'OldValue': None, 'NewValue': 'New', 'CreatedDate': ago(50), 'CreatedBy': {'Name': 'IT'}}]}},
         {'Id': '500B', 'CaseNumber': '01037999', 'Status': 'New', 'Subject': '', 'CreatedDate': ago(5), 'IsClosed': False, 'CreatedBy': {'Name': 'X'}}]


def test_case_events_created_status_changes_and_closed_in_time_order():
    ev = w.case_events(CASES)
    assert [e['type'] for e in ev] == ['case_created', 'case_status', 'case_closed', 'case_created']
    assert ev[0]['title'] == 'Case 01037263 opened' and 'ERS KMI Alerts' in ev[0]['detail'] and 'IT System User' in ev[0]['detail']
    assert ev[1]['title'] == 'Case 01037263: New to Working' and ev[1]['by'] == 'Joe H'
    s = w.case_summary(CASES)
    assert (s['count'], s['open'], s['numbers']) == (2, 1, ['01037999'])


def test_contact_counts_and_text_redaction():
    extras = {'calls': [{'kind': 'original', 'ts': ago(40)}, {'kind': 'callback', 'ts': ago(6)}, {'kind': 'call_other', 'ts': ago(1)}],
              'inbound_texts': [{'ts': ago(12)}]}
    steps = [{'kind': 'sms', 'detail': 'Your driver is coming', 'content': ['x']}, {'kind': 'sms', 'detail': 'b', 'content': []}, {'kind': 'human', 'detail': 'keep'}]
    c = w.contact_counts(extras, steps)
    assert (c['calls'], c['texts_in'], c['texts_out'], c['last_member_contact']) == (2, 1, 2, ago(6))
    red = w.strip_text_content(steps)
    assert red[0]['detail'] == '' and red[0]['content'] == [] and red[2]['detail'] == 'keep' and steps[0]['detail']      # input untouched
    assert w.contact_counts(None, [])['available'] is False


# ── the endpoint ────────────────────────────────────────────────────────────

SA_ID = '08pPb000009q4wnIAA'
SA_ROW = {'Id': SA_ID, 'AppointmentNumber': 'SA-1', 'Status': 'Dispatched', 'StatusCategory': 'Dispatched', 'CreatedDate': ago(100), 'ERS_PTA_Due__c': ago(40),
          'ParentRecordId': '1WL', 'ERS_Work_Order__c': '0WO', 'ERS_Work_Order__r': {'WorkOrderNumber': '0520'}, 'WorkType': {'Name': 'Tow'}, 'City': 'Buffalo',
          'Latitude': 43.0, 'Longitude': -78.8, 'ServiceTerritory': {'Name': '201 - GARAGE', 'Latitude': 43.1, 'Longitude': -78.9},
          'AAA_ERS_Account_Facility__r': {'Name': '201 - GARAGE', 'Phone': '(716) 555-0100'},
          'ServiceResources': {'records': [{'ServiceResourceId': 'asg', 'CreatedDate': ago(80), 'CreatedBy': {'Name': 'Jane Dee', 'Profile': {'Name': 'Membership User'}},
                                           'ServiceResource': {'Name': 'Assigned Driver', 'LastKnownLatitude': 43.2, 'LastKnownLongitude': -78.8, 'LastKnownLocationDate': ago(1),
                                                               'RelatedRecord': {'Phone': '5855550199'}}}]}}


def fake_composite(calls):
    def run(named):
        calls.append(sorted(named))
        with sf_client._stats_lock:
            sf_client._stats['total_calls'] += 1
        ok = lambda recs: {'status': 200, 'body': {'records': recs}}
        return {'sa': ok([SA_ROW]), 'contacts': ok([{'Name': f'C{i}', 'Phone': f'585555000{i}'} for i in range(5)]), 'cases': ok(CASES),
                'skills': ok([{'Skill': {'MasterLabel': 'Tow'}}]),
                'drivers': ok([_sr('near', 'Near Driver', 43.01, -78.8), _sr('asg', 'Assigned Driver', 43.2, -78.8, jobs=[_job('SA-7', 'En Route', 20)])])}
    return run


@pytest.fixture
def client(monkeypatch):
    import cache
    from routers import watchlist_call_map as r
    calls = []
    cache.invalidate(f'call_map:{SA_ID}')
    monkeypatch.setattr(w, 'now_utc', lambda: NOW)
    monkeypatch.setattr(w, 'sf_composite_query', fake_composite(calls))
    monkeypatch.setattr(r, '_role', lambda request: request.headers.get('x-test-role', 'ers-manager'))
    monkeypatch.setattr(r, '_story_bits', lambda sa_id, n, notes: {
        'steps': [{'id': 's1', 'kind': 'sms', 'ts': ago(60), 'title': 'Text sent', 'detail': 'Your driver is on the way', 'content': ['hi']},
                  {'id': 's2', 'kind': 'human', 'ts': ago(70), 'title': 'Assigned', 'detail': '', 'content': []}],
        'history': [{'ServiceAppointmentId': SA_ID, 'Field': 'Status', 'CreatedDate': ago(9), 'CreatedBy': {'Name': 'Pat Lee', 'Profile': {'Name': 'Membership User'}}}],
        'extras': {'calls': [{'kind': 'original', 'ts': ago(95)}], 'inbound_texts': [{'ts': ago(30)}]}, 'promise': ago(40), 'towbook': False})
    app = FastAPI()
    app.include_router(r.router)
    c = TestClient(app)
    c.composite_calls = calls
    yield c
    cache.invalidate(f'call_map:{SA_ID}')


def test_endpoint_bundles_everything_and_costs_one_composite(client):
    before = sf_client.get_stats()['total_calls']
    body = client.get(f'/api/watchlist/call-map/{SA_ID}').json()
    assert sf_client.get_stats()['total_calls'] - before == 1 and len(client.composite_calls) == 1
    assert body['sf_calls'] == 1                                            # story and extras are stubbed here, so only the map's own request is counted
    assert sorted(client.composite_calls[0]) == ['cases', 'contacts', 'drivers', 'sa', 'skills']
    assert body['sa']['late_min'] == 40 and body['sa']['late']['level'] == 'orange'
    assert [c['name'] for c in body['garage']['contacts']] == ['C0', 'C1', 'C2']        # up to 3
    assert body['driver']['name'] == 'Assigned Driver' and body['driver']['held'] == 1 and body['driver']['phone'] == '5855550100'
    assert [p['name'] for p in body['peers']] == ['Near Driver'] and 'free, qualified' in body['suggestion']['text']
    assert body['working']['name'] == 'Pat Lee'
    assert body['contact'] == {'available': True, 'calls': 1, 'texts_in': 1, 'texts_out': 1, 'last_member_contact': ago(30)}
    assert body['cases']['open'] == 1 and any(e['type'] == 'case_closed' for e in body['cases']['events'])


def test_second_open_within_60_seconds_is_served_from_the_cache(client):
    client.get(f'/api/watchlist/call-map/{SA_ID}')
    before = sf_client.get_stats()['total_calls']
    client.get(f'/api/watchlist/call-map/{SA_ID}')
    assert sf_client.get_stats()['total_calls'] == before and len(client.composite_calls) == 1


def test_text_content_only_for_replay_roles_but_counts_for_everyone(client):
    admin = client.get(f'/api/watchlist/call-map/{SA_ID}', headers={'x-test-role': 'admin'}).json()
    director = client.get(f'/api/watchlist/call-map/{SA_ID}', headers={'x-test-role': 'ers-director'}).json()
    sms = lambda b: next(s for s in b['steps'] if s['kind'] == 'sms')
    assert admin['can_read_texts'] and sms(admin)['detail'] == 'Your driver is on the way'
    assert not director['can_read_texts'] and sms(director)['detail'] == '' and sms(director)['content'] == []
    assert director['contact']['texts_out'] == 1 and director['contact']['texts_in'] == 1
    assert director['garage']['phone'] and director['driver']['phone']          # phones are fine for all Watchlist users


def test_contractors_are_refused_and_bad_ids_rejected(client):
    assert client.get(f'/api/watchlist/call-map/{SA_ID}', headers={'x-test-role': 'contractor'}).status_code == 403
    assert client.get('/api/watchlist/call-map/not-an-id').status_code == 400


def test_towbook_calls_never_name_a_driver():
    sf = {'sa': [SA_ROW], 'skills': [], 'contacts': [], 'cases': [], 'drivers': []}
    out = w.assemble(sf, {'towbook': True, 'steps': [], 'history': []}, NOW)
    assert out['driver'] is None and out['peers'] == [] and out['sa']['towbook'] is True


def _step(actor, role, mins, title='Assigned'):
    return {'actor': actor, 'role': role, 'ts': ago(mins), 'title': title}


def test_garage_dispatcher_is_the_fallback_when_no_call_center_dispatcher_acted():
    steps = [_step('Joel Isaman', 'Garage dispatcher', 20), _step('Joel Isaman', 'Garage dispatcher', 7), _step('Mary', 'Garage dispatcher', 30),
             _step('IT System User', 'Integration', 1), _step('Platform Integration User', 'FSL optimizer', 2), _step('Some Admin', 'AAA staff', 1)]
    got = w.working_now([_hist('Contact Center', 'Cc', 2)], [], 'SA1', NOW, steps)
    assert (got['name'], got['minutes_ago'], got['kind']) == ('Joel Isaman', 7, 'garage')
    assert w.working_now([], [], 'SA1', NOW, [_step('IT System User', 'Integration', 1)]) is None


def test_call_center_dispatcher_wins_over_the_garage_dispatcher():
    got = w.working_now([_hist('Membership User', 'Jane Dee', 15)], [], 'SA1', NOW, [_step('Joel Isaman', 'Garage dispatcher', 1)])
    assert got['name'] == 'Jane Dee' and 'kind' not in got
