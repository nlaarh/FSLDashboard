"""Call Story: S1-S9 segments and severity (call-story-spec 5.1/5.3, architecture 4.3/5). Pure, no I/O.

extract() is the ONE function used both for a story and for the baselines (run over every SA of every day
snapshot), so a story is always judged against norms computed the same way.

Input `record` = a report-card SA record (report_card_snapshot.sa_record): created, events (status / assigned /
territory), work_type, channel, is_drop_off. Segment rows carry everything the norm keys need.
"""

import re

from call_story_config import PRE_ARRIVAL, SEVERITY_ORDER, TERMINAL
from utils import parse_dt, to_eastern

STATUS_SEGMENT = {'Assigned': 'S2', 'Dispatched': 'S3', 'Accepted': 'S4', 'En Route': 'S5', 'On Location': 'S6',
                  'Rejected': 'S7', 'Declined': 'S7'}


def place_kind(name: str | None, cfg: dict) -> str | None:
    """GARAGE | SPOT | GRID | UNASSIGNED for a territory (or placeholder resource) name."""
    if not name:
        return None
    g = cfg['grid']
    up = name.upper()
    if up.strip() == g['unassigned_name']:
        return 'UNASSIGNED'
    if any(name.startswith(p) for p in g['spot_prefixes']) or any(c in up for c in g['spot_contains']):
        return 'SPOT'
    if re.match(g['zone_regex'], name.strip()):
        return 'GRID'
    return 'GARAGE'


def _iso(dt):
    return dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z') if dt else None


def extract(record: dict, cfg: dict, open_jobs=None, driver_channel=None, initial_territory: str | None = None) -> list:
    """Segments for one SA. open_jobs(driver_id, t, exclude_sa_id) -> int splits S3 into BUSY/FREE;
    driver_channel(driver_id) -> channel for the hop. Drop-offs never produce segments."""
    if record.get('is_drop_off'):
        return []
    created = parse_dt(record['created'])
    events = sorted(record.get('events') or [], key=lambda e: e['ts'])
    status = [(parse_dt(e['ts']), e['value']) for e in events if e['field'] == 'status']
    picks = [(parse_dt(e['ts']), e.get('driver'), e.get('driver_id')) for e in events
             if e['field'] == 'assigned']
    moves = [(parse_dt(e['ts']), e.get('from'), e.get('to')) for e in events if e['field'] == 'territory']
    first_garage = initial_territory or (moves[0][1] if moves else None) or record.get('territory_name')
    end = next((t for t, v in status if v in TERMINAL), None)

    def driver_at(t):
        last = None
        for ts, name, did in picks:
            if ts <= t:
                last = (name, did) if name else None
        return last

    def garage_at(t):
        last = first_garage
        for ts, _, to in moves:
            if ts <= t:
                last = to
        return last

    def channel_at(t):
        d = driver_at(t)
        if d:
            name, did = d
            if (name or '').lower().startswith('towbook'):
                return 'towbook'
            if place_kind(name, cfg) == 'SPOT':
                return 'spot'
            if did and driver_channel and driver_channel(did):
                return driver_channel(did)
        return record.get('channel')

    rows = []
    cur, start = 'S1', created
    for t, v in status:
        if cur is None:
            break
        nxt = None if v in TERMINAL else STATUS_SEGMENT.get(v, 'S1')
        if nxt == cur:
            continue
        rows.append((cur, start, t))
        cur, start = nxt, t
    if cur is not None:
        rows.append((cur, start, None))
    rows += _place_segments(created, picks, moves, first_garage, end, cfg)

    out = []
    for kind, a, b in sorted(rows, key=lambda r: (r[1], r[0])):
        if b is not None and b <= a:
            continue
        et = to_eastern(a)
        row = {'kind': kind, 'from': _iso(a), 'to': _iso(b),
               'minutes': round((b - a).total_seconds() / 60, 1) if b else None,
               'garage': garage_at(a), 'channel': channel_at(a),
               'et_hour_block': et.hour // cfg['baseline']['hour_block'] * cfg['baseline']['hour_block'],
               'daytype': 'weekend' if et.weekday() >= 5 else 'weekday',
               'stuck_type': cfg['stuck_types'].get(kind), 'owner': cfg['segment_owner'][kind],
               'driver_state': None, 'work_type': record.get('work_type') if kind == 'S6' else None, 'driver': None}
        if kind in ('S3', 'S4', 'S5', 'S6'):
            d = driver_at(a)
            row['driver'] = d[0] if d else None
            if kind == 'S3' and d and d[1] and open_jobs is not None:
                row['driver_state'] = 'BUSY' if open_jobs(d[1], a, record['id']) else 'FREE'
        out.append(row)
    for i, r in enumerate(out, 1):
        r['id'] = f'G{i}'
    return out


