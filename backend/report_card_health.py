"""Scheduler Report Card: driver-day health h1 (metrics-spec.md section 5A). Pure, no I/O.

Two lenses. Workload (scheduler-owned): H1 avoidable stacking, H2 idle while work waited, H3 peak load.
Execution (driver-owned): H4 late after a sound pick, H5 non-response pull-backs, H6 slow to accept when
free. The badge is the worse lens; `owner` names the lens(es) at that band. Thresholds come from
rules['driver_health']. Positions use the snapshot's GPS track (spec S11: newest fix <= t + 5 min, <= 30 min old).
"""

import statistics as st
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import timedelta

from report_card_snapshot import miles
from utils import parse_dt

ORDER = {'good': 0, 'watch': 1, 'bad': 2}
LENS_OWNER = {'workload': 'scheduler', 'execution': 'driver'}
SYSTEM_MISS = ('CAPACITY_SHORT', 'LATE_DESPITE_CAPACITY', 'STACKED', 'FAR_PICK')


def share_band(v, cfg):
    return None if v is None else 'good' if v <= cfg['good'][1] else 'watch' if v <= cfg['watch'][1] else 'bad'


def count_band(n, cfg):
    return 'bad' if n >= cfg['bad_at'] else 'watch' if n >= cfg['watch_at'] else 'good'


class _Driver:
    def __init__(self, d: dict):
        self.d = d
        g = d.get('gps') or []
        self.gts, self.gpos = [x[0] for x in g], [(x[1], x[2]) for x in g]
        self.trucks = [(parse_dt(x['start']), parse_dt(x['end']), set(x['truck_caps'])) for x in d.get('trucks') or []]
        self.skills = set(d.get('skills') or [])

    def pos(self, t, max_age_min):
        e = t.timestamp()
        i = bisect_right(self.gts, e + 300) - 1
        return self.gpos[i] if i >= 0 and e - self.gts[i] <= max_age_min * 60 else None

    def qualified(self, req, t):
        caps = next((c for a, b, c in self.trucks if a <= t < b), set())
        return set(req or []) <= (self.skills | caps)


def health_by_driver(snap: dict, verdicts: dict, rules: dict, minutes: list, on: dict, n_open: dict,
                     jobs: dict) -> dict:
    """{driver_id: health dict}. on / n_open: per-minute lists per driver; jobs: driver -> [(a, b, sa)]."""
    cfg = rules['driver_health']
    reach, age = cfg['reach_mi'], cfg['gps_max_age_min']
    drv = {d['id']: _Driver(d) for d in snap['drivers']}
    names = {d['id']: d['name'] for d in snap['drivers']}
    members = [d['id'] for d in snap['drivers'] if d['member']]
    waits = _waits(snap)
    pullbacks = _nonresponse_pullbacks(snap, jobs, cfg)
    out = {}
    for did, on_list in on.items():
        x, osm = drv[did], sum(on_list)
        avoid, idle_wait, partners = 0, 0, Counter()
        for i, t in enumerate(minutes):
            if not on_list[i]:
                continue
            if n_open[did][i] >= 2:
                queued = [sa for a, b, sa in jobs.get(did, ()) if sa['lat'] is not None
                          and parse_dt(sa['milestones']['t_asg']) and parse_dt(sa['milestones']['t_asg']) <= t
                          and (not sa['milestones']['t_er'] or t < parse_dt(sa['milestones']['t_er']))]
                hit = _idle_partner(queued, did, members, drv, on, n_open, i, t, reach, age)
                if hit:
                    avoid += 1
                    partners[hit] += 1
            elif n_open[did][i] == 0:
                p = x.pos(t, age)
                if p and any(a <= t < b and x.qualified(sa['required_skills'], t)
                             and miles(p[0], p[1], sa['lat'], sa['lon']) <= reach for a, b, sa in waits):
                    idle_wait += 1
        out[did] = _label(did, osm, avoid, idle_wait, partners, names, pullbacks.get(did, []),
                          snap, verdicts, n_open[did], cfg)
    return out


def _idle_partner(queued, did, members, drv, on, n_open, i, t, reach, age):
    for sa in queued:
        for y in members:
            if y == did or y not in on or not on[y][i] or n_open[y][i]:
                continue
            if not drv[y].qualified(sa['required_skills'], t):
                continue
            p = drv[y].pos(t, age)
            if p and miles(p[0], p[1], sa['lat'], sa['lon']) <= reach:
                return y
    return None


def _waits(snap: dict) -> list:
    """B7 waiting calls in this garage: from max(created + 10 min, move-in) until En Route (or end)."""
    out = []
    for sa in snap['sas']:
        if sa['is_drop_off'] or sa['channel'] not in ('fleet', 'on_platform_contractor') or sa['lat'] is None:
            continue
        m = sa['milestones']
        end = parse_dt(m['t_er']) or parse_dt(m['t_end'])
        moved = [parse_dt(e['ts']) for e in sa['events'] if e['field'] == 'territory']
        start = max([parse_dt(sa['created']) + timedelta(minutes=10)] + moved)
        if end and start < end:
            out.append((start, end, sa))
    return out


