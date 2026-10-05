"""Scheduler Report Card: raw Salesforce bundle -> immutable garage-day snapshot. Pure, no I/O.

Shape: architecture.md section 4 (schema_version 1). Rules: metrics-spec.md sections 2-4.
Times are ISO-8601 UTC strings. Actor classes and verdicts are NOT computed here: they are
rules config (report_card_verdicts), so a new rules version never needs a rebuild.

Candidate tuple (one per driver, at every assignment event, spec B6):
  [driver_id, lat, lon, miles, qualified, on_shift, open_jobs, gps_age_min, member]
lat/lon/miles/gps_age are null when the driver had no fresh fix. `member` = on the roster that day.
"""

import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from report_card_timeline import Timelines
from utils import parse_dt

SNAPSHOT_SCHEMA_VERSION = 1
BUILDER_VERSION = 'rc-build-1.2'   # 1.1: original PTA per SA (r2); 1.2: Auto_Schedule_Requested__c (spec B4a)
GPS_MAX_AGE_MIN = 30          # spec S11 / r1 candidate.gps_max_age_min
GPS_FORWARD_SLACK_MIN = 5     # spec S11 / r1 candidate.gps_forward_slack_min
SAMPLE_STEP_MIN = 2           # spec 7.2 LATE_DESPITE_CAPACITY sample step (stored, so verdicts need no re-pull)
PTA_INITIAL_WINDOW_S = 5      # spec 7.7 / r2 pta_initial_window_sec: the promise = last ERS_PTA__c row <= 5 s after creation

CHANNEL_MAP = {'Fleet Driver': 'fleet', 'On-Platform Contractor Driver': 'on_platform_contractor',
               'Off-Platform Contractor Driver': 'towbook'}
GRADED_CHANNELS = ('fleet', 'on_platform_contractor')
END_STATUSES = ('Completed', 'Unable to Complete', 'Cancel Call - Service Not En Route',
                'Cancel Call - Service En Route', 'Canceled', 'No-Show')
_SF_ID = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')


