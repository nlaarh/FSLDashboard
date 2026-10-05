import json, os, sys
from collections import defaultdict, Counter
from datetime import timedelta
sys.path.insert(0,'.')
import report_card_verdicts as V, report_card_metrics as M
from utils import parse_dt, haversine
snap=json.load(open(os.path.expanduser('~/.fslapp/report_card/0HhPb00000007qGKAQ_2026-09-28.snapshot.json')))
r=V.rules_for('r1'); vs=V.score_snapshot(snap,r); rows=M.driver_day(snap,vs,r)
drv={d['id']:d for d in snap['drivers']}
def gps_at(d,t):
    best=None
    for ts,la,lo in d['gps']:
        if ts<=t.timestamp()+300: best=(ts,la,lo)
        else: break
    return (best[1],best[2]) if best and t.timestamp()-best[0]<=1800 else None
def caps(d,t):
    for x in d['trucks']:
        if parse_dt(x['start'])<=t<parse_dt(x['end']): return set(x['truck_caps'])
    return set()
qual=lambda d,req,t: set(req)<=(set(d['skills'])|caps(d,t))
wait=[]
for s in snap['sas']:
    if s['is_drop_off'] or s['channel'] not in V.GRADED_CHANNELS or s['lat'] is None: continue
    m=s['milestones']; c=parse_dt(s['created']); e=parse_dt(m['t_er']) or parse_dt(m['t_end'])
    tin=[parse_dt(x['ts']) for x in s['events'] if x['field']=='territory']
    start=max(c+timedelta(minutes=10), max(tin) if tin else c)
    if e and start<e: wait.append((start,e,s))
# pullbacks: status->Spotted after dispatched, attribute to driver assigned just before
pb=Counter(); pb_free=Counter()
for s in snap['sas']:
    cur=None; disp_t=None; st_prev=None
    for e in s['events']:
        if e['field']=='assigned' and e.get('driver_id'): cur=e.get('driver_id')
        if e['field']=='status':
            if e['value']=='Dispatched': disp_t=parse_dt(e['ts'])
            if e['value']=='Spotted' and st_prev in ('Dispatched','Accepted','En Route') and cur:
                pb[cur]+=1
                if st_prev=='Dispatched': pb_free[cur]+=1   # pulled before the driver accepted
            st_prev=e['value']
for x in rows:
    if not x['member'] or x['on_shift_min']<60: continue
    d=drv[x['id']]; iw=0
    for a,b in x['idle']:
        t=parse_dt(a)
        while t<parse_dt(b):
            g=gps_at(d,t)
            if g and any(a0<=t<b0 and qual(d,s['required_skills'],t) and haversine(g[0],g[1],s['lat'],s['lon'])<=15 for a0,b0,s in wait): iw+=1
            t+=timedelta(minutes=1)
    print(f"{x['name'][:22]:22s} idle_wait_q15_ingarage={iw:4d} ({iw/x['on_shift_min']:.2f})  pulled_from={pb[x['id']]} pulled_before_accept={pb_free[x['id']]}")
