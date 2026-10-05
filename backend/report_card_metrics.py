"""Scheduler Report Card: driver-day metrics, health badge and garage summary. Pure, no I/O.

Formulas: metrics-spec.md section 5 (METRICS_VERSION m1), only the metrics this slice shows:
M01, M03, M04, M06, M07, M08, M12, M13 per driver; M02, M09, M17, M19, M20 and verdict counts
for the garage. Bands come from the rules version (report_card_verdicts.RULES_R1). Driver health is
h1 (report_card_health).
"""

import statistics as st
from collections import Counter, defaultdict
from datetime import timedelta

from report_card_health import health_by_driver
from utils import parse_dt

METRICS_VERSION = 'm1'
MIN_SHIFT_MIN = 60   # spec M02/M03: drivers on shift >= 1 h


def band(metric_id: str, value, rules: dict):
    """'good' | 'watch' | 'bad' | None. A band starting at 0 means lower is better."""
    b = rules['metric_bands'].get(metric_id)
    if b is None or value is None:
        return None
    if b['good'][0] == 0:
        return 'good' if value <= b['good'][1] else ('watch' if value <= b['watch'][1] else 'bad')
    return 'good' if value >= b['good'][0] else ('watch' if value >= b['watch'][0] else 'bad')


def _p90(values: list):
    return sorted(values)[int(0.9 * len(values))] if values else None


def _ratio(n, d):
    return round(n / d, 4) if d else None