def iso(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def miles(lat1, lon1, lat2, lon2):
    """Unrounded great-circle miles (R = 3958.8), as in Henry's validated script. utils.haversine
    rounds to 0.01 mi, which can flip the 0.01/0.5 mi comparisons the verdicts make."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(x))


def call_class(work_type: str) -> str:
    w = (work_type or '').lower()
    if 'tow' in w:
        return 'tow'
    if 'battery' in w or 'jump' in w:
        return 'battery'
    return 'light'


def build_snapshot(raw: dict, built_at: datetime | None = None) -> dict:
    built_at = built_at or datetime.now(timezone.utc)
    w = {k: parse_dt(v) for k, v in raw['window'].items()}
    d0, d1 = w['day_start'], w['day_end']
    tl = Timelines(raw, d0, d1)

    names, dtype, home, ttype, user_of = {}, {}, {}, {}, {}
    for m in raw.get('members') or []:
        sr = m.get('ServiceResource') or {}
        names[m['ServiceResourceId']] = sr.get('Name')
        dtype[m['ServiceResourceId']] = sr.get('ERS_Driver_Type__c')
        user_of[m['ServiceResourceId']] = sr.get('RelatedRecordId')
        ttype[m['ServiceResourceId']] = m.get('TerritoryType')
        home[m['ServiceResourceId']] = (m.get('Latitude'), m.get('Longitude'))
    for a in raw.get('assigned') or []:
        names[a['ServiceResourceId']] = (a.get('ServiceResource') or {}).get('Name')
        dtype.setdefault(a['ServiceResourceId'], (a.get('ServiceResource') or {}).get('ERS_Driver_Type__c'))
    name_to_id = {v: k for k, v in names.items()}
    roster = sorted({m['ServiceResourceId'] for m in raw.get('members') or []
                     if CHANNEL_MAP.get(dtype.get(m['ServiceResourceId'])) in GRADED_CHANNELS})
    driver_users = {user_of[d] for d in roster if user_of.get(d)}

    hist = defaultdict(list)
    for h in sorted(raw.get('history') or [], key=lambda h: h['CreatedDate']):
        hist[h['ServiceAppointmentId']].append(h)
    ar_by_sa = {a['ServiceAppointmentId']: a for a in raw.get('assigned') or []}
    req_by_woli = defaultdict(set)
    for x in raw.get('woli_skills') or []:
        req_by_woli[x['RelatedRecordId']].add((x.get('Skill') or {}).get('MasterLabel'))

    sas = []
    for s in raw.get('sas') or []:
        rec = sa_record(s, hist[s['Id']], ar_by_sa.get(s['Id']), name_to_id, roster, dtype,
                         req_by_woli, driver_users, d0)
        if not rec['in_day'] and not _open_at(rec, d0):
            continue  # carryover that had already ended before the day started
        sas.append(rec)

    jobs = defaultdict(list)  # B5: final driver -> [(start, end, sa_id)]; drop-offs never count
    for r in sas:
        if r['busy'] and r['final_driver_id'] and not r['is_drop_off']:
            jobs[r['final_driver_id']].append((parse_dt(r['busy'][0]), parse_dt(r['busy'][1]), r['id']))

    def open_jobs(d, t, exclude=None):
        return sum(1 for a, b, sid in jobs.get(d, ()) if a <= t < b and sid != exclude)

    for r in sas:
        _add_candidates(r, tl, roster, open_jobs)

    pickers = sorted(set(roster) | {r['final_driver_id'] for r in sas if r['final_driver_id']
                                   and CHANNEL_MAP.get(dtype.get(r['final_driver_id'])) in GRADED_CHANNELS})
    drivers = [_driver_record(d, names, dtype, ttype, home, tl, d in roster, sas) for d in pickers]

    by_channel = _count(r['channel'] for r in sas if r['in_day'] and not r['is_drop_off'])
    graded, towbook = sum(by_channel.get(c, 0) for c in GRADED_CHANNELS), by_channel.get('towbook', 0)
    mode = 'towbook' if towbook and not graded else ('mixed' if towbook else 'fsl')
    terr = raw.get('territory') or {}
    return {
        'schema_version': SNAPSHOT_SCHEMA_VERSION,
        'builder_version': BUILDER_VERSION,
        'territory': {'id': raw['territory_id'], 'name': terr.get('Name'),
                      'lat': terr.get('Latitude'), 'lon': terr.get('Longitude')},
        'service_date': raw['service_date'],
        'window': {'day_start_utc': iso(d0), 'day_end_utc': iso(d1),
                   'carryover_from_utc': iso(w['carryover_from'])},
        'built_at': iso(built_at),
        'provisional': built_at < d1 + timedelta(hours=24),
        'channel_summary': {'by_channel': by_channel, 'mode': mode},
        'drivers': drivers,
        'sas': sas,
        'config': {
            'as_of': 'build_time', 'captured_at': iso(built_at),
            'territory_flags': {k: terr.get(k) for k in ('RSO_Automation_Active__c', 'ERS_Auto_Schedule__c')},
            'policies_used': raw.get('policies') or [],
            'membership_types': _count(ttype.get(d) for d in roster),
        },
        'optimizer_sf': {'requests': raw.get('opt_requests') or []},
        'travel_basis': {'distance': 'haversine_miles', 'note': 'straight line, not road distance'},
        'candidate_rules': {'gps_max_age_min': GPS_MAX_AGE_MIN, 'gps_forward_slack_min': GPS_FORWARD_SLACK_MIN,
                            'sample_step_min': SAMPLE_STEP_MIN,
                            'qualified_rule': 'woli_skills_subset_of_sr_skills_plus_truck_caps'},
        'completeness': {
            'sa_count_expected': raw.get('sa_count_expected'), 'sa_count_loaded': len(raw.get('sas') or []),
            'history_rows': len(raw.get('history') or []), 'ar_rows': len(raw.get('assigned') or []),
            'gps_points_raw': len(raw.get('gps') or []),
            'gps_points_kept': sum(len(d['gps']) for d in drivers),
            'sf_calls': raw.get('sf_calls'), 'build_ms': raw.get('build_ms'),
            'warnings': _warnings(sas),
        },
    }


def _count(values) -> dict:
    out = defaultdict(int)
    for v in values:
        out[v or 'unknown'] += 1
    return dict(out)


def _open_at(r: dict, t) -> bool:
    end = parse_dt(r['milestones']['t_end'])
    return end is None or end > t


def _actor(h: dict, driver_users: set) -> dict:
    cb = h.get('CreatedBy') or {}
    return {'actor': cb.get('Name'), 'actor_profile': (cb.get('Profile') or {}).get('Name'),
            'actor_is_driver': h.get('CreatedById') in driver_users}


def sa_record(s, rows, ar, name_to_id, roster, dtype, req_by_woli, driver_users, day_start) -> dict:
    wt = (s.get('WorkType') or {}).get('Name') or ''
    created = parse_dt(s['CreatedDate'])
    status = [(parse_dt(h['CreatedDate']), h.get('NewValue'), h) for h in rows if h['Field'] == 'Status']
    first = lambda v: next((t for t, n, _ in status if n == v), None)
    t_disp, t_acc, t_er, t_ol = first('Dispatched'), first('Accepted'), first('En Route'), first('On Location')
    end = next(((t, n) for t, n, _ in status if n in END_STATUSES), (None, None))

    assign = [h for h in rows if h['Field'] == 'ERS_Assigned_Resource__c'
              and not _SF_ID.match(h.get('NewValue') or '')
              and not (h.get('NewValue') is None and _SF_ID.match(h.get('OldValue') or ''))]
    picks = [h for h in assign if h.get('NewValue')]
    driver = ar['ServiceResourceId'] if ar else None
    driver_type = (ar.get('ServiceResource') or {}).get('ERS_Driver_Type__c') if ar else None
    fallback = False
    if not driver and picks and name_to_id.get(picks[-1]['NewValue']) in roster:
        driver = name_to_id[picks[-1]['NewValue']]   # canceled SA lost its AR: last pick decides (S2)
        driver_type, fallback = dtype.get(driver), True
    channel = CHANNEL_MAP.get(driver_type, 'unknown') if driver else 'unknown'

    final = [h for h in picks if driver and name_to_id.get(h['NewValue']) == driver]
    t_asg = parse_dt(final[-1]['CreatedDate']) if final else (parse_dt(picks[-1]['CreatedDate']) if picks else None)
    pick_ts = [parse_dt(h['CreatedDate']) for h in picks]
    pullbacks = sum(1 for t, n, _ in status if n == 'Spotted'
                    and any(t2 < t and n2 in ('Dispatched', 'Accepted', 'En Route') for t2, n2, _ in status))
    moves = [h for h in rows if h['Field'] == 'ServiceTerritory' and h.get('OldValue') and h.get('NewValue')
             and not _SF_ID.match(h['NewValue'])]
    ast, aet = parse_dt(s.get('ActualStartTime')), parse_dt(s.get('ActualEndTime'))
    arrival, arrival_src = (ast, 'actual_start') if channel in GRADED_CHANNELS else (t_ol, 'history')
    busy_end = end[0] or aet
    pta = s.get('ERS_PTA__c')
    pta_rows = [h for h in rows if h['Field'] == 'ERS_PTA__c']
    p0, p0_src = initial_pta(created, pta_rows, pta)
    due = parse_dt(s.get('ERS_PTA_Due__c'))
    due0 = due - timedelta(minutes=pta) + timedelta(minutes=p0) if (due and pta is not None and p0 is not None) else None

    events = ([{'ts': iso(parse_dt(h['CreatedDate'])), 'field': 'assigned', 'driver': h.get('NewValue'),
                'driver_id': name_to_id.get(h.get('NewValue')), **_actor(h, driver_users)} for h in assign]
              + [{'ts': iso(t), 'field': 'status', 'value': n, **_actor(h, driver_users)} for t, n, h in status]
              + [{'ts': iso(parse_dt(h['CreatedDate'])), 'field': 'territory', 'from': h.get('OldValue'),
                  'to': h.get('NewValue'), **_actor(h, driver_users)} for h in moves]
              + [{'ts': iso(parse_dt(h['CreatedDate'])), 'field': 'pta', 'from': h.get('OldValue'),
                  'to': h.get('NewValue'), **_actor(h, driver_users)} for h in pta_rows])
    events.sort(key=lambda e: e['ts'])
    pick_ev = lambda h: {'ts': iso(parse_dt(h['CreatedDate'])), 'driver': h['NewValue'], **_actor(h, driver_users)}
    return {
        'id': s['Id'], 'number': s.get('AppointmentNumber'), 'woli_id': s.get('ParentRecordId'),
        'work_type': wt, 'is_drop_off': 'drop' in wt.lower(), 'call_class': call_class(wt),
        'in_day': created >= day_start, 'status': s.get('Status'), 'created': iso(created),
        'lat': s.get('Latitude'), 'lon': s.get('Longitude'), 'city': s.get('City'),
        'postal_code': s.get('PostalCode'),
        'pta_min': pta, 'pta_due': iso(due),
        'pta_initial_min': p0, 'pta_initial_src': p0_src, 'pta_initial_due': iso(due0),
        'auto_schedule_requested': iso(parse_dt(s.get('Auto_Schedule_Requested__c'))),
        'priority': s.get('ERS_Dynamic_Priority__c'), 'duration_planned_min': s.get('FSL__Duration_In_Minutes__c'),
        'required_skills': sorted(x for x in req_by_woli.get(s.get('ParentRecordId'), ()) if x),
        'channel': channel, 'driver_type': driver_type, 'final_driver_id': driver, 'no_ar_fallback': fallback,
        'dispatch_method_formula': s.get('ERS_Dispatch_Method__c'),
        'off_platform_driver': (s.get('Off_Platform_Driver__r') or {}).get('Name'),
        'cancel_reason': s.get('ERS_Cancellation_Reason__c'),
        'decision': {
            'final': pick_ev(picks[-1]) if picks and driver else None,
            'first': pick_ev(picks[0]) if picks else None,
            'n_picks': len(picks),
            'n_pre_dispatch_picks': sum(1 for t in pick_ts if t_disp is None or t < t_disp),
            'pullbacks': pullbacks,
            'reassign_after_dispatch': sum(1 for t in pick_ts if t_disp and t > t_disp),
            'ar_creator': {'name': (ar.get('CreatedBy') or {}).get('Name'), 'created': ar.get('CreatedDate')} if ar else None,
            'scheduling_policy': s.get('FSL__Scheduling_Policy_Used__c'),
        },
        'events': events,
        'territory_moves': {'in': len(moves), 'from': [h['OldValue'] for h in moves]},
        'milestones': {'t_first': iso(pick_ts[0]) if pick_ts else None, 't_asg': iso(t_asg),
                       't_disp': iso(t_disp), 't_acc': iso(t_acc), 't_er': iso(t_er), 't_ol': iso(t_ol),
                       't_end': iso(end[0]), 'end_status': end[1], 'actual_end': iso(aet),
                       'arrival': iso(arrival), 'arrival_source': arrival_src},
        'busy': [iso(t_asg), iso(busy_end)] if t_asg and busy_end and busy_end > t_asg else None,
    }


def initial_pta(created, rows: list, stored):
    """Spec 7.7: the last ERS_PTA__c value written <= 5 s after creation; same-second rows are chained
    Old -> New. No such row -> the stored value. Values <= 0 or >= 999 -> (None, 'invalid')."""
    early = sorted((h for h in rows if parse_dt(h['CreatedDate']) <= created + timedelta(seconds=PTA_INITIAL_WINDOW_S)),
                   key=lambda h: h['CreatedDate'])
    cur, src = None, 'history'
    while early:
        nxt = next((h for h in early if (h.get('OldValue') in (None, '') if cur is None else h.get('OldValue') == cur)), None)
        if nxt is None or nxt.get('NewValue') == cur:
            break
        cur = nxt.get('NewValue')
        early.remove(nxt)
    value = None
    try:
        value = float(cur) if cur is not None else None
    except (TypeError, ValueError):
        pass
    if value is None:
        value, src = stored, 'stored'
    if value is None or not 0 < value < 999:
        return None, 'invalid'
    return value, src


_sa_record = sa_record   # old name, kept for callers


def _add_candidates(r: dict, tl: Timelines, roster: list, open_jobs):
    """B6 candidate sets at every pick, plus free-capacity samples for the late rules (7.2)."""
    created = parse_dt(r['created'])
    req, final = set(r['required_skills']), r['final_driver_id']
    pool = roster + ([final] if final and final not in roster else [])
    r['candidate_sets'], r['decision_set_idx'] = [], None
    t_asg = parse_dt(r['milestones']['t_asg'])
    picks = [e for e in r['events'] if e['field'] == 'assigned' and e.get('driver')]
    if r['is_drop_off'] or not r['in_day']:
        r['free_samples'] = None
        return
    for i, e in enumerate(picks):
        t = parse_dt(e['ts'])
        c = []
        for d in pool:
            p = tl.position(d, t, GPS_MAX_AGE_MIN, GPS_FORWARD_SLACK_MIN)
            mi = miles(p[0], p[1], r['lat'], r['lon']) if p else None
            c.append([d, p[0] if p else None, p[1] if p else None, round(mi, 4) if mi is not None else None,
                      int(tl.qualified(d, req, t)), int(tl.on_shift(d, t)), open_jobs(d, t, r['id']),
                      round((t - p[2]).total_seconds() / 60, 1) if p else None, int(d in roster)])
        r['candidate_sets'].append({'event_idx': i, 'ts': e['ts'], 'c': c})
        if t == t_asg:
            r['decision_set_idx'] = i
    r['free_samples'] = None
    if final and t_asg and r['lat'] is not None:
        t_er = parse_dt(r['milestones']['t_er'])
        series = lambda a, b: [_free_at(t, r, tl, roster, open_jobs, req, t_asg) for t in _steps(a, b)]
        r['free_samples'] = {'step_min': SAMPLE_STEP_MIN, 'pre': series(created, t_asg),
                             'queue': series(t_asg, t_er) if t_er else []}


def _steps(a, b):
    t = a
    while t <= b:
        yield t
        t += timedelta(minutes=SAMPLE_STEP_MIN)


def _free_at(t, r, tl, roster, open_jobs, req, caps_at) -> list:
    """[[driver_id, miles]] for free (0 open jobs), on-shift, qualified, fresh-GPS drivers other
    than the pick. Qualification uses truck capabilities at the decision time, as Henry's script."""
    out = []
    for d in roster:
        if d == r['final_driver_id'] or not tl.on_shift(d, t) or open_jobs(d, t):
            continue
        if not tl.qualified(d, req, caps_at):
            continue
        p = tl.position(d, t, GPS_MAX_AGE_MIN, GPS_FORWARD_SLACK_MIN)
        if p:
            out.append([d, round(miles(p[0], p[1], r['lat'], r['lon']), 4)])
    return out


def _driver_record(d, names, dtype, ttype, home, tl: Timelines, member: bool, sas: list) -> dict:
    keep = [parse_dt(e['ts']) for r in sas for e in r['events'] if e.get('driver_id') == d]
    return {
        'id': d, 'name': names.get(d), 'driver_type': dtype.get(d),
        'channel': CHANNEL_MAP.get(dtype.get(d), 'unknown'), 'member': member,
        'territory_type': ttype.get(d),
        'home_base': {'lat': home.get(d, (None, None))[0], 'lon': home.get(d, (None, None))[1]},
        'skills': sorted(x for x in tl.skills.get(d, ()) if x),
        'logins': [{'start': iso(a), 'end': iso(b)} for a, b in tl.logins.get(d, ())],
        'trucks': [{'start': iso(a), 'end': iso(b), 'truck_id': aid, 'truck': tl.truck_names.get(aid),
                    'truck_caps': sorted(tl.caps.get(aid, ()))} for a, b, aid in tl.trucks.get(d, ())],
        'absences': [{'start': iso(a), 'end': iso(b), 'type': t} for a, b, t in tl.absences.get(d, ())],
        'gps': tl.gps_track(d, keep_at=keep),
    }


def _warnings(sas: list) -> list:
    out = []
    no_ar = sum(1 for r in sas if r['in_day'] and r['decision']['ar_creator'] is None)
    if no_ar:
        out.append(f'{no_ar} SAs have no AssignedResource (canceled; driver taken from history when known)')
    return out
