import json, os, sys, statistics as st
from collections import Counter
sys.path.insert(0, 'backend')
from report_card_store import load_snapshot
from utils import parse_dt
S = os.path.dirname(os.path.abspath(__file__))
R = [x for x in json.load(open(S + '/rows.json'))['rows'] if x['tid'] == '0HhPb00000007qUKAQ' and x['pta_met'] is False and x['code'] == 'LATE_DESPITE_CAPACITY']
snaps = {}; c = Counter(); asg = []; pre = []
for r in R:
    if r['date'] not in snaps: snaps[r['date']] = {x['id']: x for x in load_snapshot(r['tid'], r['date'])['sas']}
    sa = snaps[r['date']][r['id']]
    fin = sa['decision']['final']
    c[(r['final_actor_class'], fin['actor'] if fin else None)] += 1
    m = sa['milestones']
    asg.append((parse_dt(m['t_asg']) - parse_dt(sa['created'])).total_seconds() / 60)
    pre.append(r['pick_open'])
print(c.most_common()); print('created->final assign min median', round(st.median(asg), 1), 'p75', round(sorted(asg)[int(.75*len(asg))], 1), '| pick open jobs', Counter(pre))
