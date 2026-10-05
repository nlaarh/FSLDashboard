"""ROI baseline analysis from stored snapshots (no Salesforce). Writes per-SA rows + per-day rows to rows.json."""
import json, os, sys
from collections import Counter, defaultdict
from datetime import timedelta
sys.path.insert(0, 'backend')
from report_card_store import load_snapshot
from report_card_verdicts import rules_for, score_snapshot, actor_class
from report_card_health import _Driver, _waits
from report_card_snapshot import miles
from utils import parse_dt

S = os.path.dirname(os.path.abspath(__file__))
PLAN = {
    '0HhPb00000007qGKAQ': ['2026-09-01', '2026-09-09', '2026-09-11', '2026-09-14', '2026-09-17',
                           '2026-09-22', '2026-09-25', '2026-09-28', '2026-09-12', '2026-09-20'],
    '0HhPb00000007s3KAA': ['2026-08-03', '2026-08-05', '2026-08-07', '2026-08-11', '2026-08-13',
                           '2026-08-19', '2026-08-25', '2026-08-31', '2026-08-08', '2026-08-23'],
}
PLAN['0HhPb00000007rKKAQ'] = ['2026-09-01', '2026-09-09', '2026-09-11', '2026-09-14', '2026-09-17', '2026-09-22', '2026-09-25', '2026-09-28', '2026-09-12', '2026-09-20']
PLAN['0HhPb00000007qUKAQ'] = ['2026-09-01', '2026-09-09', '2026-09-11', '2026-09-14', '2026-09-17', '2026-09-22', '2026-09-25', '2026-09-28', '2026-09-12', '2026-09-20']
ONLY = sys.argv[1:]

R = rules_for('r1')
SCHED = ('STACKED', 'FAR_PICK', 'LATE_DESPITE_CAPACITY')
MEMBER_REASONS = {'Member Found Own Service', 'Member Could Not Wait', 'Passerby Assisted',
                  'Member got themselves going', 'IVR Cancellation'}
CANCEL_ST = ('Cancel Call - Service Not En Route', 'Cancel Call - Service En Route', 'Canceled')
REACH, AGE, RUN_MIN = 15, 30, 10


def orig_pta(sa, hist):
    """Promise made at creation: follow the ERS_PTA__c chain written within 5 s of creation (cs1)."""
    created = parse_dt(sa['created'])
    rows = sorted((h for h in hist if parse_dt(h['CreatedDate']) <= created + timedelta(seconds=5)),
                  key=lambda h: h['CreatedDate'])
    later = [h for h in hist if parse_dt(h['CreatedDate']) > created + timedelta(seconds=5)]
    if not rows:
        return sa['pta_min'], later
    cur, seen = None, set()
    for _ in range(len(rows)):
        nxt = next((h for h in rows if id(h) not in seen and (h['OldValue'] == cur or (cur is None and h['OldValue'] in (None, '')))), None)
        if not nxt:
            break
        seen.add(id(nxt)); cur = nxt['NewValue']
    try:
        return float(cur), later
    except (TypeError, ValueError):
        return sa['pta_min'], later


