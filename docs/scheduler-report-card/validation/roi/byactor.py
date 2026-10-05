import json,os
from collections import Counter,defaultdict
S=os.path.dirname(os.path.abspath(__file__))
R=json.load(open(S+'/rows.json'))['rows']
SCHED=('STACKED','FAR_PICK','LATE_DESPITE_CAPACITY')
for g in ('GKAQ','s3KAA'):
    rs=[r for r in R if r['tid'].endswith(g)]
    m=defaultdict(float); n=Counter(); mi=defaultdict(float); calls=Counter()
    for r in rs:
        a=r['final_actor_class']
        calls[a]+=1
        if r['code'] in SCHED and r['pta_met'] is False: m[a]+=r['late_min']; n[a]+=1
        if r['code'] in ('STACKED','FAR_PICK') and (r['extra_free_mi'] or 0)>0: mi[a]+=r['extra_free_mi']
    print(g,'sched misses by final actor',dict(n),'late min',{k:round(v) for k,v in m.items()},'miles',{k:round(v) for k,v in mi.items()},'all calls by actor',dict(calls))
    # failure rate per actor (scheduler codes / calls) with n
    f=Counter(r['final_actor_class'] for r in rs if r['code'] in SCHED)
    print('   sched-code rate by actor', {k: f"{f[k]}/{calls[k]}={f[k]/calls[k]:.1%}" for k in calls if calls[k]>=30})
