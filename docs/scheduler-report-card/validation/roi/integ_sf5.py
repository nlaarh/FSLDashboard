import json, sys, time, re
from collections import Counter
sys.path.insert(0, 'backend')
import sf_client as s
from utils import parse_dt
U = {u['Name']: u['Id'] for u in json.load(open(sys.argv[1] + '/integ_users.json'))['users']}
inv = {v: k for k, v in U.items()}
try:
    r = s.sf_rest_get('/services/data/v65.0/tooling/query', params={'q': "SELECT FIELDS(ALL) FROM PlatformEventSubscriberConfig LIMIT 50"})['records']
    for x in r: print('PE config', x.get('DeveloperName'), {k: inv.get(v, v) for k, v in x.items() if k not in ('attributes',) and ('User' in k or 'Consumer' in k)})
    if not r: print('PE config: none')
except Exception as e: print('PE config ERR', str(e)[:150])
time.sleep(0.5)
jobs = s.sf_query_all("SELECT CreatedById, CreatedBy.Name, CreatedDate, CompletedDate FROM AsyncApexJob WHERE ApexClass.Name = 'BatchScheduleServiceAppointments' AND JobType = 'BatchApex' AND CreatedDate = LAST_N_DAYS:2")
print('FSL auto-schedule batch jobs by submitter (2 days):', Counter(j['CreatedBy']['Name'] for j in jobs))
win = [(parse_dt(j['CreatedDate']).timestamp(), parse_dt(j['CompletedDate'] or j['CreatedDate']).timestamp(), j['CreatedBy']['Name']) for j in jobs]
time.sleep(0.5)
ID = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')
hist = s.sf_query_all(f"SELECT NewValue, CreatedDate FROM ServiceAppointmentHistory WHERE Field = 'ERS_Assigned_Resource__c' AND CreatedById = '{U['IT System User']}' AND CreatedDate = LAST_N_DAYS:2")
drv = [h for h in hist if h['NewValue'] and not ID.match(h['NewValue']) and not h['NewValue'].lower().startswith('towbook') and 'spot' not in h['NewValue'].lower()]
c = Counter()
for h in drv:
    t = parse_dt(h['CreatedDate']).timestamp()
    who = [w for a, b, w in win if a - 3 <= t <= b + 3]
    c[who[0] if who else 'no FSL batch running'] += 1
print('IT System User driver picks by FSL batch running at that moment:', dict(c))
