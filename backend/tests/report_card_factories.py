"""Synthetic Scheduler Report Card inputs (fake ids and names) shared by the report card tests."""

import copy
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / 'fixtures' / 'report_card'
D1, D2, D3 = '0HnFAKE00000001AAA', '0HnFAKE00000002AAA', '0HnFAKE00000003AAA'


def load_wny_0928() -> dict:
    """Anonymised verdict inputs for the 90 SAs of 100 WNY Fleet on 2026-09-28 (spec 6.1, 7.4)."""
    return json.loads((FIXTURES / 'wny_2026-09-28_verdict_inputs.json').read_text())


def cand(driver, miles, open_jobs=0, on_shift=1, qualified=1, member=1):
    return [driver, None, None, miles, qualified, on_shift, open_jobs, 2.0 if miles is not None else None, member]


def make_sa(**over) -> dict:
    """One scored SA in snapshot shape: Fleet, PTA 60, assigned at +1 min to D1 at 3 mi, on time."""
    sa = {
        'id': '08pFAKE00000001AAA', 'number': 'SA-0000001', 'in_day': True, 'is_drop_off': False,
        'lat': 43.0, 'lon': -78.8, 'status': 'Completed', 'required_skills': [], 'events': [], 'busy': None,
        'created': '2026-09-28T16:00:00.000Z', 'pta_min': 60, 'pta_due': '2026-09-28T17:00:00.000Z',
        'channel': 'fleet', 'final_driver_id': D1,
        'decision': {'final': {'actor': 'Mulesoft Integration', 'actor_profile': 'AAACRM Mulesoft Integration User',
                               'actor_is_driver': False, 'ts': '2026-09-28T16:01:00.000Z'},
                     'first': {'actor': 'Mulesoft Integration', 'actor_profile': 'AAACRM Mulesoft Integration User',
                               'actor_is_driver': False, 'ts': '2026-09-28T16:01:00.000Z'},
                     'n_picks': 1, 'n_pre_dispatch_picks': 1, 'pullbacks': 0, 'reassign_after_dispatch': 0,
                     'ar_creator': {'name': 'Mulesoft Integration'}},
        'territory_moves': {'in': 0, 'from': []},
        'milestones': {'t_first': '2026-09-28T16:01:00.000Z', 't_asg': '2026-09-28T16:01:00.000Z',
                       't_disp': '2026-09-28T16:02:00.000Z', 't_acc': None, 't_er': '2026-09-28T16:05:00.000Z',
                       't_ol': '2026-09-28T16:40:00.000Z', 't_end': '2026-09-28T17:10:00.000Z',
                       'end_status': 'Completed', 'actual_end': None,
                       'arrival': '2026-09-28T16:40:00.000Z', 'arrival_source': 'actual_start'},
        'decision_set_idx': 0,
        'candidate_sets': [{'event_idx': 0, 'ts': '2026-09-28T16:01:00.000Z', 'c': [cand(D1, 3.0), cand(D2, 6.0)]}],
        'free_samples': {'step_min': 2, 'pre': [], 'queue': []},
    }
    for k, v in over.items():
        if k in ('decision', 'milestones'):
            sa[k] = {**sa[k], **v}
        else:
            sa[k] = v
    return sa


def late(sa: dict) -> dict:
    """Same SA, arriving 30 min after the PTA deadline."""
    sa = copy.deepcopy(sa)
    sa['milestones']['arrival'] = sa['milestones']['t_ol'] = '2026-09-28T17:30:00.000Z'
    sa['milestones']['t_end'] = '2026-09-28T18:00:00.000Z'
    return sa


def _hist(sa_id, field, ts, new, old=None, actor='Mulesoft Integration', profile='AAACRM Mulesoft Integration User',
          user='005FAKE00000009AAA'):
    return {'ServiceAppointmentId': sa_id, 'Field': field, 'OldValue': old, 'NewValue': new,
            'CreatedDate': ts, 'CreatedById': user, 'CreatedBy': {'Name': actor, 'Profile': {'Name': profile}}}


