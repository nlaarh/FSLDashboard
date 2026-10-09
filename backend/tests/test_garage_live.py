"""Garage Live: the attention rules (each rule, ranking, thresholds), the assembled view, Towbook handling, permissions and the Salesforce cost."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import cache
import garage_live as gl
import garage_live_rules as rules
from garage_live_rules import THRESHOLDS

NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)
ago = lambda m: (NOW - timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%M:%S.000+0000')
G, OTHER = '0HhGARAGE0000001', '0HhOTHER00000002'


@pytest.fixture(autouse=True)
def clean():
    gl.reset_trail()
    cache.invalidate('')
    yield
    cache.invalidate('')


# ── fake Watchlist snapshot ──
def sa(i, status='Dispatched', created=60, pta=45, wt='Tow', terr=G, cat=None, lat=43.0, lon=-78.8, fac='100 - WNY Fleet', phone='(716) 555-0100'):
    return {'Id': f'SA{i}', 'AppointmentNumber': f'SA-{i}', 'Status': status, 'StatusCategory': cat or {'Completed': 'Completed', 'On Location': 'InProgress'}.get(status, 'Dispatched'),
            'ServiceTerritoryId': terr, 'ServiceTerritory': {'Name': fac}, 'WorkType': {'Name': wt}, 'ERS_PTA__c': pta, 'CreatedDate': ago(created),
            'Latitude': lat, 'Longitude': lon, 'City': 'Buffalo', 'Street': '1 Main St', 'ParentRecordId': f'WL{i}', 'WO_Priority_Code__c': None,
            'AAA_ERS_Account_Facility__r': {'Name': fac, 'Phone': phone}}


def ar(driver, name, given=30, typ='Fleet Driver'):
    return {'ServiceResource': {'Id': driver, 'Name': name, 'ERS_Driver_Type__c': typ}, 'CreatedDate': ago(given)}


def hist(status, mins):
    return {'Field': 'Status', 'NewValue': status, 'CreatedDate': ago(mins)}


def snapshot(sas, ars=None, hists=None):
    return {'now': NOW, 'sas': sas, 'ar_by_sa': ars or {}, 'hist_by_sa': hists or {}, 'wo_by_woli': {f'WL{i}': {'wo_id': f'WO{i}', 'wo': {'WorkOrderNumber': f'00{i}'}} for i in range(1, 30)},
            'dup_candidates': [], 'no_sa_wos': []}


def drv(i, name, lat=43.0, lon=-78.8, gps=1):
    return {'Id': i, 'Name': name, 'LastKnownLatitude': lat, 'LastKnownLongitude': lon, 'LastKnownLocationDate': ago(gps), 'RelatedRecord': {'Phone': '5855550100'}}


TRUCKS = [{'ERS_Driver__c': d, 'Name': f'T-{d}', 'ERS_Truck_Capabilities__c': 'Flat Bed;Tow'} for d in ('D1', 'D2', 'D3')]
MEMBERS = [{'ServiceResourceId': d, 'ServiceTerritoryId': G} for d in ('D1', 'D2', 'D3', 'D4')]
DRIVERS = [drv('D1', 'Ann Lee 100'), drv('D2', 'Bob Ray 101', 43.1, -78.9), drv('D3', 'Cy Poe 102', 43.5, -79.0), drv('D4', 'Dee Off 103')]


def build(sas, ars=None, hists=None, result=None, skills=None, drivers=DRIVERS, members=MEMBERS, garage=G):
    return gl.build(garage, snapshot(sas, ars, hists), result or {'operational_alerts': [], 'watchlist': []}, drivers, TRUCKS, members, NOW, skills,
                    {'name': '100 - WNY Fleet', 'lat': 43.0, 'lon': -78.9})


def rule_ids(body, rule):
    return [i for i in body['attention'] if i['rule'] == rule]


# ── Rule 1: member waiting past the promise ─────────────────────────────────

@pytest.mark.parametrize('created,level', [(45, None), (46, 'yellow'), (75, 'yellow'), (76, 'orange'), (134, 'orange'), (135, 'red'), (300, 'red')])
def test_late_member_levels(created, level):
    body = build([sa(1, 'Dispatched', created=created, pta=45)], {'SA1': [ar('D1', 'Ann Lee 100', 5)]})
    late = rule_ids(body, 'late')
    if level is None:
        assert not late
    else:
        assert late[0]['severity'] == level
        assert f"waited {rules.fmt_min(created - 45)} past the promise on SA-1 (Tow)" in late[0]['text'] and 'Driver: Ann Lee.' in late[0]['text']


def test_member_on_scene_no_longer_waits():
    body = build([sa(1, 'On Location', created=200, pta=45)], {'SA1': [ar('D1', 'Ann Lee 100')]}, {'SA1': [hist('On Location', 5)]})
    assert not rule_ids(body, 'late') and body['summary']['waiting_calls'] == 0 and body['tickets'][0]['late']['level'] == 'ok'


def test_drop_offs_are_not_tickets_and_not_counted():
    body = build([sa(1, 'Dispatched', wt='Tow Drop-Off'), sa(2)], {'SA2': [ar('D1', 'Ann Lee 100')]})
    assert [t['number'] for t in body['tickets']] == ['SA-2'] and body['summary']['open_calls'] == 1


# ── Rule 2: call not accepted ───────────────────────────────────────────────

def test_garage_received_and_rejected_and_driver_not_accepted():
    sas = [sa(1, 'Received', created=20, pta=90), sa(2, 'Received', created=4, pta=90), sa(3, 'Rejected', pta=90), sa(4, 'Dispatched', pta=90), sa(5, 'Dispatched', pta=90)]
    ars = {'SA4': [ar('D1', 'Ann Lee 100', 14)], 'SA5': [ar('D2', 'Bob Ray 101', 4)]}
    hists = {'SA1': [hist('Received', 15)], 'SA2': [hist('Received', 4)], 'SA3': [hist('Rejected', 2)], 'SA4': [hist('Dispatched', 14)], 'SA5': [hist('Dispatched', 4)]}
    got = {i['sa_number']: i for i in rule_ids(build(sas, ars, hists), 'not_accepted')}
    assert set(got) == {'SA-1', 'SA-3', 'SA-4'}                                 # SA-2 (4 min) and SA-5 (4 min) are still fine
    assert 'Received for 15 min' in got['SA-1']['text'] and got['SA-1']['severity'] == 'orange'
    assert got['SA-3']['severity'] == 'red' and 'rejected' in got['SA-3']['text']
    assert 'Ann Lee was given SA-4 (Tow) 14 min ago and has not accepted it' in got['SA-4']['text']


def test_not_accepted_clock_restarts_when_the_call_is_reassigned():
    ars = {'SA1': [ar('D1', 'Ann Lee 100', 50), ar('D2', 'Bob Ray 101', 3)]}
    body = build([sa(1, 'Dispatched', pta=300)], ars, {'SA1': [hist('Dispatched', 50)]})
    assert not rule_ids(body, 'not_accepted')                                    # Bob got it 3 min ago
    body = build([sa(1, 'Dispatched', pta=300)], {'SA1': [ar('D1', 'Ann Lee 100', 50)]}, {'SA1': [hist('Dispatched', 50)]})
    assert rule_ids(body, 'not_accepted')[0]['severity'] == 'red'                # 50 min >= 30


# ── Rule 3: driver on scene too long ────────────────────────────────────────

@pytest.mark.parametrize('wt,mins,sev', [('Battery', 59, None), ('Battery', 61, 'orange'), ('Battery', 121, 'red'), ('Tow', 61, None), ('Tow', 119, None), ('Tow', 125, 'red')])
def test_on_scene_too_long(wt, mins, sev):
    body = build([sa(1, 'On Location', wt=wt, pta=999)], {'SA1': [ar('D1', 'Ann Lee 100')]}, {'SA1': [hist('On Location', mins)]})
    got = rule_ids(body, 'on_scene')
    assert (got[0]['severity'] if got else None) == sev
    if got and mins == 125:
        assert got[0]['text'] == 'Ann Lee has been on scene 2 h 05 min at SA-1 (Tow).'


# ── Rule 4: driver en route too long / not moving ───────────────────────────

def test_en_route_too_long_and_red():
    ars = {'SA1': [ar('D1', 'Ann Lee 100')], 'SA2': [ar('D2', 'Bob Ray 101')]}
    hists = {'SA1': [hist('En Route', 44)], 'SA2': [hist('En Route', 95)]}
    got = {i['sa_number']: i for i in rule_ids(build([sa(1, 'En Route', pta=999), sa(2, 'En Route', pta=999)], ars, hists), 'en_route')}
    assert set(got) == {'SA-2'} and got['SA-2']['severity'] == 'red' and 'driving to SA-2 for 1 h 35 min' in got['SA-2']['text']
    assert rule_ids(build([sa(1, 'En Route', pta=999)], {'SA1': [ar('D1', 'Ann Lee 100')]}, {'SA1': [hist('En Route', 46)]}), 'en_route')[0]['severity'] == 'orange'


def test_not_moving_from_the_position_trail_and_from_an_old_gps_date():
    ars, hists = {'SA1': [ar('D1', 'Ann Lee 100')]}, {'SA1': [hist('En Route', 10)]}
    s = [sa(1, 'En Route', pta=999)]
    for minutes_ago in (16, 8, 0):                                               # three reads over 16 minutes at the same spot
        snap_now = NOW - timedelta(minutes=minutes_ago)
        gl.note_position('D1', 43.0, -78.8, snap_now)
    body = build(s, ars, hists)
    assert [i['text'] for i in rule_ids(body, 'not_moving')] == ['Ann Lee has not moved in 16 min while driving to SA-1.']
    gl.reset_trail()
    assert not rule_ids(build(s, ars, hists), 'not_moving')                      # nothing known yet: stays silent
    old = [drv('D1', 'Ann Lee 100', gps=20)]
    assert 'not moved in 20 min' in rule_ids(build(s, ars, hists, drivers=old), 'not_moving')[0]['text']


def test_moving_driver_is_not_flagged_as_stuck():
    ars, hists = {'SA1': [ar('D1', 'Ann Lee 100')]}, {'SA1': [hist('En Route', 10)]}
    for minutes_ago, lat in ((16, 43.0), (8, 43.02), (0, 43.04)):
        gl.note_position('D1', lat, -78.8, NOW - timedelta(minutes=minutes_ago))
    assert not rule_ids(build([sa(1, 'En Route', pta=999)], ars, hists, drivers=[drv('D1', 'Ann Lee 100', 43.04)]), 'not_moving')


# ── Rule 5: job but GPS old ─────────────────────────────────────────────────

def test_gps_older_than_30_minutes_with_a_job():
    ars = {'SA1': [ar('D1', 'Ann Lee 100')], 'SA2': [ar('D2', 'Bob Ray 101')], 'SA3': [ar('D3', 'Cy Poe 102')]}
    drivers = [drv('D1', 'Ann Lee 100', gps=29), drv('D2', 'Bob Ray 101', gps=45), drv('D3', 'Cy Poe 102', gps=90)]
    s = [sa(1, 'Dispatched', pta=999), sa(2, 'Dispatched', pta=999), sa(3, 'Dispatched', pta=999)]
    got = {i['driver_id']: i for i in rule_ids(build(s, ars, drivers=drivers), 'gps')}
    assert set(got) == {'D2', 'D3'} and got['D2']['severity'] == 'yellow' and got['D3']['severity'] == 'orange'
    assert 'GPS has not updated for 45 min' in got['D2']['text']
    free_old = build([], drivers=[drv('D1', 'Ann Lee 100', gps=500)])
    assert not rule_ids(free_old, 'gps')                                         # a free driver with old GPS is just off the map


# ── Rule 6: Watchlist flags (same flags, same wording) ──────────────────────

ALERTS = [{'sa_id': 'SA1', 'sa_number': 'SA-1', 'flag': 'High Priority Call Late', 'pta_delta_min': 20, 'work_type': 'Tow', 'territory_id': G},
          {'sa_id': 'SA2', 'sa_number': 'SA-2', 'flag': 'Potential Duplicate', 'pta_delta_min': None, 'work_type': 'Tow', 'territory_id': G, 'duplicate_of': ['SA-9']},
          {'sa_id': 'SA1', 'sa_number': 'SA-1', 'flag': 'Call At Risk of Missing PTA', 'pta_delta_min': 20, 'work_type': 'Tow', 'territory_id': G},
          {'sa_id': 'SAX', 'sa_number': 'SA-X', 'flag': 'Potential Duplicate', 'pta_delta_min': None, 'work_type': 'Tow', 'territory_id': OTHER},
          {'sa_id': '', 'sa_number': '', 'wo_number': '0777', 'flag': 'No Service Appointments on Work Order', 'pta_delta_min': None, 'work_type': 'Tow', 'territory_id': G}]


def test_watchlist_flags_for_this_garage_only_and_not_said_twice():
    result = {'operational_alerts': ALERTS, 'watchlist': [{'sa_number': 'SA-2', 'reason': '3 driver changes'}]}
    body = build([sa(1, 'Dispatched', created=65, pta=45), sa(2, 'Dispatched', pta=999)], {'SA1': [ar('D1', 'Ann Lee 100', 5)], 'SA2': [ar('D2', 'Bob Ray 101', 5)]}, result=result)
    texts = [i['text'] for i in rule_ids(body, 'watchlist')]
    assert 'Watchlist: High Priority Call Late. SA-1 Tow (20 min past the promise).' in texts
    assert 'Watchlist: Potential Duplicate. SA-2 Tow. Same member: SA-9.' in texts
    assert 'Watchlist: No Service Appointments on Work Order. WO 0777 Tow.' in texts
    assert 'Watchlist: SA-2 is followed for 3 driver changes.' in texts
    assert not any('SA-X' in t for t in texts)                                   # another garage
    assert not any('At Risk' in t for t in texts)                                # SA-1 is already late: the late line says it
    assert body['tickets'][0]['flags'] == ['High Priority Call Late', 'Call At Risk of Missing PTA']


# ── Rule 7: free qualified driver closer than the assigned one ──────────────

def test_closer_free_qualified_driver():
    s = [sa(1, 'Dispatched', created=20, pta=60, lat=43.0, lon=-78.8)]
    ars = {'SA1': [ar('D3', 'Cy Poe 102', 5)]}                                    # D3 is 0.5 deg away; D1 sits on the call
    provider = lambda wolis, drivers: ({'WL1': {'Tow'}}, {'D1': {'Tow'}, 'D2': set()})
    body = build(s, ars, skills=provider)
    got = rule_ids(body, 'closer_driver')
    assert got[0]['text'].startswith('SA-1 (Tow): Ann Lee is free, qualified and 0.0 mi away.') and 'The assigned driver, Cy Poe, is 36.0 mi away.' in got[0]['text']
    none = lambda wolis, drivers: ({'WL1': {'Winch Out'}}, {'D1': {'Tow'}})        # nobody holds the required skill (trucks give Flat Bed, Tow)
    assert not rule_ids(build(s, ars, skills=none), 'closer_driver')
    assert not rule_ids(build(s, ars, skills=lambda *a: None), 'closer_driver')    # skills unreadable: silent, with a note
    assert 'Driver skills could not be read' in build(s, ars, skills=lambda *a: None)['notes'][0]
    assert not rule_ids(build([sa(1, 'Dispatched', created=2, pta=60)], ars, skills=provider), 'closer_driver')   # waiting under 5 min


def test_skills_are_not_asked_for_when_nobody_is_free_or_nobody_waits():
    asked = []
    provider = lambda w, d: asked.append((w, d)) or ({}, {})
    build([], skills=provider)
    busy = [ar(d, n) for d, n in (('D1', 'Ann Lee 100'), ('D2', 'Bob Ray 101'), ('D3', 'Cy Poe 102'))]
    build([sa(i + 1, 'En Route', pta=999) for i in range(3)], {f'SA{i + 1}': [busy[i]] for i in range(3)}, skills=provider)
    assert asked == []


# ── Rule 8: capacity, and the ranking ───────────────────────────────────────

def test_capacity_line_and_counts():
    s = [sa(i, 'Dispatched', created=5, pta=90) for i in range(1, 6)]
    body = build(s)
    cap = rule_ids(body, 'capacity')[0]
    assert cap['text'] == '5 calls waiting, 3 free drivers.' and cap['severity'] == 'info'
    assert body['summary']['drivers'] == {'free': 3, 'busy': 0, 'off': 1}      # D4 has no truck login
    busy = build(s, {f'SA{i}': [ar(('D1', 'D2', 'D3')[i % 3], 'x')] for i in range(1, 6)})
    assert rule_ids(busy, 'capacity')[0]['text'] == '5 calls waiting, 0 free drivers.' and rule_ids(busy, 'capacity')[0]['severity'] == 'orange'
    assert not rule_ids(build([]), 'capacity')


def test_ranking_severity_then_rule_then_minutes():
    s = [sa(1, 'Dispatched', created=200, pta=45), sa(2, 'Dispatched', created=100, pta=45), sa(3, 'Received', created=30, pta=999), sa(4, 'On Location', wt='Tow', pta=999)]
    ars = {'SA1': [ar('D1', 'Ann Lee 100', 5)], 'SA2': [ar('D2', 'Bob Ray 101', 5)], 'SA4': [ar('D3', 'Cy Poe 102')]}
    hists = {'SA3': [hist('Received', 25)], 'SA4': [hist('On Location', 130)]}
    order = [(i['severity'], i['rule'], i['sa_number']) for i in build(s, ars, hists)['attention']]
    assert order[:4] == [('red', 'late', 'SA-1'), ('red', 'on_scene', 'SA-4'), ('orange', 'late', 'SA-2'), ('orange', 'not_accepted', 'SA-3')]
    assert order[-1][1] == 'capacity'


def test_thresholds_are_one_dict_and_change_the_outcome():
    s = [sa(1, 'On Location', wt='Battery', pta=999)]
    ars, hists = {'SA1': [ar('D1', 'Ann Lee 100')]}, {'SA1': [hist('On Location', 40)]}
    assert not rule_ids(build(s, ars, hists), 'on_scene')
    tight = {**THRESHOLDS, 'on_scene_light_min': 30}
    body = build(s, ars, hists)
    items = rules.build_attention(body['tickets'], body['drivers'], [], [], body['summary'], lambda t, d: False, th=tight)
    assert [i['rule'] for i in items if i['rule'] == 'on_scene'] == ['on_scene']


# ── The assembled view ──────────────────────────────────────────────────────

def test_drivers_status_queue_phone_truck_and_time_in_status():
    s = [sa(1, 'On Location', wt='Tow', pta=999), sa(2, 'Dispatched', pta=999, wt='Battery'), sa(3, 'En Route', pta=999, wt='Tow Drop-Off', terr=OTHER)]
    ars = {'SA1': [ar('D1', 'Ann Lee 100', 90)], 'SA2': [ar('D1', 'Ann Lee 100', 10)], 'SA3': [ar('D2', 'Bob Ray 101', 20)]}
    hists = {'SA1': [hist('On Location', 40)], 'SA3': [hist('En Route', 12)]}
    body = build(s, ars, hists)
    d = {x['id']: x for x in body['drivers']}
    assert (d['D1']['status'], d['D1']['status_min'], d['D1']['truck'], d['D1']['phone']) == ('on_scene', 40, 'T-D1', '5855550100')
    assert d['D1']['job']['number'] == 'SA-1' and d['D1']['queue'] == [{'sa_id': 'SA2', 'number': 'SA-2', 'work_type': 'Battery', 'label': 'not started', 'territory_id': G}]
    assert (d['D2']['status'], d['D2']['status_min'], d['D2']['held']) == ('towing', 12, 0)     # a moving drop-off means towing, never a call
    assert d['D3']['status'] == 'free' and 'D4' not in d                                           # D4: roster but no truck login = off


def test_driver_from_another_garage_holding_this_garages_call_is_listed():
    body = build([sa(1, 'En Route', pta=999)], {'SA1': [ar('DX', 'Visiting Vic 900')]}, {'SA1': [hist('En Route', 3)]},
                 drivers=DRIVERS + [drv('DX', 'Visiting Vic 900')])
    assert 'DX' in {d['id'] for d in body['drivers']}


def test_excluded_test_and_spare_drivers_are_left_out():
    drivers = DRIVERS + [drv('D5', 'Test Truck'), drv('D6', '000-Spare')]
    members = MEMBERS + [{'ServiceResourceId': d, 'ServiceTerritoryId': G} for d in ('D5', 'D6')]
    trucks = TRUCKS + [{'ERS_Driver__c': d, 'Name': 'x', 'ERS_Truck_Capabilities__c': ''} for d in ('D5', 'D6')]
    body = gl.build(G, snapshot([]), {}, drivers, trucks, members, NOW)
    assert {d['id'] for d in body['drivers']} == {'D1', 'D2', 'D3'}


def test_unknown_garage_is_none():
    assert gl.build('0HhNOBODY0000009', snapshot([]), {}, DRIVERS, TRUCKS, MEMBERS, NOW) is None


# ── Towbook garages ─────────────────────────────────────────────────────────

def test_towbook_garage_shows_tickets_only_and_never_names_a_driver():
    tb = lambda: {'ServiceResource': {'Id': 'TB1', 'Name': 'Towbook-Joe Smith', 'ERS_Driver_Type__c': 'Off-Platform Contractor Driver'}, 'CreatedDate': ago(50)}
    s = [sa(1, 'Dispatched', created=120, pta=45, terr='0HhTOWBOOK000003', fac='201 - TOWBOOK GARAGE'), sa(2, 'On Location', created=80, pta=45, terr='0HhTOWBOOK000003', fac='201 - TOWBOOK GARAGE')]
    body = gl.build('0HhTOWBOOK000003', snapshot(s, {'SA1': [tb()], 'SA2': [tb()]}, {'SA2': [hist('On Location', 500)]}), {}, DRIVERS, TRUCKS, MEMBERS, NOW)
    assert body['garage']['kind'] == 'towbook' and body['garage']['has_gps'] is False and body['drivers'] == []
    assert all(t['driver_name'] is None and t['towbook'] for t in body['tickets'])
    assert 'Towbook garage' in body['notes'][0]
    assert 'Joe' not in str(body) and 'Smith' not in str(body)
    assert [i['rule'] for i in body['attention']] == ['late', 'capacity'] and 'Towbook driver' in body['attention'][0]['text']
    assert not any(i['rule'] in ('on_scene', 'en_route', 'gps', 'closer_driver') for i in body['attention'])


def test_garage_kinds():
    assert gl.build(G, snapshot([sa(1)], {'SA1': [ar('D1', 'Ann Lee 100')]}), {}, DRIVERS, TRUCKS, MEMBERS, NOW)['garage']['kind'] == 'fleet'
    op = gl.build(OTHER, snapshot([sa(1, terr=OTHER, fac='076DO - TRANSIT')], {'SA1': [ar('D1', 'Ann Lee 100', typ='On-Platform Contractor Driver')]}), {}, DRIVERS, TRUCKS,
                  [{'ServiceResourceId': 'D1', 'ServiceTerritoryId': OTHER}], NOW)
    assert op['garage']['kind'] == 'on_platform' and op['garage']['phone'] == '(716) 555-0100'


# ── Endpoint: permissions, zero Salesforce, one build for many viewers ──────

@pytest.fixture
def api(monkeypatch):
    from routers import garage_live as router
    state = {'role': 'ers-manager', 'territories': [], 'builds': 0, 'sf': 0}
    snap = state['snap'] = snapshot([sa(1, 'Dispatched', created=100, pta=45), sa(2, 'Dispatched', terr=OTHER, created=100, pta=45)], {'SA1': [ar('D1', 'Ann Lee 100', 5)], 'SA2': [ar('D1', 'Ann Lee 100', 3)]})
    snap['sas'][1]['ServiceTerritory'] = {'Name': '201 - OTHER'}

    def shared():
        state['builds'] += 1
        return snap, {'operational_alerts': [], 'watchlist': [], 'last_updated': NOW.isoformat()}
    monkeypatch.setattr(router.watchlist, 'shared_state', shared)
    monkeypatch.setattr(router.ref_data, 'drivers', lambda **k: DRIVERS)
    monkeypatch.setattr(router.ref_data, 'trucks', lambda **k: TRUCKS)
    monkeypatch.setattr(router.ref_data, 'members', lambda: MEMBERS + [{'ServiceResourceId': 'D1', 'ServiceTerritoryId': OTHER}])
    monkeypatch.setattr(router, '_now', lambda: NOW)
    monkeypatch.setattr(router, 'sf_query_all', lambda q: state.__setitem__('sf', state['sf'] + 1) or [])
    monkeypatch.setattr(router, 'get_request_username', lambda r: 'u')
    monkeypatch.setattr(router._users, 'get_user', lambda u: {'role': state['role'], 'territories': state['territories']})
    import routers.garages as garages
    monkeypatch.setattr(garages, 'get_request_username', lambda r: 'u')
    monkeypatch.setattr(garages._users, 'get_user', lambda u: {'role': state['role'], 'territories': state['territories']})
    app = FastAPI()
    app.include_router(router.router)
    return TestClient(app), state


def test_endpoint_returns_the_garage_view(api):
    client, state = api
    r = client.get(f'/api/garage-live/{G}')
    assert r.status_code == 200
    body = r.json()
    assert body['garage']['name'] == '100 - WNY Fleet' and [t['number'] for t in body['tickets']] == ['SA-1'] and body['can_replay'] is True
    assert state['sf'] == 2                  # a call waits and drivers are free: the call's skills + the free drivers' skills, one SELECT each


def test_no_salesforce_at_all_when_no_call_waits_for_a_free_driver(api):
    client, state = api
    state['snap']['sas'][0]['CreatedDate'] = ago(2)                                # a 2-minute-old call: too young for the suggestion rule
    assert client.get(f'/api/garage-live/{G}').status_code == 200 and state['sf'] == 0


def test_three_viewers_share_one_build(api):
    client, state = api
    for _ in range(3):
        assert client.get(f'/api/garage-live/{G}').status_code == 200
    assert state['builds'] == 1 and state['sf'] == 2                              # three viewers, one build, the skills read once


def test_contractor_gets_own_garage_only_and_no_replay(api):
    client, state = api
    state.update(role='contractor', territories=[G])
    assert client.get(f'/api/garage-live/{OTHER}').status_code == 403
    r = client.get(f'/api/garage-live/{G}')
    assert r.status_code == 200 and r.json()['can_replay'] is False
    d = r.json()['drivers'][0]
    assert d['id'] == 'D1' and [q['number'] for q in d['queue']] == ['Another garage']   # D1's call SA-2 belongs to another garage
    assert d['job']['number'] == 'SA-1'
    assert 'SA-2' not in r.text and '201 - OTHER' not in r.text


def test_bad_id_and_unknown_garage(api):
    client, _ = api
    assert client.get('/api/garage-live/bad id!').status_code in (400, 404)
    assert client.get('/api/garage-live/0HhNOBODY0000009').status_code == 404


def test_salesforce_down_is_a_503(api, monkeypatch):
    client, _ = api
    from routers import garage_live as router
    monkeypatch.setattr(router.watchlist, 'shared_state', lambda: (_ for _ in ()).throw(RuntimeError('down')))
    assert client.get(f'/api/garage-live/{G}').status_code == 503


# ── Skills reads: shared, once per id ───────────────────────────────────────

def test_skills_provider_reads_each_call_and_driver_once(monkeypatch):
    from routers import garage_live as router
    queries = []
    monkeypatch.setattr(router, 'sf_query_all', lambda q: queries.append(q) or (
        [{'RelatedRecordId': 'WL1', 'Skill': {'MasterLabel': 'Tow'}}] if 'SkillRequirement' in q else [{'ServiceResourceId': 'D1', 'Skill': {'MasterLabel': 'Tow'}}]))
    got = router.skills_provider(['WL1', 'WL2'], ['D1', 'D2'])
    assert got == ({'WL1': {'Tow'}, 'WL2': set()}, {'D1': {'Tow'}, 'D2': set()}) and len(queries) == 2
    router.skills_provider(['WL1', 'WL2'], ['D1', 'D2'])
    assert len(queries) == 2                                                     # all remembered (an id with no skills too)
    assert all(q.lstrip().startswith('SELECT') for q in queries)


def test_contractor_never_sees_another_garages_call_number_in_a_shared_drivers_job_or_the_drawer():
    from routers.garage_live import _redact_for_contractor
    foreign = {'sa_id': 'SA9', 'number': 'SA-9', 'work_type': 'Tow', 'territory_id': OTHER, 'status': 'On Location', 'is_light': False}
    body = {'tickets': [{'sa_id': 'SA1'}], 'drivers': [{'id': 'D1', 'job': foreign, 'queue': [{'sa_id': 'SA9', 'number': 'SA-9', 'work_type': 'Tow', 'label': 'x', 'territory_id': OTHER}]}],
            'attention': [{'sa_id': 'SA9', 'text': 'Ann has been on scene at SA-9'}, {'sa_id': 'SA1', 'text': 'mine'}, {'sa_id': None, 'text': '5 calls waiting'}]}
    out = _redact_for_contractor(body, G)
    assert 'SA-9' not in str(out) and out['drivers'][0]['job']['number'] == 'Another garage'
    assert [i['text'] for i in out['attention']] == ['mine', '5 calls waiting']
    assert 'SA-9' in str(body)                                                     # the shared cached copy is untouched


def test_road_endpoint_uses_the_shared_osrm_lookup_and_refuses_jumps(api, monkeypatch):
    client, _ = api
    from routers import garage_live as router
    calls = []
    monkeypatch.setattr(router.osrm, 'route', lambda pts, timeout=8, cached=True: calls.append(pts) or {'coords': [[43.0, -78.8], [43.001, -78.801]], 'miles': 0.1})
    r = client.get('/api/garage-live-road?a=43.0,-78.8&b=43.001,-78.801')
    assert r.status_code == 200 and r.json()['coords'][1] == [43.001, -78.801] and calls == [[(43.0, -78.8), (43.001, -78.801)]]
    assert client.get('/api/garage-live-road?a=43.0,-78.8&b=44.0,-78.8').status_code == 400      # ~69 miles: a jump, not a drive
    assert client.get('/api/garage-live-road?a=x&b=1,2').status_code == 400
    monkeypatch.setattr(router.osrm, 'route', lambda *a, **k: None)
    assert client.get('/api/garage-live-road?a=43.0,-78.8&b=43.001,-78.801').status_code == 204  # OSRM down: the screen draws a straight line
