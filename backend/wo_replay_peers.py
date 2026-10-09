"""Work Order Replay: the other drivers of the garage who could have taken this call, at the moment it was given to the driver
(and again when the driver accepted it). No Salesforce read: everything comes from the garage-day snapshot the Report Card saved.

Who is shown: a driver of the same garage's roster who was ON SHIFT (truck login minus absence) and QUALIFIED at that moment, and
whose last GPS fix was fresh. Qualified = the work order's required skills are a subset of the driver's skills plus the logged-in
truck's capabilities, exactly as report_card_health._Driver.qualified (and the verdicts) decide it. The driver who got the call is left out.
Distance is a straight line in miles, not road distance.
Each driver also carries the queue they held at that moment (call number, status, when it was given, miles from the member) and the next call they were given. Status comes from the other calls the snapshot has for that driver.
Drivers who were on shift but not qualified are only counted. Towbook garages do not report driver positions or names: no one is listed.
Never returns a phone number or street address."""

import re

from report_card_health import _Driver
from report_card_snapshot import GPS_MAX_AGE_MIN, miles
from utils import parse_dt, to_eastern
from wo_replay_map import _towbook

_SUFFIX = re.compile(r'\s+\d{2,5}[A-Z]{0,2}$')
LABELS = {'free': 'free', 'en_route': 'driving to a job', 'on_location': 'on a job', 'towing': 'towing', 'waiting': 'has a job, not started'}
RANK = {'towing': 4, 'on_location': 3, 'en_route': 2, 'waiting': 1, 'free': 0}
TOWBOOK_NOTE = 'This call went through a Towbook garage. Towbook does not report where its other drivers are, so they are not visible.'
DISTANCE_NOTE = 'Distances are straight-line miles, not road distance.'


def _short(n):
    return _SUFFIX.sub('', n or '').strip()


def _on_shift(d: dict, t) -> bool:
    return (any(parse_dt(x['start']) <= t < parse_dt(x['end']) for x in d.get('logins') or [])
            and not any(parse_dt(x['start']) <= t < parse_dt(x['end']) for x in d.get('absences') or []))


def _iso(t):
    return t.isoformat().replace('+00:00', 'Z') if t else None


def _job(s: dict, label: str, member: dict) -> dict:
    """One call in a driver's queue. Distance is from the member's location (a drop-off has no pin)."""
    m = s['milestones']
    mi = None if s['is_drop_off'] or s.get('lat') is None else round(miles(s['lat'], s['lon'], member['lat'], member['lon']), 1)
    return {'sa': s.get('number'), 'work_type': s.get('work_type'), 'label': label, 'given_at': m['t_asg'], 'miles': mi}


def _state(sas_of_driver: list, member: dict, t) -> tuple:
    """(status, calls held, queue, next) for one driver at t. Held = the same count the snapshot uses for open jobs (drop-offs never count);
    a drop-off that is under way means the driver is towing and shows in the queue as towing. queue is in the order the calls were given;
    next = the first call given to the driver after t and when they reached it."""
    state, held, queue, later = 'free', 0, [], []
    for s in sas_of_driver:
        m = s['milestones']
        if s['id'] == member['id']:
            continue
        asg = parse_dt(m['t_asg'])
        if asg and asg > t and not s['is_drop_off']:
            later.append((asg, s))
        if not s['is_drop_off'] and not s.get('busy'):
            continue
        if s['is_drop_off']:
            er, end = parse_dt(m['t_er']), parse_dt(m['t_end'] or m['actual_end'])
            if er and er <= t and (end is None or t < end):
                state = max(state, 'towing', key=RANK.get)
                queue.append((asg, _job(s, LABELS['towing'], member)))
            continue
        a, b = parse_dt(s['busy'][0]), parse_dt(s['busy'][1])
        if not a <= t < b:
            continue
        held += 1
        ol, er = parse_dt(m['t_ol']), parse_dt(m['t_er'])
        here = 'on_location' if ol and ol <= t else 'en_route' if er and er <= t else 'waiting'
        state = max(state, here, key=RANK.get)
        queue.append((asg, _job(s, {'on_location': 'on scene', 'en_route': 'driving to it', 'waiting': 'not started'}[here], member)))
    nxt = None
    if later:
        asg, s = min(later, key=lambda x: x[0])
        nxt = {**_job(s, '', member), 'reached_at': s['milestones']['t_ol']}
        nxt.pop('label')
    return state, held, [j for _, j in sorted(queue, key=lambda x: x[0] or t)], nxt