def _intervals(flags: list, t0) -> list:
    """Runs of True minutes -> [[start_iso, end_iso]]."""
    out, start = [], None
    for i, on in enumerate(flags + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            out.append([_iso(t0 + timedelta(minutes=start)), _iso(t0 + timedelta(minutes=i))])
            start = None
    return out


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def driver_day(snapshot: dict, verdicts: dict, rules: dict) -> list:
    """One row per driver with on-shift time or work: minute sweep over the Eastern day."""
    d0, d1 = parse_dt(snapshot['window']['day_start_utc']), parse_dt(snapshot['window']['day_end_utc'])
    minutes = [d0 + timedelta(minutes=i) for i in range(int((d1 - d0).total_seconds() // 60))]
    jobs = defaultdict(list)
    for sa in snapshot['sas']:
        if sa['busy'] and sa['final_driver_id'] and not sa['is_drop_off']:
            jobs[sa['final_driver_id']].append((parse_dt(sa['busy'][0]), parse_dt(sa['busy'][1]), sa))
    on, n_open = {}, {}
    for d in snapshot['drivers']:
        logins = [(parse_dt(x['start']), parse_dt(x['end'])) for x in d['logins']]
        absent = [(parse_dt(x['start']), parse_dt(x['end'])) for x in d['absences']]
        on[d['id']] = [any(a <= t < b for a, b in logins) and not any(a <= t < b for a, b in absent) for t in minutes]
        n_open[d['id']] = [sum(1 for a, b, _ in jobs.get(d['id'], ()) if a <= t < b) for t in minutes]
    health = health_by_driver(snapshot, verdicts, rules, minutes, on, n_open, jobs)
    rows = []
    for d in snapshot['drivers']:
        osm = sum(on[d['id']])
        scored = [sa for _, _, sa in jobs.get(d['id'], ()) if sa['in_day']]
        if not osm and not scored:
            continue
        rows.append(_driver_row(d, on[d['id']], n_open[d['id']], osm, scored, verdicts, rules, d0, health[d['id']]))
    rows.sort(key=lambda r: (-r['assigned'], r['name'] or ''))
    return rows


def _driver_row(d, on, n_open, osm, scored, verdicts, rules, d0, health) -> dict:
    qw = [verdicts[s['id']]['evidence']['queue_wait_min'] for s in scored if s['id'] in verdicts]
    qw = [x for x in qw if x is not None and x > 0]
    pta = [verdicts[s['id']]['evidence']['pta_met'] for s in scored if s['id'] in verdicts]
    pta = [x for x in pta if x is not None]
    resp = [verdicts[s['id']]['evidence']['response_min'] for s in scored if s['id'] in verdicts]
    resp = [x for x in resp if x is not None and 0 < x < 1440]
    busy_on = sum(1 for o, n in zip(on, n_open) if o and n)
    m = {
        'M01': {'value': len(scored), 'completed': sum(1 for s in scored if s['status'] == 'Completed')},
        'M03': {'value': round(len(scored) / (osm / 60), 2) if osm >= MIN_SHIFT_MIN else None},
        'M04': {'value': _ratio(busy_on, osm)},
        'M06': {'value': max(n_open) if n_open else 0},
        'M07': {'value': sum(1 for n in n_open if n >= 2)},
        'M08': {'value': round(_p90(qw), 1) if qw else None, 'median': round(st.median(qw), 1) if qw else None, 'n': len(qw)},
        'M12': {'value': round(st.median(resp)) if resp else None, 'n': len(resp)},
        'M13': {'value': _ratio(sum(pta), len(pta)), 'met': sum(pta), 'n': len(pta)},
    }
    for k in m:
        m[k]['band'] = band(k, m[k]['value'], rules)
    codes = Counter(verdicts[s['id']]['code'] for s in scored if s['id'] in verdicts)
    return {
        'id': d['id'], 'name': d['name'], 'channel': d['channel'], 'member': d['member'],
        'on_shift_min': osm, 'assigned': len(scored), 'metrics': m,
        'health': health['health'], 'health_owner': health['owner'], 'health_detail': health,
        'verdict_counts': dict(codes),
        'assigned_off_shift': sum(1 for s in scored if s['id'] in verdicts
                                  and verdicts[s['id']]['evidence'].get('assigned_off_shift')),
        'idle': _intervals([o and not n for o, n in zip(on, n_open)], d0),
        'stacked': _load_runs(n_open, d0),
        'on_shift': _intervals(on, d0),
    }


def _load_runs(n_open: list, t0) -> list:
    """Runs of 2+ open jobs -> [[start_iso, end_iso, open_jobs]], split where the count changes."""
    out, start = [], None
    for i, n in enumerate(n_open + [0]):
        if start is not None and n != n_open[start]:
            out.append([_iso(t0 + timedelta(minutes=start)), _iso(t0 + timedelta(minutes=i)), n_open[start]])
            start = None
        if start is None and n >= 2:
            start = i
    return out


def garage_summary(snapshot: dict, verdicts: dict, drivers: list, rules: dict) -> dict:
    ev = [v['evidence'] for v in verdicts.values()]
    pta = [e['pta_met'] for e in ev if e['pta_met'] is not None]
    resp = [e['response_min'] for e in ev if e['response_min'] is not None and 0 < e['response_min'] < 1440]
    qw = [e['queue_wait_min'] for e in ev if e['queue_wait_min'] and e['queue_wait_min'] > 0]
    graded = [e for e in ev if e['graded']]
    free = [e for e in graded if e['closest_free_driver_id']]
    m20 = [e for e in ev if e.get('m20_graded')]
    codes = Counter(v['code'] for v in verdicts.values())
    # Spec 7.4 "(7 + 2) / 81 graded": inbound calls are context, their clock started elsewhere.
    n_graded = sum(1 for v in verdicts.values() if v['graded'] and v['code'] != 'INBOUND_CASCADE')
    fails = sum(1 for v in verdicts.values() if v['is_failure'])
    on1h = [r['assigned'] for r in drivers if r['on_shift_min'] >= MIN_SHIFT_MIN and r['member']]
    jph = [r['metrics']['M03']['value'] for r in drivers if r['metrics']['M03']['value'] is not None and r['member']]
    out = {
        'sa_count': len(verdicts),
        'M13': {'met': sum(pta), 'n': len(pta), 'value': _ratio(sum(pta), len(pta))},
        'M12': {'median': round(st.median(resp)) if resp else None, 'n': len(resp)},
        'M08': {'median': round(st.median(qw)) if qw else None, 'p90': round(_p90(qw)) if qw else None, 'n': len(qw)},
        'M09': dict(Counter(e['final_actor_class'] for e in ev if e['final_actor_class'])),
        'M17': {'picked': sum(1 for e in graded if e['picked_closest']), 'n': len(graded)},
        'M19': {'picked': sum(1 for e in free if e['picked_closest_free']), 'n': len(free)},
        'M20': {'idle_closer': sum(1 for e in m20 if e['idle_q_closer_count']),
                'less_loaded_closer': sum(1 for e in m20 if e['less_loaded_q_closer_count']), 'n': len(m20)},
        'M02': {'value': round(max(on1h) / st.median(on1h), 2) if on1h and st.median(on1h) else None,
                'drivers': len(on1h)},
        'M03': {'min': min(jph) if jph else None, 'median': round(st.median(jph), 2) if jph else None,
                'max': max(jph) if jph else None},
        'M07': {'value': sum(r['metrics']['M07']['value'] for r in drivers)},
        'verdict_counts': dict(codes),
        'flag_counts': dict(Counter(f for v in verdicts.values() for f in v['flags'])),
        'failure_rate': {'failures': fails, 'graded': n_graded, 'value': _ratio(fails, n_graded)},
        'health_counts': dict(Counter(r['health'] for r in drivers)),
    }
    for k in ('M13', 'M02'):
        out[k]['band'] = band(k, out[k]['value'], rules)
    out['M17']['band'] = band('M17', _ratio(out['M17']['picked'], out['M17']['n']), rules)
    out['M19']['band'] = band('M19', _ratio(out['M19']['picked'], out['M19']['n']), rules)
    out['M20']['band'] = band('M20', _ratio(out['M20']['idle_closer'], out['M20']['n']), rules)
    out['M08']['band'] = band('M08', out['M08']['p90'], rules)
    return out
