import json, sys, time
from collections import Counter
sys.path.insert(0, 'backend')
import sf_client as s
from report_card_store import load_snapshot
from report_card_verdicts import rules_for, score_snapshot
from utils import parse_dt
R = rules_for('r1')
for tid, day in (('0HhPb00000007s3KAA', '2026-08-31'), ('0HhPb00000007qGKAQ', '2026-09-28')):
    snap = load_snapshot(tid, day); v = score_snapshot(snap, R)
    ids = sorted(v); req = {}
    for i in range(0, len(ids), 150):
        time.sleep(0.4)
        for r in s.sf_query_all("SELECT Id, Auto_Schedule_Requested__c FROM ServiceAppointment WHERE Id IN (" + ",".join(f"'{x}'" for x in ids[i:i+150]) + ")"):
            req[r['Id']] = r['Auto_Schedule_Requested__c']
    sas = {x['id']: x for x in snap['sas']}
    c = Counter(); graded = 0
    for k, vv in v.items():
        f = vv['evidence']
        if 'BYPASSED_OPTIMIZER' not in vv['flags']: continue
        if f['final_actor_class'] == 'INTEGRATION':
            fin = parse_dt(sas[k]['decision']['final']['ts']); rq = parse_dt(req.get(k))
            mech = 'FSL auto-schedule (pick 0-60 s after Auto_Schedule_Requested__c)' if rq and 0 <= (fin - rq).total_seconds() <= 60 else 'no auto-schedule stamp before pick'
            c[('INTEGRATION', f['final_actor'], mech)] += 1
        else:
            c[(f['final_actor_class'],)] += 1
    print(f"== {day} {snap['territory']['name']}: scored {len(v)}, BYPASSED_OPTIMIZER {sum(c.values())}, graded decisions {sum(1 for x in v.values() if x['evidence']['graded'])}")
    for k, n in c.most_common(): print('  ', n, k)