def peers_at(snap: dict, member: dict, driver_id: str | None, t) -> dict:
    """{'at', 'drivers': [...sorted by distance], 'not_qualified', 'no_gps'} for one moment."""
    by_driver = {}
    for s in snap['sas']:
        if s.get('final_driver_id'):
            by_driver.setdefault(s['final_driver_id'], []).append(s)
    shown, not_qualified, no_gps = [], 0, 0
    for d in snap['drivers']:
        if not d['member'] or d['id'] == driver_id or not _on_shift(d, t):
            continue
        x = _Driver(d)
        if not x.qualified(member['required_skills'], t):
            not_qualified += 1
            continue
        pos = x.pos(t, GPS_MAX_AGE_MIN)
        if pos is None:
            no_gps += 1
            continue
        status, held, queue, nxt = _state(by_driver.get(d['id'], []), member, t)
        shown.append({'name': _short(d['name']), 'status': status, 'label': LABELS[status], 'held': held, 'queue': queue, 'next': nxt,
                      'miles': round(miles(pos[0], pos[1], member['lat'], member['lon']), 1), 'lat': round(pos[0], 5), 'lon': round(pos[1], 5)})
    shown.sort(key=lambda p: p['miles'])
    return {'at': t.isoformat().replace('+00:00', 'Z'), 'drivers': shown, 'not_qualified': not_qualified, 'no_gps': no_gps}


def build_peers(snap: dict | None, member_id: str) -> dict:
    """The /api/call-story/peers answer from a day snapshot (None when the day is not built)."""
    out = {'available': False, 'channel': None, 'moments': [], 'notes': [], 'member': None}
    snap_sa = next((s for s in (snap or {}).get('sas', []) if s['id'] == member_id), None)
    if not snap_sa:
        out['notes'].append('The Report Card for this garage and day has not been built, so the other drivers\' positions are not available.')
        return out
    out['channel'] = snap_sa['channel']
    if snap_sa['channel'] == 'towbook':
        out['notes'].append(TOWBOOK_NOTE)
        return out
    m = snap_sa['milestones']
    if snap_sa['lat'] is None or not m['t_asg']:
        out['notes'].append('This call was never given to a driver, or has no location, so there is nothing to compare.')
        return out
    out['available'], out['member'] = True, {'lat': round(snap_sa['lat'], 4), 'lon': round(snap_sa['lon'], 4)}
    given, accepted = parse_dt(m['t_asg']), parse_dt(m['t_acc'])
    moments = [('given', given)] + ([('accepted', accepted)] if accepted and accepted > given else [])
    for kind, t in moments:
        out['moments'].append({'kind': kind, **peers_at(snap, snap_sa, snap_sa['final_driver_id'], t)})
    if snap.get('provisional'):
        out['notes'].append('This garage-day is still provisional: positions may be incomplete.')
    out['notes'].append(DISTANCE_NOTE)
    return out


def pull_peers(raw: dict, snapshot_for) -> dict:
    """Zero Salesforce calls: the member leg's garage-day snapshot only."""
    sas = raw.get('sas') or []
    sa = next((s for s in sas if 'drop' not in ((s.get('WorkType') or {}).get('Name') or '').lower()), sas[0] if sas else None)
    if _towbook(raw):      # decided from the story itself, so it holds even when the day was never built
        return {'available': False, 'channel': 'towbook', 'moments': [], 'member': None, 'notes': [TOWBOOK_NOTE], 'sf_calls': 0}
    if not sa or not sa.get('ServiceTerritoryId'):
        return build_peers(None, '')
    snap = snapshot_for(sa['ServiceTerritoryId'], to_eastern(sa['CreatedDate']).date().isoformat())
    return {**build_peers(snap, sa['Id']), 'sf_calls': 0}
