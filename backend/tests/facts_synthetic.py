"""Seeded fake Salesforce rows for the daily-facts tests: appointments, history, assignments, surveys.
The same rows are fed to today's Salesforce code paths (through a fake sf_query_all) and to the facts builder."""

import random
from datetime import datetime, timedelta, timezone

DAYS = ('2026-10-05', '2026-10-06', '2026-10-07')
GARAGES = [
    ('0Hh000000000001AAA', 'Alpha Towing 001D'),
    ('0Hh000000000002AAA', '100 - Fleet Buffalo'),
    ('0Hh000000000003AAA', 'Bravo Garage 076DO'),
    ('0Hh000000000004AAA', 'Cascade Auto 002D'),
    ('0Hh000000000005AAA', 'Main Office'),         # not a garage for the trends ranking
    ('0Hh000000000006AAA', 'WR006'),                # grid zone
]
STATUSES = ['Completed'] * 70 +['Canceled', 'Dispatched', 'Assigned', 'No-Show', 'Unable to Complete', 'None', 'Scheduled',
                                'Cancel Call - Service En Route', 'In Progress', 'Cannot Complete']
METHODS = ['Field Services', 'Towbook', '', 'Field Services', 'Towbook']
WORK_TYPES = ['Tow', 'Battery', 'Light Service', 'Tow Drop-Off', 'Winch']


def stamp(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%S.000+0000')


def make(seed: int = 7, per_garage: int = 26):
    rnd = random.Random(seed)
    sas, history, assign, reassign, surveys = [], [], [], [], []
    n = 0
    for day in DAYS:
        d0 = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        for tid, name in GARAGES:
            for _ in range(per_garage if name != 'Cascade Auto 002D' else 5):
                n += 1
                sid = f'08p{n:015d}'
                created = d0 + timedelta(seconds=rnd.randint(0, 86398))            # never in the last second of a day
                status, dm, wt = rnd.choice(STATUSES), rnd.choice(METHODS), rnd.choice(WORK_TYPES)
                start = created + timedelta(minutes=rnd.choice([-5, 0, 3, 12, 25, 44, 46, 70, 130, 500, 29, 61]))
                pta = rnd.choice([None, 0, 999, 30, 45, 60, 90, 120, 15, 200])
                sa = {'Id': sid, 'ServiceTerritoryId': tid, 'ServiceTerritory': {'Name': name}, 'Status': status,
                      'CreatedDate': stamp(created), 'ActualStartTime': stamp(start) if rnd.random() > 0.15 else None,
                      'ERS_PTA__c': pta, 'ERS_Dispatch_Method__c': dm or None,
                      'ERS_Facility_Decline_Reason__c': rnd.choice([None, None, None, 'Too busy']), 'WorkType': {'Name': wt}}
                sas.append(sa)
                if dm == 'Towbook' and rnd.random() > 0.2:
                    on = created + timedelta(minutes=rnd.choice([10, 20, 33, 47, 90, 600, -2]))
                    history.append({'ServiceAppointmentId': sid, 'Field': 'Status', 'OldValue': 'Dispatched', 'NewValue': 'On Location', 'CreatedDate': stamp(on)})
                    if rnd.random() > 0.7:                                         # a later duplicate: the earliest must win
                        history.append({'ServiceAppointmentId': sid, 'Field': 'Status', 'OldValue': 'X', 'NewValue': 'On Location', 'CreatedDate': stamp(on + timedelta(minutes=9))})
                if rnd.random() > 0.6:                                             # cascade: first call went to another garage
                    other = rnd.choice([g for g in GARAGES if g[0] != tid])[0]
                    history.append({'ServiceAppointmentId': sid, 'Field': 'ServiceTerritory', 'OldValue': None, 'NewValue': other, 'CreatedDate': stamp(created)})
                    history.append({'ServiceAppointmentId': sid, 'Field': 'ServiceTerritory', 'OldValue': other, 'NewValue': tid, 'CreatedDate': stamp(created + timedelta(minutes=2))})
                elif rnd.random() > 0.5:
                    history.append({'ServiceAppointmentId': sid, 'Field': 'ServiceTerritory', 'OldValue': None, 'NewValue': tid, 'CreatedDate': stamp(created)})
                for k in range(rnd.choice([0, 1, 1, 2, 3])):                       # k assignments: a name row and an id row each
                    at = created + timedelta(minutes=2 + 3 * k)
                    who = rnd.choice(['Membership User', 'Contact Center', 'System Administrator'])
                    for new in (f'Driver {k} {name[:3]}', f'0Hn{n:06d}{k:09d}'):
                        row = {'ServiceAppointmentId': sid, 'CreatedDate': stamp(at), 'NewValue': new,
                               'CreatedBy': {'Name': 'x', 'Profile': {'Name': who}}}
                        assign.append(row)
                        reassign.append(row)
    for day in DAYS:
        for tid, _ in GARAGES[:3]:
            for _ in range(5):
                surveys.append({'ERS_Work_Order__r': {'ServiceTerritoryId': tid}, 'ERS_Overall_Satisfaction__c': rnd.choice(['Totally Satisfied', 'Satisfied', 'totally satisfied']),
                                'ERS_Response_Time_Satisfaction__c': rnd.choice(['Totally Satisfied', 'Dissatisfied']),
                                'ERS_Technician_Satisfaction__c': rnd.choice(['Totally Satisfied', 'Satisfied', 'Totally Satisfied']),
                                'ERSSatisfaction_With_Being_Kept_Informed__c': rnd.choice(['Totally Satisfied', None])})
    return {'sas': sas, 'history': history, 'assign': assign, 'reassign': reassign, 'surveys': surveys}
