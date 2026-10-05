import json, os, sys
from collections import defaultdict
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
        if ts<=t.timestamp()+300: best=(la,lo)
        else: break
    return best if best and any(t.timestamp()-ts<=1800 and ts<=t.timestamp()+300 for ts,_,_ in d['gps']) else None
def caps(d,t):
    for x in d['trucks']:
        if parse_dt(x['start'])<=t<parse_dt(x['end']): return set(x['truck_caps'])
    return set()
def qual(d,req,t): return set(req)<=(set(d['skills'])|caps(d,t))
def on(d,t):
    return any(parse_dt(x['start'])<=t<parse_dt(x['end']) for x in d['logins']) and not any(parse_dt(x['start'])<=t<parse_dt(x['end']) for x in d['absences'])
jobs=defaultdict(list)
for s in snap['sas']:
    if s['busy'] and s['final_driver_id'] and not s['is_drop_off']: jobs[s['final_driver_id']].append(s)
def nopen(did,t): return sum(1 for s in jobs[did] if parse_dt(s['busy'][0])<=t<parse_dt(s['busy'][1]))
members=[x['id'] for x in rows if x['member'] and x['on_shift_min']>=60]
for x in rows:
    if x['id'] not in members: continue
    stk=0; avoid=0
    for a,b in x['stacked']:
        t=parse_dt(a)
        while t<parse_dt(b):
            stk+=1
            queued=[s for s in jobs[x['id']] if parse_dt(s['milestones']['t_asg']) and parse_dt(s['milestones']['t_asg'])<=t and (not parse_dt(s['milestones']['t_er']) or t<parse_dt(s['milestones']['t_er'])) and s['lat'] is not None]
            hit=False
            for q in queued:
                for y in members:
                    if y==x['id']: continue
                    dy=drv[y]
                    if not on(dy,t) or nopen(y,t)!=0 or not qual(dy,q['required_skills'],t): continue
                    g=gps_at(dy,t)
                    if g and haversine(g[0],g[1],q['lat'],q['lon'])<=15: hit=True; break
                if hit: break
            avoid+=hit
            t+=timedelta(minutes=1)
    print(f"{x['name'][:22]:22s} stacked={stk:4d} avoidable={avoid:4d} share_of_shift={avoid/x['on_shift_min']:.2f}")
