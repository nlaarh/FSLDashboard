"""r2 = r1 with pta_basis 'initial' (cs1: last ERS_PTA__c row <= 5 s after creation; basis = spotting time).
Scores every sampled garage-day under r1 and r2; also pull-back actors (decision=True) and S6 battery baseline."""
import copy, json, os, sys
from collections import Counter, defaultdict
from datetime import timedelta
sys.path.insert(0, 'backend')
from report_card_store import load_snapshot
from report_card_verdicts import rules_for, score_snapshot, actor_class
from utils import parse_dt
S = os.path.dirname(os.path.abspath(__file__))
PLAN = json.load(open(S + '/rows.json'))['days']
R1 = rules_for('r1')

def initial_pta(sa, rows):
    c = parse_dt(sa['created'])
    early = sorted((h for h in rows if parse_dt(h['CreatedDate']) <= c + timedelta(seconds=5)), key=lambda h: h['CreatedDate'])
    if not early:
        return sa['pta_min'], 'no_history'
    # same-second rows: follow the Old->New chain to its end
    cur = None
    for _ in early:
        nxt = next((h for h in early if (h['OldValue'] in (None, '') if cur is None else h['OldValue'] == cur)), None)
        if nxt is None or nxt['NewValue'] == cur:
            break
        cur = nxt['NewValue']
        early = [h for h in early if h is not nxt]
    return float(cur), 'history'

tot = Counter(); shifts = Counter(); per = {}; examples = []
pb = defaultdict(Counter); bounced_late = defaultdict(Counter)
s6 = defaultdict(list); s3busy = []
for day in PLAN:
    tid, d = day['tid'], day['date']
    snap = load_snapshot(tid, d)
    hist = defaultdict(list)
    for h in json.load(open(f'{S}/pta_{tid}_{d}.json')):
        hist[h['ServiceAppointmentId']].append(h)
    v1 = score_snapshot(snap, R1)
    s2 = copy.deepcopy(snap)
    src = Counter()
    for sa in s2['sas']:
        if sa['id'] not in v1 or not sa['pta_due'] or not sa['pta_min']:
            continue
        p0, how = initial_pta(sa, hist.get(sa['id'], []))
        src[how] += 1
        basis = parse_dt(sa['pta_due']) - timedelta(minutes=sa['pta_min'])     # = ERS_Spotting_Datetime__c
        sa['pta_due'] = (basis + timedelta(minutes=p0)).isoformat().replace('+00:00', 'Z')
        sa['pta_min'] = p0
    v2 = score_snapshot(s2, R1)
    met = lambda v: (sum(1 for x in v.values() if x['evidence']['pta_met'] is True), sum(1 for x in v.values() if x['evidence']['pta_met'] is not None))
    per[(tid, d)] = (met(v1), met(v2), src)
    for k in v1:
        a, b = v1[k]['code'], v2[k]['code']
        tot[tid] += 1
        if a != b:
            shifts[(tid, a, b)] += 1
            examples.append((d, next(x['number'] for x in snap['sas'] if x['id'] == k), a, b))
    # pull-back actor (decision=True so garage-portal users on the roster read GARAGE_DISPATCHER)
    for sa in snap['sas']:
        if sa['id'] not in v1:
            continue
        seen_disp, first = False, None
        for e in sa['events']:
            if e['field'] == 'status' and e['value'] in ('Dispatched', 'Accepted', 'En Route'):
                seen_disp = True
            elif e['field'] == 'status' and e['value'] == 'Spotted' and seen_disp:
                cls = actor_class(e, R1, decision=True)
                pb[tid][cls] += 1
                first = first or cls
        if v1[sa['id']]['code'] == 'BOUNCED' and v1[sa['id']]['evidence']['pta_met'] is False:
            m = sa['milestones']
            late = (parse_dt(m['arrival']) - parse_dt(sa['pta_due'])).total_seconds() / 60
            bounced_late[tid][first or 'reassign_only'] += late
        m = sa['milestones']
        if tid == '0HhPb00000007qGKAQ' and m['t_ol'] and m['end_status'] == 'Completed':
            s6[sa['call_class']].append((parse_dt(m['t_end']) - parse_dt(m['t_ol'])).total_seconds() / 60)

def pct(xs, q):
    xs = sorted(xs); return round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)
for (tid, d), (m1, m2, src) in sorted(per.items()):
    print(tid[-4:], d, 'r1', m1, 'r2', m2, dict(src))
print('codes scored', dict(tot)); print('shifts', dict(shifts)); print(examples)
print('pullback actors', {k: dict(v) for k, v in pb.items()})
print('bounced late min by first pullback actor', {k: {a: round(b) for a, b in v.items()} for k, v in bounced_late.items()})
for k, xs in s6.items():
    print('WNY S6', k, 'n', len(xs), 'p50', pct(xs, .5), 'p75', pct(xs, .75), 'p90', pct(xs, .9), 'p95', pct(xs, .95))
