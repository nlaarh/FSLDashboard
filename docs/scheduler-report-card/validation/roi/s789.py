import json,os,sys
from collections import defaultdict
sys.path.insert(0,'backend')
from report_card_store import load_snapshot
from utils import parse_dt
S=os.path.dirname(os.path.abspath(__file__))
seg=defaultdict(list)
for day in json.load(open(S+'/rows.json'))['days']:
    snap=load_snapshot(day['tid'],day['date'])
    g='WNY100' if day['tid'].endswith('GKAQ') else '076DO'
    for sa in snap['sas']:
        if not sa['in_day'] or sa['is_drop_off']: continue
        ev=sa['events']
        st=[e for e in ev if e['field']=='status']
        for i,e in enumerate(st):
            if e['value'] in ('Rejected','Declined'):
                nxt=next((x for x in st[i+1:] if x['value'] in ('Spotted','Assigned','Dispatched')),None)
                if nxt: seg[(g,sa['channel'],'S7')].append((parse_dt(nxt['ts'])-parse_dt(e['ts'])).total_seconds()/60)
        te=[e for e in ev if e['field']=='territory']
        for i,e in enumerate(te):
            if 'SPOT' in (e.get('to') or '').upper():
                nxt=next((x for x in te[i+1:]),None)
                if nxt: seg[(g,sa['channel'],'S8')].append((parse_dt(nxt['ts'])-parse_dt(e['ts'])).total_seconds()/60)
def q(xs,p): xs=sorted(xs); return round(xs[min(len(xs)-1,int(p*len(xs)))],1)
allc=defaultdict(list)
for k,xs in sorted(seg.items()):
    allc[k[2]]+=xs
    print(k,'n',len(xs),'p50',q(xs,.5),'p75',q(xs,.75),'p90',q(xs,.9),'p95',q(xs,.95))
for k,xs in allc.items(): print('POOLED',k,'n',len(xs),'p50',q(xs,.5),'p75',q(xs,.75),'p90',q(xs,.9),'p95',q(xs,.95))
