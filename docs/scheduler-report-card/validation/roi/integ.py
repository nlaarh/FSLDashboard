"""Integration accounts: who, when (vs SA creation, vs SF optimizer runs), pick quality, policy stamp. Snapshots only."""
import json, os, sys, statistics as st
from bisect import bisect_right
from collections import Counter, defaultdict
sys.path.insert(0, 'backend')
from report_card_store import load_snapshot
from report_card_verdicts import rules_for, score_snapshot, actor_class, sa_features
from utils import parse_dt
S = os.path.dirname(os.path.abspath(__file__))
R = rules_for('r1')
days = json.load(open(S + '/rows.json'))['days']
only = sys.argv[1:]
agg = defaultdict(lambda: defaultdict(list))
bypass = Counter()
for day in days:
    if only and day['date'] not in only: continue
    snap = load_snapshot(day['tid'], day['date'])
    g = 'WNY' if day['tid'].endswith('GKAQ') else '076DO'
    runs = sorted(parse_dt(r['ts']).timestamp() for r in snap['optimizer_sf']['requests'] if r.get('ts'))
    v = score_snapshot(snap, R)
    drivers = {d['id']: d for d in snap['drivers']}
    for sa in snap['sas']:
        if sa['id'] not in v: continue
        f = v[sa['id']]['evidence']
        if 'BYPASSED_OPTIMIZER' in v[sa['id']]['flags']: bypass[(g, f['final_actor_class'])] += 1
        created = parse_dt(sa['created']).timestamp()
        picks = [e for e in sa['events'] if e['field'] == 'assigned' and e.get('driver')]
        for i, e in enumerate(picks):
            cls = actor_class(e, R, decision=True)
            key = (g, cls if cls != 'INTEGRATION' else 'INT:' + e['actor'], 'first' if i == 0 else 'later')
            t = parse_dt(e['ts']).timestamp()
            j = bisect_right(runs, t) - 1
            agg[key]['since_created_s'].append(t - created)
            agg[key]['since_opt_run_s'].append(t - runs[j] if j >= 0 else None)
            # was this pick the closest qualified / closest free at that moment?
            cs = sa['candidate_sets'][i]['c'] if sa.get('candidate_sets') and i < len(sa['candidate_sets']) else None
            if cs:
                me = next((c for c in cs if c[0] == e.get('driver_id')), None)
                pool = [c for c in cs if c[8] and c[5] and c[4] and c[3] is not None]
                if me and me[3] is not None and pool:
                    best = min(pool + [me], key=lambda c: c[3])
                    agg[key]['closest'].append(best[0] == me[0] or me[3] <= best[3] + 0.01)
                    free = [c for c in pool + [me] if c[6] == 0]
                    if free:
                        agg[key]['closest_free'].append(min(free, key=lambda c: c[3])[0] == me[0])
                    agg[key]['pick_open'].append(me[6])
                    agg[key]['min_open'].append(min(c[6] for c in pool + [me]))
            agg[key]['policy_stamped'].append(bool(sa['decision'].get('scheduling_policy')))
def q(xs, p):
    xs = sorted(x for x in xs if x is not None); return round(xs[int(p * (len(xs) - 1))], 1) if xs else None
print('BYPASSED_OPTIMIZER flag by final actor class:', dict(bypass))
print(f"{'group':55s} n  created->pick s p50/p90 | last SF opt run->pick s p50/p90 | <=60s after run | closest% closestfree% | pick open mean | policy stamped")
for k in sorted(agg, key=lambda k: (k[0], -len(agg[k]['since_created_s']))):
    a = agg[k]; n = len(a['since_created_s'])
    if n < 5: continue
    ro = [x for x in a['since_opt_run_s'] if x is not None]
    pct = lambda xs: f"{100*sum(xs)/len(xs):.0f}%({len(xs)})" if xs else '-'
    print(f"{str(k):55s} {n:4d} {q(a['since_created_s'],.5)}/{q(a['since_created_s'],.9)} | {q(ro,.5)}/{q(ro,.9)} | {pct([x<=60 for x in ro])} | {pct(a['closest'])} {pct(a['closest_free'])} | {(st.mean(a['pick_open']) if a['pick_open'] else 0):.2f} vs min {(st.mean(a['min_open']) if a['min_open'] else 0):.2f} | {pct(a['policy_stamped'])}")