def _nonresponse_pullbacks(snap: dict, jobs: dict, cfg: dict) -> dict:
    """H5: Dispatched -> Spotted with no accept for >= min wait, from a driver with 0 other open jobs."""
    min_wait = cfg['execution']['H5_nonresponse_pullbacks']['min_wait_fallback_min']
    out = defaultdict(list)
    for sa in snap['sas']:
        cur, disp, prev = None, None, None
        for e in sa['events']:
            if e['field'] == 'assigned' and e.get('driver_id'):
                cur = e['driver_id']
            if e['field'] != 'status':
                continue
            if e['value'] == 'Dispatched':
                disp = parse_dt(e['ts'])
            elif e['value'] == 'Spotted' and prev == 'Dispatched' and cur and disp:
                wait = (parse_dt(e['ts']) - disp).total_seconds() / 60
                busy = sum(1 for a, b, other in jobs.get(cur, ()) if a <= disp < b and other['id'] != sa['id'])
                if wait >= min_wait and busy == 0:
                    out[cur].append({'sa': sa['number'], 'wait_min': round(wait, 1)})
            prev = e['value']
    return out


def _label(did, osm, avoid, idle_wait, partners, names, pulls, snap, verdicts, n_open, cfg) -> dict:
    w, ex = cfg['workload'], cfg['execution']
    enough = osm >= cfg['min_on_shift_min']
    mine = [sa for sa in snap['sas'] if sa['final_driver_id'] == did and sa['id'] in verdicts]
    codes = Counter(verdicts[sa['id']]['code'] for sa in mine)
    accept = []
    for sa in mine:
        m = sa['milestones']
        td, ta = parse_dt(m['t_disp']), parse_dt(m['t_acc']) or parse_dt(m['t_er'])
        if td and ta and verdicts[sa['id']]['evidence'].get('pick_open_jobs') == 0:
            accept.append((ta - td).total_seconds() / 60)
    h6 = ex['H6_accept_when_free_median']
    h6_med = st.median(accept) if len(accept) >= h6['min_n'] else None
    top = names.get(partners.most_common(1)[0][0]) if partners else None
    peak = max(n_open) if n_open else 0
    h1 = round(avoid / osm, 2) if enough and osm else None
    h2 = round(idle_wait / osm, 2) if enough and osm else None
    inputs = [
        ('H1', 'workload', h1, share_band(h1, w['H1_avoidable_stacked_share']),
         f"Scheduler: stacked {_pct(h1)} of the shift while a qualified driver nearby was idle"
         + (f" (mostly {top})" if top else '')),
        ('H2', 'workload', h2, share_band(h2, w['H2_idle_while_waited_share']),
         f"Scheduler: idle {_pct(h2)} of the shift while a call they could take waited within {cfg['reach_mi']} mi"),
        ('H3', 'workload', peak, 'bad' if peak >= w['H3_max_open']['bad_at'] else 'good',
         f"Scheduler: up to {peak} open jobs at once"),
        ('H4', 'execution', codes['LATE_EXECUTION'], count_band(codes['LATE_EXECUTION'], ex['H4_late_execution_count']),
         f"Driver: {codes['LATE_EXECUTION']} late arrival(s) after a quick pick while free"),
        ('H5', 'execution', len(pulls), count_band(len(pulls), ex['H5_nonresponse_pullbacks']),
         f"Driver: pulled back {len(pulls)} time(s) after not accepting"
         + (f" ({', '.join(str(p['wait_min']) + ' min' for p in pulls)})" if pulls else '')),
        ('H6', 'execution', round(h6_med, 1) if h6_med is not None else None,
         None if h6_med is None else 'good' if h6_med <= h6['fallback_min']['p75']
         else 'watch' if h6_med <= h6['fallback_min']['p90'] else 'bad',
         f"Driver: median {h6_med and round(h6_med, 1)} min to accept when free "
         f"(garage p75 {h6['fallback_min']['p75']} min)"),
    ]
    lenses = {}
    for lens in ('workload', 'execution'):
        bands = [b for _, ln, _, b, _ in inputs if ln == lens and b]
        lenses[lens] = max(bands, key=ORDER.get) if bands else 'good'
    worst = max(lenses.values(), key=ORDER.get)
    owners = [LENS_OWNER[k] for k, b in lenses.items() if b == worst and worst != 'good']
    misses = [verdicts[sa['id']] for sa in mine if verdicts[sa['id']]['evidence']['pta_met'] is False]
    qw = [verdicts[sa['id']]['evidence']['queue_wait_min'] for sa in mine]
    qw = [q for q in qw if q and q > 0]
    return {
        'version': cfg['version'],
        'health': {'good': 'healthy', 'watch': 'watch', 'bad': 'unhealthy'}[worst],
        'owner': None if not owners else owners[0] if len(owners) == 1 else 'both',
        'lenses': lenses,
        'inputs': [{'id': i, 'lens': ln, 'value': v, 'band': b, 'text': t} for i, ln, v, b, t in inputs],
        'reasons': [{'id': i, 'lens': ln, 'band': b, 'text': t} for i, ln, v, b, t in inputs if b in ('watch', 'bad')],
        'context': {
            'pta_misses': {'system': sum(1 for v in misses if v['code'] in SYSTEM_MISS),
                           'bounce': sum(1 for v in misses if v['code'] == 'BOUNCED'),
                           'driver': sum(1 for v in misses if v['code'] == 'LATE_EXECUTION')},
            'queue_wait_median': round(st.median(qw), 1) if qw else None,
        },
    }


def _pct(v):
    return '—' if v is None else f'{round(v * 100)}%'
