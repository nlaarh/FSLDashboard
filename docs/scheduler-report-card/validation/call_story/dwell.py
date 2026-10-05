import json, sys, statistics
from collections import defaultdict
from datetime import datetime, timedelta
P=lambda s: datetime.fromisoformat(s.replace('+0000','+00:00'))
d=json.load(open(sys.argv[1]))
sa={s['Id']:s for s in d['sas']}
st=defaultdict(list); terr=defaultdict(list)
for h in d['hist']:
    if h['Field']=='Status' and h['NewValue']: st[h['ServiceAppointmentId']].append((P(h['CreatedDate']),h['NewValue']))
    if h['Field']=='ServiceTerritory' and h['NewValue'] and not h['NewValue'].startswith('0Hh'): terr[h['ServiceAppointmentId']].append((P(h['CreatedDate']),h['OldValue'],h['NewValue']))
TERM={'Completed','Canceled','Cancel Call - Service Not En Route','Cancel Call - Service En Route','Unable to Complete','No-Show'}
dwell=defaultdict(list)     # status -> total minutes per SA (SAs that entered it)
first=defaultdict(list)
hourly=defaultdict(lambda: defaultdict(list))
for sid,rows in st.items():
    rows.sort()
    tot=defaultdict(float)
    for i,(t,s) in enumerate(rows):
        if s in TERM: break
        nxt=rows[i+1][0] if i+1<len(rows) else None
        if nxt: tot[s]+=(nxt-t).total_seconds()/60
    for s,m in tot.items(): dwell[s].append(m)
    fo={}
    for t,s in rows:
        fo.setdefault(s,t)
    c=P(sa[sid]['CreatedDate'])
    hr=(c-timedelta(hours=4)).hour
    def seg(name,a,b):
        if a and b and b>=a:
            v=(b-a).total_seconds()/60; first[name].append(v); hourly[name][hr//4*4].append(v)
    asg=fo.get('Assigned'); disp=fo.get('Dispatched'); acc=fo.get('Accepted'); er=fo.get('En Route'); ol=fo.get('On Location'); cp=fo.get('Completed')
    seg('created->first Assigned',c,asg)
    seg('Assigned->Dispatched (first)',asg,disp)
    seg('Dispatched->Accepted (first)',disp,acc or er)
    seg('Accepted->En Route',acc,er)
    seg('En Route->On Location',er,ol)
    seg('On Location->Completed',ol,cp)
    seg('created->On Location',c,ol)
def pct(v,p):
    v=sorted(v); k=(len(v)-1)*p; f=int(k); return v[f]+(v[min(f+1,len(v)-1)]-v[f])*(k-f)
print('n SAs', len(st))
print(f"{'segment':34s} {'n':>4s} {'p50':>6s} {'p75':>6s} {'p90':>6s} {'p95':>6s} {'max':>6s}")
for k,v in list(first.items())+[('DWELL '+s,v) for s,v in sorted(dwell.items(), key=lambda kv:-len(kv[1]))]:
    if len(v)<5: continue
    print(f"{k:34s} {len(v):4d} {pct(v,.5):6.1f} {pct(v,.75):6.1f} {pct(v,.9):6.1f} {pct(v,.95):6.1f} {max(v):6.1f}")
if len(sys.argv)>2:
    for k in ['created->first Assigned','Dispatched->Accepted (first)','En Route->On Location']:
        print(k, {h:(len(v), round(pct(v,.5),1), round(pct(v,.9),1)) for h,v in sorted(hourly[k].items()) if len(v)>=10})
# territory moves
mv=[(sid,x) for sid,r in terr.items() for x in r if x[1]]
print('real territory moves', len(mv), 'SAs', len({m[0] for m in mv}))
from collections import Counter
print(Counter((m[1][1][:20],m[1][2][:20]) for m in mv).most_common(8))
