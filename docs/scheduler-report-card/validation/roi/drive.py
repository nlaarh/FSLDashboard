import json,os,sys
sys.path.insert(0,'backend')
from utils import parse_dt
S=os.path.dirname(os.path.abspath(__file__))
R=json.load(open(S+'/rows.json'))['rows']
sf=[r for r in R if r['code'] in ('STACKED','FAR_PICK') and (r['extra_free_mi'] or 0)>0]
sn={}
out=[]
for r in sf:
    k=(r['tid'],r['date'])
    if k not in sn: sn[k]=json.load(open(os.path.expanduser(f"~/.fslapp/report_card/{r['tid']}_{r['date']}.snapshot.json")))
    sa=next(x for x in sn[k]['sas'] if x['id']==r['id'])
    m=sa['milestones']
    drive=(parse_dt(m['t_ol'])-parse_dt(m['t_er'])).total_seconds()/60 if m['t_ol'] and m['t_er'] else None
    c=sa['candidate_sets'][sa['decision_set_idx']]['c']
    me=next(x for x in c if x[0]==sa['final_driver_id'])
    out.append((r['extra_free_mi'],r['pick_mi'],drive,me[7],r['number'],r['code'],r['final_actor_class'],sa['milestones']['end_status']))
out.sort(reverse=True)
for o in out[:12]: print([round(x,1) if isinstance(x,float) else x for x in o])
# implied speed check: pick miles / drive minutes
bad=[o for o in out if o[2] and o[1]>15 and o[1]/(o[2]/60)>70]
print('picks >15mi with implied speed >70 mph (driver did not drive from GPS point):',len(bad),'of',sum(1 for o in out if o[1]>15))
for o in bad: print('  ',[round(x,1) if isinstance(x,float) else x for x in o])
