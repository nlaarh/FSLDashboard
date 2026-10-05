import json, os, sys, statistics as st, math
from collections import Counter, defaultdict
from datetime import timedelta
sys.path.insert(0,'.')
import report_card_verdicts as V, report_card_metrics as M
from utils import parse_dt, haversine
snap=json.load(open(os.path.expanduser(sys.argv[1] if len(sys.argv)>1 else '~/.fslapp/report_card/0HhPb00000007qGKAQ_2026-09-28.snapshot.json')))
r=V.rules_for('r1'); vs=V.score_snapshot(snap,r); rows=M.driver_day(snap,vs,r)
feat={s['id']:V.sa_features(s,r) for s in snap['sas']}
d0=parse_dt(snap['window']['day_start_utc']); d1=parse_dt(snap['window']['day_end_utc'])
mins=[d0+timedelta(minutes=i) for i in range(int((d1-d0).total_seconds()//60))]
# waiting calls (B7): created <= t < t_er (or t_end), waited >= 10 min, graded channel, not drop-off
wait=[]
for s in snap['sas']:
    if s['is_drop_off'] or s['channel'] not in V.GRADED_CHANNELS or s['lat'] is None: continue
    m=s['milestones']; c=parse_dt(s['created']); e=parse_dt(m['t_er']) or parse_dt(m['t_end'])
    if e: wait.append((c+timedelta(minutes=10), e, s['lat'], s['lon']))
drv={d['id']:d for d in snap['drivers']}
def gps_at(d,t):
    best=None
    for ts,la,lo in d['gps']:
        if ts<=t.timestamp()+300: best=(ts,la,lo)
        else: break
    if best and t.timestamp()-best[0]<=1800: return best[1],best[2]
    return None
WT_P90={'Battery':51.5,'Tire':51.5,'Lockout':51.5}  # indicative week p90; build uses 56-day per work type
jph_all=[x['metrics']['M03']['value'] for x in rows if x['metrics']['M03']['value'] and x['member']]
med_jph=st.median(jph_all); med_util=st.median([x['metrics']['M04']['value'] for x in rows if x['member'] and x['on_shift_min']>=60])
print('garage median jobs/h',med_jph,'median util',round(med_util,2))
out=[]
for x in rows:
    if not x['member'] or x['on_shift_min']<60: continue
    d=drv[x['id']]
    on=set(); 
    for a,b in x['on_shift']:
        t=parse_dt(a)
        while t<parse_dt(b): on.add(t); t+=timedelta(minutes=1)
    idle=set()
    for a,b in x['idle']:
        t=parse_dt(a)
        while t<parse_dt(b): idle.add(t); t+=timedelta(minutes=1)
    iw=0; iw15=0
    for t in idle:
        w=[(la,lo) for a,b,la,lo in wait if a<=t<b]
        if not w: continue
        iw+=1
        g=gps_at(d,t)
        if g and any(haversine(g[0],g[1],la,lo)<=15 for la,lo in w): iw15+=1
    mine=[s for s in snap['sas'] if s['final_driver_id']==x['id'] and s['in_day'] and not s['is_drop_off']]
    codes=Counter(vs[s['id']]['code'] for s in mine)
    late_drv=codes['LATE_EXECUTION']; late_sys=sum(codes[k] for k in ('CAPACITY_SHORT','LATE_DESPITE_CAPACITY','STACKED','FAR_PICK'))
    late_bnc=sum(1 for s in mine if vs[s['id']]['code']=='BOUNCED' and feat[s['id']]['pta_met'] is False)
    acc_free=[]; long_scene=0
    for s in mine:
        m=s['milestones']; f=feat[s['id']]
        td,ta=parse_dt(m['t_disp']),parse_dt(m['t_acc']) or parse_dt(m['t_er'])
        if td and ta and f.get('pick_open_jobs')==0: acc_free.append((ta-td).total_seconds()/60)
        to,te=parse_dt(m['t_ol']),parse_dt(m['t_end'])
        if to and te and (te-to).total_seconds()/60>WT_P90.get(s['work_type'],51.5): long_scene+=1
    mm=x['metrics']
    out.append(dict(name=x['name'][:22],osm=x['on_shift_min'],asg=x['assigned'],util=mm['M04']['value'],jph=mm['M03']['value'],
        jph_rel=round(mm['M03']['value']/med_jph,2) if mm['M03']['value'] else None, stk=mm['M07']['value'],stk_share=round(mm['M07']['value']/x['on_shift_min'],2),
        maxopen=mm['M06']['value'], idle_wait=iw, idle_wait15=iw15, pta=f"{mm['M13']['met']}/{mm['M13']['n']}", late_drv=late_drv, late_sys=late_sys, late_bnc=late_bnc,
        acc_free_med=round(st.median(acc_free),1) if acc_free else None, n_acc_free=len(acc_free), long_scene=long_scene, ruby=x['health']))
for o in out: print(o)
json.dump(out,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'health_out.json'),'w'))
