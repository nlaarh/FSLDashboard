import json, sys, time, re
from bisect import bisect_right
from collections import Counter, defaultdict
sys.path.insert(0, 'backend')
import sf_client as s
from utils import parse_dt
U = {u['Name']: u['Id'] for u in json.load(open(sys.argv[1] + '/integ_users.json'))['users']}
ID = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')
uid = U['IT System User']
jobs = s.sf_query_all(f"SELECT CreatedDate, CompletedDate FROM AsyncApexJob WHERE CreatedById = '{uid}' AND ApexClass.Name = 'BatchScheduleServiceAppointments' AND JobType = 'BatchApex' AND CreatedDate = LAST_N_DAYS:2")
win = [(parse_dt(j['CreatedDate']).timestamp(), parse_dt(j['CompletedDate'] or j['CreatedDate']).timestamp()) for j in jobs]
inside = lambda t: any(a - 3 <= t <= b + 3 for a, b in win)
time.sleep(0.5)
hist = s.sf_query_all(f"SELECT ServiceAppointmentId, NewValue, CreatedDate FROM ServiceAppointmentHistory WHERE Field = 'ERS_Assigned_Resource__c' AND CreatedById = '{uid}' AND CreatedDate = LAST_N_DAYS:2")
isdrv = lambda v: v and not ID.match(v) and not v.lower().startswith('towbook') and 'spot' not in v.lower()
out = [h for h in hist if isdrv(h['NewValue']) and not inside(parse_dt(h['CreatedDate']).timestamp())]
sa_ids = sorted({h['ServiceAppointmentId'] for h in out})
full = []
for i in range(0, len(sa_ids), 150):
    time.sleep(0.5)
    full += s.sf_query_all("SELECT ServiceAppointmentId, Field, OldValue, NewValue, CreatedDate, CreatedBy.Name FROM ServiceAppointmentHistory WHERE ServiceAppointmentId IN (" + ",".join(f"'{x}'" for x in sa_ids[i:i+150]) + ") AND Field IN ('ERS_Assigned_Resource__c','Status','ServiceTerritory')")
by = defaultdict(list)
for h in sorted(full, key=lambda h: h['CreatedDate']): by[h['ServiceAppointmentId']].append(h)
cls = Counter(); prev_actor = Counter(); same_tx = Counter(); ex = defaultdict(list)
for h in out:
    t = parse_dt(h['CreatedDate'])
    rows = by[h['ServiceAppointmentId']]
    before = [r for r in rows if r['Field'] == 'ERS_Assigned_Resource__c' and isdrv(r['NewValue']) and parse_dt(r['CreatedDate']) < t]
    same_moment = [r for r in rows if abs((parse_dt(r['CreatedDate']) - t).total_seconds()) <= 2 and r['Field'] != 'ERS_Assigned_Resource__c']
    if before and before[-1]['NewValue'] == h['NewValue']:
        k = 'same driver as previous pick (re-stamp)'
    elif before:
        k = 'different driver from previous pick'
    else:
        k = 'first driver pick on this SA'
    cls[k] += 1
    if before: prev_actor[(k, before[-1]['CreatedBy']['Name'])] += 1
    for r in same_moment: same_tx[(k, r['Field'], r['NewValue'], r['CreatedBy']['Name'])] += 1
    if len(ex[k]) < 2: ex[k].append((h['ServiceAppointmentId'], h['NewValue'], h['CreatedDate'], [(r['CreatedDate'][11:19], r['Field'], r['NewValue'], r['CreatedBy']['Name']) for r in rows if abs((parse_dt(r['CreatedDate']) - t).total_seconds()) <= 120]))
print('IT System User driver picks outside FSL batch runs:', len(out)); print(dict(cls))
print('previous pick by:', prev_actor.most_common(8))
print('same-moment (<=2 s) other changes:', same_tx.most_common(10))
for k, v in ex.items():
    for e in v: print(' EX', k, e)
