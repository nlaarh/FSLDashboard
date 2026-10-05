import json,os,sys
from collections import defaultdict, Counter
from datetime import timedelta
sys.path.insert(0,'backend')
from report_card_store import load_snapshot
from report_card_verdicts import rules_for, score_snapshot
from utils import parse_dt
S=os.path.dirname(os.path.abspath(__file__))
R1=rules_for('r1')
out=Counter(); who=Counter(); codes=Counter()
for day in json.load(open(S+'/rows.json'))['days']:
    tid,d=day['tid'],day['date']; snap=load_snapshot(tid,d); v=score_snapshot(snap,R1)
    hist=defaultdict(list)
    for h in json.load(open(f'{S}/pta_{tid}_{d}.json')): hist[h['ServiceAppointmentId']].append(h)
    for sa in snap['sas']:
        if sa['id'] not in v: continue
        c=parse_dt(sa['created'])
        late=[h for h in hist.get(sa['id'],[]) if parse_dt(h['CreatedDate'])-c>timedelta(seconds=5)]
        out[(tid[-4:],'scored')]+=1
        if late:
            out[(tid[-4:],'pta_edit_after_5s')]+=1
            for h in late: who[(tid[-4:],h['CreatedBy']['Name'])]+=1
            codes[(tid[-4:],v[sa['id']]['code'],sa['territory_moves']['in']>0)]+=1
print(dict(out)); print(dict(who)); print(dict(codes))