def tiny_raw() -> dict:
    """A one-garage, 2026-09-28 raw bundle: two drivers, one bounced call, one carryover, one drop-off."""
    sa1 = '08pFAKE00000001AAA'
    member = lambda d, name, user: {'ServiceResourceId': d, 'TerritoryType': 'P', 'Latitude': 43.0, 'Longitude': -78.8,
                                    'ServiceResource': {'Name': name, 'ERS_Driver_Type__c': 'Fleet Driver',
                                                        'RelatedRecordId': user}}
    gps = lambda d, ts, lat, lon: [
        {'ServiceResourceId': d, 'Field': 'LastKnownLatitude', 'NewValue': str(lat), 'CreatedDate': ts},
        {'ServiceResourceId': d, 'Field': 'LastKnownLongitude', 'NewValue': str(lon), 'CreatedDate': ts}]
    sa = lambda i, created, wt, status, ast=None: {
        'Id': i, 'AppointmentNumber': 'SA-' + i[-6:], 'Status': status, 'CreatedDate': created,
        'ActualStartTime': ast, 'ActualEndTime': None, 'WorkType': {'Name': wt}, 'ParentRecordId': '1WLFAKE' + i[-6:],
        'ERS_PTA__c': 120 if i == sa1 else 60,
        'ERS_PTA_Due__c': '2026-09-28T18:00:00.000+0000' if i == sa1 else '2026-09-28T17:00:00.000+0000',
        'Latitude': 43.0, 'Longitude': -78.8}
    return {
        'territory_id': '0HhFAKE00000001AAA', 'service_date': '2026-09-28',
        'window': {'day_start': '2026-09-28T04:00:00Z', 'day_end': '2026-09-29T04:00:00Z',
                   'carryover_from': '2026-09-27T22:00:00Z'},
        'territory': {'Name': '999 - TEST FLEET', 'RSO_Automation_Active__c': True, 'ERS_Auto_Schedule__c': True},
        'sa_count_expected': 4,
        'sas': [sa(sa1, '2026-09-28T16:00:00.000+0000', 'Tire', 'Completed', '2026-09-28T16:40:00.000+0000'),
                sa('08pFAKE00000002AAA', '2026-09-27T23:00:00.000+0000', 'Battery', 'Completed'),
                sa('08pFAKE00000003AAA', '2026-09-27T23:30:00.000+0000', 'Battery', 'Dispatched'),
                sa('08pFAKE00000004AAA', '2026-09-28T16:00:00.000+0000', 'Tow Drop-Off', 'Completed')],
        'history': [
            _hist(sa1, 'ERS_Assigned_Resource__c', '2026-09-28T16:00:30.000+0000', 'Driver Two'),
            _hist(sa1, 'ERS_Assigned_Resource__c', '2026-09-28T16:00:30.000+0000', D2),
            _hist(sa1, 'Status', '2026-09-28T16:01:00.000+0000', 'Dispatched'),
            _hist(sa1, 'Status', '2026-09-28T16:03:00.000+0000', 'Spotted', actor='Dispatcher One', profile='Membership User'),
            _hist(sa1, 'ERS_Assigned_Resource__c', '2026-09-28T16:04:00.000+0000', 'Driver One', 'Driver Two',
                  actor='Dispatcher One', profile='Membership User'),
            _hist(sa1, 'Status', '2026-09-28T16:05:00.000+0000', 'Dispatched', actor='Dispatcher One', profile='Membership User'),
            _hist(sa1, 'Status', '2026-09-28T16:10:00.000+0000', 'En Route', actor='Driver One', profile='Membership User',
                  user='005FAKE00000001AAA'),
            _hist(sa1, 'Status', '2026-09-28T16:40:00.000+0000', 'On Location', actor='Driver One', profile='Membership User',
                  user='005FAKE00000001AAA'),
            _hist(sa1, 'Status', '2026-09-28T17:10:00.000+0000', 'Completed', actor='Driver One', profile='Membership User',
                  user='005FAKE00000001AAA'),
            _hist('08pFAKE00000002AAA', 'Status', '2026-09-28T01:00:00.000+0000', 'Completed'),
            # PTA written twice at creation (90 -> 60, same second), then re-based to 120 by Towbook at +15 s.
            _hist(sa1, 'ERS_PTA__c', '2026-09-28T16:00:00.000+0000', '90'),
            _hist(sa1, 'ERS_PTA__c', '2026-09-28T16:00:00.000+0000', '60', '90'),
            _hist(sa1, 'ERS_PTA__c', '2026-09-28T16:00:15.000+0000', '120', '60', actor='Integrations Towbook',
                  profile='Towbook Integrations'),
        ],
        'assigned': [{'ServiceAppointmentId': sa1, 'ServiceResourceId': D1, 'CreatedDate': '2026-09-28T16:00:30.000+0000',
                      'ServiceResource': {'Name': 'Driver One', 'ERS_Driver_Type__c': 'Fleet Driver'},
                      'CreatedBy': {'Name': 'Mulesoft Integration'}}],
        'woli_skills': [{'RelatedRecordId': '1WLFAKE' + sa1[-6:], 'Skill': {'MasterLabel': 'Tire'}}],
        'members': [member(D1, 'Driver One', '005FAKE00000001AAA'), member(D2, 'Driver Two', '005FAKE00000002AAA')],
        'asset_history': [
            {'AssetId': '02iFAKE00000001AAA', 'OldValue': None, 'NewValue': D1, 'CreatedDate': '2026-09-28T12:00:00.000+0000'},
            {'AssetId': '02iFAKE00000001AAA', 'OldValue': D1, 'NewValue': None, 'CreatedDate': '2026-09-28T20:00:00.000+0000'},
            {'AssetId': '02iFAKE00000002AAA', 'OldValue': None, 'NewValue': D2, 'CreatedDate': '2026-09-28T12:00:00.000+0000'},
        ],
        'assets': [{'Id': '02iFAKE00000001AAA', 'Name': 'Truck 1', 'ERS_Truck_Capabilities__c': 'Tire;Lockout'},
                   {'Id': '02iFAKE00000002AAA', 'Name': 'Truck 2', 'ERS_Truck_Capabilities__c': 'Battery Service'}],
        'absences': [], 'skills': [],
        'gps': gps(D1, '2026-09-28T15:59:00.000+0000', 43.02, -78.8) + gps(D2, '2026-09-28T15:00:00.000+0000', 43.0, -78.8),
        'opt_requests': [], 'policies': [], 'sf_calls': 14, 'build_ms': 1000,
    }
