import json, sys, time, re
from bisect import bisect_right
from collections import Counter
sys.path.insert(0, 'backend')
import sf_client as s
from utils import parse_dt
U = {u['Name']: u['Id'] for u in json.load(open(sys.argv[1] + '/integ_users.json'))['users']}
ID = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')
for name in ('IT System User', 'Mulesoft Integration', 'Replicant Integration User'):
    uid = U[name]
    jobs = s.sf_query_all(f"SELECT CreatedDate, CompletedDate FROM AsyncApexJob WHERE CreatedById = '{uid}' AND ApexClass.Name = 'BatchScheduleServiceAppointments' AND JobType = 'BatchApex' AND CreatedDate = LAST_N_DAYS:2")
    time.sleep(0.5)
    n_exp = s.sf_query(f"SELECT COUNT() FROM ServiceAppointmentHistory WHERE Field = 'ERS_Assigned_Resource__c' AND CreatedById = '{uid}' AND CreatedDate = LAST_N_DAYS:2")['totalSize']
    time.sleep(0.5)
    hist = s.sf_query_all(f"SELECT ServiceAppointmentId, NewValue, CreatedDate, ServiceAppointment.CreatedDate, ServiceAppointment.Auto_Schedule_Requested__c, ServiceAppointment.ServiceTerritory.Name FROM ServiceAppointmentHistory WHERE Field = 'ERS_Assigned_Resource__c' AND CreatedById = '{uid}' AND CreatedDate = LAST_N_DAYS:2")
    time.sleep(0.5)
    assert len(hist) == n_exp, (n_exp, len(hist))
    picks = [h for h in hist if h['NewValue'] and not ID.match(h['NewValue'])]
    win = sorted((parse_dt(j['CreatedDate']).timestamp(), parse_dt(j['CompletedDate'] or j['CreatedDate']).timestamp()) for j in jobs)
    starts = [a for a, b in win]
    def inside(t, slack=3):
        i = bisect_right(starts, t + slack) - 1
        return any(a - slack <= t <= b + slack for a, b in win[max(0, i - 5):i + 1])
    hit = sum(1 for p in picks if inside(parse_dt(p['CreatedDate']).timestamp()))
    # placebo: same picks shifted by 10 min (how often a random moment falls inside a job window)
    plc = sum(1 for p in picks if inside(parse_dt(p['CreatedDate']).timestamp() - 600))
    req = sum(1 for p in picks if (p.get('ServiceAppointment') or {}).get('Auto_Schedule_Requested__c'))
    terr = Counter((p.get('ServiceAppointment') or {}).get('ServiceTerritory', {}) and p['ServiceAppointment']['ServiceTerritory']['Name'] for p in picks).most_common(4)
    tb = lambda p: (p['NewValue'] or '').lower().startswith('towbook') or 'spot' in (p['NewValue'] or '').lower()
    on = [p for p in picks if not tb(p)]
    on_hit = sum(1 for p in on if inside(parse_dt(p['CreatedDate']).timestamp()))
    on_req = sum(1 for p in on if (p.get('ServiceAppointment') or {}).get('Auto_Schedule_Requested__c'))
    miss = [p for p in on if not inside(parse_dt(p['CreatedDate']).timestamp())]
    gap = sorted((parse_dt(p['CreatedDate']) - parse_dt(p['ServiceAppointment']['CreatedDate'])).total_seconds() for p in miss)
    print(f"   {name}: Towbook/SPOT placeholder picks {len(picks)-len(on)} | driver picks {len(on)}, inside FSL batch {on_hit} ({100*on_hit/max(1,len(on)):.0f}%), with request stamp {on_req} | driver picks outside: {len(miss)}, created->pick s p50 {gap[len(gap)//2] if gap else None} | examples {[ (p['ServiceAppointmentId'], p['NewValue'], p['CreatedDate']) for p in miss[:3]]}")
    print(f"{name}: FSL batch jobs {len(jobs)} | assignment picks {len(picks)} | inside an FSL auto-schedule batch run (+-3 s): {hit} ({100*hit/max(1,len(picks)):.0f}%) | placebo -10 min: {plc} ({100*plc/max(1,len(picks)):.0f}%) | SA has Auto_Schedule_Requested__c: {req} | top garages {terr}")
