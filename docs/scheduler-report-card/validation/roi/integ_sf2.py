import json, os, sys, time, statistics as st
from collections import Counter, defaultdict
sys.path.insert(0, 'backend')
import sf_client as s
from report_card_store import load_snapshot
from report_card_verdicts import rules_for, actor_class
from utils import parse_dt
S = sys.argv[1]; R = rules_for('r1')
L = '/Users/alaaroubi/Library/CloudStorage/OneDrive-AAAWesternandCentralNewYork/AAA/Dev/FSL/FSL/force-app/main/default/classes/'
for cls in ('ERS_SA_AutoSchedule', 'ERS_SA_AutoScheduleTimingHandler'):
    r = s.sf_rest_get('/services/data/v65.0/tooling/query', params={'q': f"SELECT Name, Status, LastModifiedDate, Body FROM ApexClass WHERE Name = '{cls}' AND NamespacePrefix = null"})['records']
    loc = open(L + cls + '.cls').read()
    norm = lambda x: ''.join(x.split())
    print(cls, 'prod', r[0]['Status'], r[0]['LastModifiedDate'], 'IDENTICAL to local' if norm(r[0]['Body']) == norm(loc) else 'DIFFERS from local'); time.sleep(0.4)
r = s.sf_rest_get('/services/data/v65.0/tooling/query', params={'q': "SELECT Name, NamespacePrefix, Status FROM ApexClass WHERE Name = 'BatchScheduleServiceAppointments'"})['records']
print('BatchScheduleServiceAppointments:', [(x['NamespacePrefix'], x['Status']) for x in r]); time.sleep(0.4)
d = s.sf_rest_get('/services/data/v65.0/sobjects/ServiceAppointment/describe')
print('fields:', [f['name'] for f in d['fields'] if f['name'] in ('FSL__Auto_Schedule__c', 'Auto_Schedule_Requested__c', 'Auto_Schedule_Elapsed_Seconds__c', 'FSL__Scheduling_Policy_Used__c')])
for tid, day in (('0HhPb00000007qGKAQ', '2026-09-28'), ('0HhPb00000007s3KAA', '2026-08-31')):
    snap = load_snapshot(tid, day)
    sas = {x['id']: x for x in snap['sas'] if x['in_day'] and not x['is_drop_off']}
    rows = []
    ids = sorted(sas)
    for i in range(0, len(ids), 150):
        time.sleep(0.4)
        rows += s.sf_query_all("SELECT Id, FSL__Auto_Schedule__c, Auto_Schedule_Requested__c, Auto_Schedule_Elapsed_Seconds__c, CreatedBy.Name FROM ServiceAppointment WHERE Id IN (" + ",".join(f"'{x}'" for x in ids[i:i+150]) + ")")
    c = Counter(); gap = defaultdict(list); el = []
    for r in rows:
        sa = sas[r['Id']]
        picks = [e for e in sa['events'] if e['field'] == 'assigned' and e.get('driver')]
        first = picks[0] if picks else None
        fc = (actor_class(first, R, decision=True) + ':' + first['actor']) if first else 'none'
        req = parse_dt(r['Auto_Schedule_Requested__c'])
        c[(fc, 'requested' if req else 'not_requested')] += 1
        if req and first:
            gap[fc].append((parse_dt(first['ts']) - req).total_seconds())
        if r['Auto_Schedule_Elapsed_Seconds__c'] is not None: el.append(r['Auto_Schedule_Elapsed_Seconds__c'])
    print(f'\n== {day} {snap["territory"]["name"]}: n={len(rows)}')
    for k, v in sorted(c.items(), key=lambda kv: -kv[1]): print('  first pick', k, v)
    for k, v in gap.items():
        v = sorted(v); print(f'  {k}: first pick minus Auto_Schedule_Requested__c, s: p10 {v[len(v)//10]:.0f} p50 {v[len(v)//2]:.0f} p90 {v[int(len(v)*.9)]:.0f} (n {len(v)})')
    if el: print('  Auto_Schedule_Elapsed_Seconds__c: n', len(el), 'median', st.median(el))