def analyze_day(tid, d):
    snap = load_snapshot(tid, d)
    hist = defaultdict(list)
    for h in json.load(open(f'{S}/pta_{tid}_{d}.json')):
        hist[h['ServiceAppointmentId']].append(h)
    v = score_snapshot(snap, R)
    d0, d1 = parse_dt(snap['window']['day_start_utc']), parse_dt(snap['window']['day_end_utc'])
    minutes = [d0 + timedelta(minutes=i) for i in range(int((d1 - d0).total_seconds() // 60))]
    drv = {x['id']: _Driver(x) for x in snap['drivers']}
    members = [x['id'] for x in snap['drivers'] if x['member']]
    jobs = defaultdict(list)
    for sa in snap['sas']:
        if sa['busy'] and sa['final_driver_id'] and not sa['is_drop_off']:
            jobs[sa['final_driver_id']].append((parse_dt(sa['busy'][0]), parse_dt(sa['busy'][1])))
    on = {}
    for x in snap['drivers']:
        lg = [(parse_dt(a['start']), parse_dt(a['end'])) for a in x['logins']]
        ab = [(parse_dt(a['start']), parse_dt(a['end'])) for a in x['absences']]
        on[x['id']] = (lg, ab)

    def is_on(dd, t):
        lg, ab = on[dd]
        return any(a <= t < b for a, b in lg) and not any(a <= t < b for a, b in ab)

    def n_open(dd, t):
        return sum(1 for a, b in jobs.get(dd, ()) if a <= t < b)

    def idle_q_near(sa, t, exclude=None):
        for y in members:
            if y == exclude or not is_on(y, t) or n_open(y, t):
                continue
            if not drv[y].qualified(sa['required_skills'], t):
                continue
            p = drv[y].pos(t, AGE)
            if p and miles(p[0], p[1], sa['lat'], sa['lon']) <= REACH:
                return y
        return None

    # 5. idle qualified driver-minutes while >=1 call waited (H2 numerator, B7 waits), and
    #    call-minutes waited while an idle qualified driver was within 15 mi.
    waits = _waits(snap)
    idle_driver_min, waited_call_min_cov, waited_call_min = 0, 0, 0
    for t in minutes:
        active = [sa for a, b, sa in waits if a <= t < b]
        if not active:
            continue
        waited_call_min += len(active)
        for y in members:
            if not is_on(y, t) or n_open(y, t):
                continue
            p = drv[y].pos(t, AGE)
            if p and any(drv[y].qualified(sa['required_skills'], t) and miles(p[0], p[1], sa['lat'], sa['lon']) <= REACH
                         for sa in active):
                idle_driver_min += 1
        for sa in active:
            if idle_q_near(sa, t):
                waited_call_min_cov += 1
    on_shift_min = sum(1 for y in members for t in minutes[::5] if is_on(y, t)) * 5

    rows = []
    for sa in snap['sas']:
        if sa['id'] not in v:
            continue
        vv, f, m = v[sa['id']], v[sa['id']]['evidence'], sa['milestones']
        arrival, due = parse_dt(m['arrival']), parse_dt(sa['pta_due'])
        late = (arrival - due).total_seconds() / 60 if f['pta_met'] is False else None
        p0, later = orig_pta(sa, hist.get(sa['id'], []))
        created = parse_dt(sa['created'])
        spot_shift = None
        if sa['pta_due'] and sa['pta_min']:
            spot_shift = ((due - timedelta(minutes=sa['pta_min'])) - created).total_seconds() / 60
        met_orig = None
        if arrival and p0 and 0 < p0 < 999:
            met_orig = arrival <= created + timedelta(minutes=p0)
        # member cancel while waiting
        cancel = m['end_status'] in CANCEL_ST and not m['t_ol'] and not arrival
        cancel_info = None
        if cancel:
            t_end = parse_dt(m['t_end'])
            st_at = None
            for e in sa['events']:
                if e['field'] == 'status' and parse_dt(e['ts']) < t_end:
                    st_at = e['value']
            spotted_min = 0.0
            cur, since = None, None
            for e in [e for e in sa['events'] if e['field'] == 'status'] + [{'ts': m['t_end'], 'value': '_END'}]:
                if cur == 'Spotted':
                    spotted_min += (parse_dt(e['ts']) - since).total_seconds() / 60
                cur, since = e['value'], parse_dt(e['ts'])
            run, best, t = 0, 0, created + timedelta(minutes=10)
            stop = parse_dt(m['t_er']) or t_end
            if sa['lat'] is not None:
                while t < stop:
                    run = run + 2 if idle_q_near(sa, t, exclude=sa['final_driver_id']) else 0
                    best = max(best, run)
                    t += timedelta(minutes=2)
            cancel_info = {
                'reason': sa['cancel_reason'], 'member': sa['cancel_reason'] in MEMBER_REASONS,
                'wait_min': round((t_end - created).total_seconds() / 60, 1),
                'past_pta': bool(due and t_end > due), 'status_before': st_at,
                'spotted_min': round(spotted_min, 1),
                'from_spot_terr': any('SPOT' in (x or '').upper() for x in sa['territory_moves']['from']),
                'idle_q_run_min': best, 'sched_delay': vv['code'] in SCHED + ('BOUNCED',) or best >= RUN_MIN,
            }
        pull_actors = Counter(actor_class(e, R) for e in sa['events'] if e['field'] == 'status' and e['value'] == 'Spotted'
                              and any(e2['field'] == 'status' and e2['value'] in ('Dispatched', 'Accepted', 'En Route')
                                      and e2['ts'] < e['ts'] for e2 in sa['events']))
        rows.append({
            'tid': tid, 'date': d, 'id': sa['id'], 'number': sa['number'], 'woli': sa['woli_id'],
            'channel': sa['channel'], 'code': vv['code'], 'flags': vv['flags'], 'graded': vv['graded'],
            'pick_mi': f.get('pick_miles'), 'closest_free_mi': f.get('closest_free_q_miles'),
            'extra_free_mi': f.get('extra_free_miles'), 'idle_closer': f.get('idle_closer'),
            'pick_open': f.get('pick_open_jobs'), 'pta_met': f['pta_met'], 'late_min': late,
            'pta_min': sa['pta_min'], 'pta0': p0, 'pta_later_edits': [(h['OldValue'], h['NewValue'], h['CreatedDate'], h['CreatedBy']['Name']) for h in later],
            'spot_shift_min': spot_shift, 'met_orig': met_orig, 'arrived': f['arrived'],
            'n_picks': f['n_picks'], 'n_pre': f['n_pre_dispatch_picks'], 'pullbacks': f['pullbacks'],
            'pullback_actors': dict(pull_actors), 'reassign_after_dispatch': f['reassign_after_dispatch'],
            'final_actor_class': f['final_actor_class'], 'cancel': cancel_info, 'response_min': f['response_min'],
            'terr_moves_in': f['terr_moves_in'],
        })
    day = {'tid': tid, 'date': d, 'name': snap['territory']['name'], 'n_scored': len(rows),
           'by_channel': snap['channel_summary']['by_channel'],
           'idle_driver_min': idle_driver_min, 'waited_call_min': waited_call_min,
           'waited_call_min_with_idle_q': waited_call_min_cov, 'on_shift_min': on_shift_min,
           'completeness': snap['completeness']}
    return day, rows


if __name__ == '__main__':
    days, allrows = [], []
    for tid, ds in PLAN.items():
        for d in ds:
            if ONLY and d not in ONLY: continue
            day, rows = analyze_day(tid, d)
            days.append(day); allrows += rows
            print(d, day['name'], day['n_scored'], Counter(r['code'] for r in rows).most_common(5), flush=True)
    json.dump({'days': days, 'rows': allrows}, open(f'{S}/rows.json', 'w'), default=str)
