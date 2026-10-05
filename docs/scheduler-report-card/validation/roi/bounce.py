import json,sys,os
sys.path.insert(0,'backend')
from collections import Counter
from utils import parse_dt
S=os.path.dirname(os.path.abspath(__file__))
R=json.load(open(S+'/rows.json'))['rows']
tid=sys.argv[1] if len(sys.argv)>1 else None
R=[r for r in R if not tid or r['tid']==tid]
b=[r for r in R if r['code']=='BOUNCED']
print(len(b),'of',len(R), 'pullbacks>0',sum(1 for r in b if r['pullbacks']), 'reassign_after',sum(1 for r in b if r['reassign_after_dispatch']), 'both', sum(1 for r in b if r['pullbacks'] and r['reassign_after_dispatch']))
print('pta', Counter(r['pta_met'] for r in b), 'late min', round(sum(r['late_min'] or 0 for r in b)))
snaps={}; gaps=[]
for r in b:
    k=(r['tid'],r['date'])
    if k not in snaps: snaps[k]=json.load(open(f"{os.path.expanduser('~')}/.fslapp/report_card/{r['tid']}_{r['date']}.snapshot.json"))
    sa=next(x for x in snaps[k]['sas'] if x['id']==r['id'])
    last=None
    for e in sa['events']:
        if e['field']!='status': continue
        if e['value'] in ('Dispatched','Accepted','En Route'): last=e
        if e['value']=='Spotted' and last:
            gaps.append(((parse_dt(e['ts'])-parse_dt(last['ts'])).total_seconds()/60, last['value'], e['actor'], e['actor_profile']))
            last=None
gs=sorted(g[0] for g in gaps)
if gs:
    print('pullback events',len(gs),'median min',round(gs[len(gs)//2],1),'<=2min',sum(1 for g in gs if g<=2),'>=15min',sum(1 for g in gs if g>=15))
    print(Counter(g[1] for g in gaps), Counter(g[3] for g in gaps), Counter(g[2] for g in gaps).most_common(6))