def _place_segments(created, picks, moves, initial_territory, end, cfg) -> list:
    """S8 (parked in a SPOT bucket, by territory or a 000-* placeholder resource) and S9 (in a raw grid zone),
    each until the next GARAGE territory. They overlay the status segments."""
    points = [(created, place_kind(initial_territory, cfg) or 'GARAGE', 'territory')]
    points += [(ts, place_kind(to, cfg) or 'GARAGE', 'territory') for ts, _, to in moves]
    points += [(ts, 'SPOT', 'placeholder') for ts, name, _ in picks if place_kind(name, cfg) == 'SPOT']
    points.sort(key=lambda p: p[0])
    state, since, out = 'GARAGE', created, []
    for ts, kind, src in points:
        if end and ts >= end:
            break
        new = kind if src == 'territory' else 'SPOT'
        if new == state:
            continue
        if state in ('SPOT', 'GRID', 'UNASSIGNED'):
            out.append(('S8' if state == 'SPOT' else 'S9', since, ts))
        state, since = new, ts
    if state in ('SPOT', 'GRID', 'UNASSIGNED'):
        out.append(('S8' if state == 'SPOT' else 'S9', since, end))
    return out


def norm_key(seg: dict) -> str:
    """S3 is split by driver state at dispatch, S6 by work type (spec 5.2)."""
    if seg['kind'] == 'S3':
        return f"S3:{seg.get('driver_state') or 'ANY'}"
    if seg['kind'] == 'S6':
        return f"S6:{seg.get('work_type') or 'ANY'}"
    return seg['kind']


def severity(seg: dict, baseline: dict | None, due_initial, cfg: dict) -> tuple:
    """(severity, reason). Percentiles only with n >= min_n; otherwise floors only, never STUCK/CRITICAL by percentile."""
    m = seg['minutes']
    if m is None:
        return 'OK', None
    floor = cfg['floors_min'][seg['kind']]
    sev, why = 'OK', None
    if baseline and baseline['n'] >= cfg['baseline']['min_n']:
        if m > max(baseline['p95'], floor):
            sev, why = 'CRITICAL', 'p95'
        elif m > max(baseline['p90'], floor):
            sev, why = 'STUCK', 'p90'
        elif m > baseline['p75']:
            sev, why = 'SLOW', 'p75'
    elif m > floor:
        sev, why = 'SLOW', 'floor'
    if seg['kind'] in cfg['always_flag'] and sev == 'OK':
        sev, why = 'SLOW', 'always_flag'
    rule = cfg['severity']['critical_if_pta_passed']
    if (rule['enabled'] and due_initial and seg['kind'] in rule['segments'] and seg['kind'] in PRE_ARRIVAL
            and SEVERITY_ORDER.index(sev) >= SEVERITY_ORDER.index(rule['min_severity']) and sev != 'CRITICAL'):
        a, b = parse_dt(seg['from']), parse_dt(seg['to'])
        if b and a < due_initial <= b:
            sev, why = 'CRITICAL', 'pta_passed'
    return sev, why

