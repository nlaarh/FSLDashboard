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
from datetime import timedelta

import gps_store
from feature_flags import is_on
from report_card_health import _Driver
from report_card_snapshot import GPS_MAX_AGE_MIN, miles
from utils import parse_dt, to_eastern
from wo_replay_map import _ID, _member_sa, _towbook

_SUFFIX = re.compile(r'\s+\d{2,5}[A-Z]{0,2}$')
LABELS = {'busy': 'has a job', 'free': 'free', 'en_route': 'driving to a job', 'on_location': 'on a job', 'towing': 'towing', 'waiting': 'has a job, not started'}
RANK = {'towing': 4, 'on_location': 3, 'en_route': 2, 'waiting': 1, 'free': 0}
TOWBOOK_NOTE = 'This call went through a Towbook garage. Towbook does not report where its other drivers are, so they are not visible.'
OPEN_NOTE = ('This call is still open and its garage-day is not built yet, so the other drivers are today\'s qualified, on-shift drivers. '
             'Their positions are from our own GPS record at each moment; the calls they held are the ones still open now.')
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


def _moments(raw: dict, sa: dict) -> tuple:
    """([(kind, time)], name of the driver it went to): when the member leg was last given to a driver, and when that driver accepted (Status history)."""
    rows = [h for h in raw.get('history') or [] if h.get('ServiceAppointmentId') == sa['Id']]
    picks = [h for h in rows if h.get('Field') == 'ERS_Assigned_Resource__c' and h.get('NewValue') and not _ID.match(h['NewValue'])]
    if not picks:
        return [], None
    last = max(picks, key=lambda h: parse_dt(h['CreatedDate']))
    given = parse_dt(last['CreatedDate'])
    acc = min((parse_dt(h['CreatedDate']) for h in rows if h.get('Field') == 'Status' and h.get('NewValue') == 'Accepted' and parse_dt(h['CreatedDate']) > given), default=None)
    return [('given', given)] + ([('accepted', acc)] if acc else []), last['NewValue']


def _stored_position(rows: list, rid: str, t) -> tuple | None:
    """The last stored fix of the driver at or before t, from gps_store rows (a latitude row and a longitude row share one stamp)."""
    fix = {}
    for r in rows:
        if r['ServiceResourceId'] == rid and parse_dt(r['CreatedDate']) <= t:
            fix.setdefault(r['CreatedDate'], {})[r['Field']] = float(r['NewValue'])
    both = [(parse_dt(k), (v['LastKnownLatitude'], v['LastKnownLongitude'])) for k, v in fix.items() if len(v) == 2]
    return max(both, key=lambda x: x[0])[1] if both else None


def open_peers(raw: dict, live: dict | None, stored=gps_store.stored_gps_rows) -> dict | None:
    """The peers answer for a call that is still open, when no day snapshot exists: `live` is the Watchlist call map's answer (the qualified,
    on-shift drivers now, each with the open calls it holds and when each was given). Position at each moment = our own GPS record (Postgres,
    no Salesforce); a driver whose record does not cover the moment is counted as 'no recent GPS', never guessed. None when it cannot be done."""
    sa = _member_sa(raw.get('sas') or [])
    member = ((live or {}).get('sa') or {})
    if not is_on(gps_store.FLAG) or not sa or not live or member.get('lat') is None:
        return None
    moments, picked = _moments(raw, sa)
    if not moments:
        return None
    roster = [p for p in live.get('peers') or [] if p['name'] != picked]       # the driver it went to is not a candidate (he may be a peer NOW if the call moved since)
    out = {'available': True, 'channel': None, 'moments': [], 'member': {'lat': round(member['lat'], 4), 'lon': round(member['lon'], 4)},
           'notes': [OPEN_NOTE, DISTANCE_NOTE], 'sf_calls': 0}
    ids = [p['id'] for p in roster]
    for kind, t in moments:
        window = {i: (t - timedelta(minutes=GPS_MAX_AGE_MIN), t) for i in ids}
        rows, covered = stored(window) if ids else ([], set())
        shown, no_gps = [], 0
        for p in roster:
            pos = _stored_position(rows, p['id'], t) if p['id'] in covered else None
            if pos is None:
                no_gps += 1
                continue
            held = [j for j in p['queue'] if j.get('given_at') and parse_dt(j['given_at']) <= t]
            queue = [{'sa': j['sa'], 'work_type': j.get('work_type'), 'label': j['label'], 'given_at': j['given_at'],
                      'miles': None if j.get('lat') is None else round(miles(j['lat'], j['lon'], member['lat'], member['lon']), 1)} for j in held]
            status = 'busy' if held else 'free'
            shown.append({'name': _short(p['name']), 'status': status, 'label': LABELS[status], 'held': len(held), 'queue': queue, 'next': None,
                          'miles': round(miles(pos[0], pos[1], member['lat'], member['lon']), 1), 'lat': round(pos[0], 5), 'lon': round(pos[1], 5)})
        shown.sort(key=lambda d: d['miles'])
        out['moments'].append({'kind': kind, 'at': t.isoformat().replace('+00:00', 'Z'), 'drivers': shown,
                               'not_qualified': (live.get('peer_counts') or {}).get('not_qualified', 0), 'no_gps': no_gps})
    return out if any(m['drivers'] for m in out['moments']) else None
