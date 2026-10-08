"""Replay extras, pure rules: member calls, member texts and the driver's other jobs (replay-v2 design, Henry's H2-H4).
No Salesforce here: replay_extras_pull.py reads the rows, this module turns them into the /api/call-story/extras answer.
Phones, street addresses and message bodies never appear in the output.

Channels: fleet / on_platform / towbook. Towbook drivers are never named (the garage placeholder is not a person)."""

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from utils import parse_dt

FAR = datetime(9999, 1, 1, tzinfo=timezone.utc)
ACTIVE = {'dispatched', 'accepted', 'en route', 'on location'}
TERMINAL = {'completed', 'unable to complete', 'canceled', 'cancel call - service not en route', 'cancel call - service en route',
            'no-show', 'declined', 'rejected', 'cannot complete', 'cleared', 'abandoned', 'transferred'}
CALLBACK_MIN = 15           # owner rule: a call this long after the work order was created is a callback
WINDOW_BEFORE = timedelta(minutes=30)
WINDOW_AFTER = timedelta(minutes=60)
MAX_WINDOW = timedelta(hours=24)
LABELS = {'dispatched': 'not started', 'accepted': 'not started', 'en route': 'driving to it', 'on location': 'at the job', 'towing': 'towing'}
RANK = {'towing': 3, 'on location': 2, 'en route': 1}
LEVELS = {'bad': 0, 'warn': 1, 'info': 2}
TOWBOOK_NOTE = 'The Towbook garage did not report which driver took this call.'
NO_PHONE_NOTE = 'No phone number on this work order, so member calls cannot be matched.'
LIMIT_NOTES = {
    'fleet': 'A job the driver held when this call was given to them, and later lost to another driver, is not found.',
    'towbook': 'Towbook does not record driver swaps, so only the last driver is checked.',
}
TIMES_NOTE = 'Status times are when the driver tapped the app, so a real arrival can be earlier.'


def _is_drop(wt) -> bool:
    return 'drop' in (wt or '').lower()


def _wt(sa: dict) -> str:
    return (sa.get('WorkType') or {}).get('Name') or ''


def _is_id(v) -> bool:
    return str(v or '').startswith('0Hn')


def _iso(dt) -> str | None:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def _plural(n: int, one: str, many: str) -> str:
    return f'{n} {one if n == 1 else many}'


# ---- the member leg ---------------------------------------------------------------------------------------------

def _rows(history, sa_id=None):
    """(time, field, new value) of the history rows of one SA (or all), oldest first."""
    rows = [(parse_dt(h['CreatedDate']), h.get('Field'), h.get('NewValue'), h.get('ServiceAppointmentId')) for h in history]
    return sorted((r for r in rows if sa_id is None or r[3] == sa_id), key=lambda r: r[0])


def _resource_names(raw: dict) -> dict:
    """{ServiceResource id: (name, driver type)}: from AssignedResource, else the name row written with each id row."""
    out = {a['ServiceResourceId']: ((a.get('ServiceResource') or {}).get('Name'), (a.get('ServiceResource') or {}).get('ERS_Driver_Type__c'))
           for a in raw.get('assigned') or [] if a.get('ServiceResourceId')}
    pairs = defaultdict(list)
    for h in raw.get('history') or []:
        if h.get('Field') == 'ERS_Assigned_Resource__c' and h.get('NewValue'):
            pairs[(h['ServiceAppointmentId'], h['CreatedDate'])].append(h['NewValue'])
    for vals in pairs.values():
        ids, names = [v for v in vals if _is_id(v)], [v for v in vals if not _is_id(v)]
        if len(ids) == 1 and len(names) == 1 and ids[0] not in out:
            out[ids[0]] = (names[0], None)
    return out


def _channel(name, dtype, off_platform) -> str:
    if (dtype or '') == 'Off-Platform Contractor Driver' or (name or '').lower().startswith('towbook'):
        return 'towbook'
    if dtype == 'On-Platform Contractor Driver':
        return 'on_platform'
    if dtype == 'Fleet Driver':
        return 'fleet'
    return 'towbook' if off_platform else 'fleet'


def member_context(raw: dict, now: datetime) -> dict:
    """Everything the extras need to know about the member's call, from the story raw (no Salesforce).
    driver is None when nobody was ever given the call; then there is no driver-load section."""
    sas = raw.get('sas') or []
    member = next((s for s in sas if not _is_drop(_wt(s))), sas[0] if sas else None) or {}
    created = parse_dt(raw['wo']['CreatedDate'])
    rows = _rows(raw.get('history') or [], member.get('Id'))
    status = [(t, (v or '')) for t, f, v, _ in rows if f == 'Status']
    first_er = next((t for t, v in status if v.lower() == 'en route'), FAR)
    holders = [(t, v) for t, f, v, _ in rows if f == 'ERS_Assigned_Resource__c' and _is_id(v)]
    names = _resource_names(raw)
    final = holders[-1][1] if holders else None
    name, dtype = names.get(final, (None, None))
    chan = _channel(name, dtype, bool(member.get('Off_Platform_Driver__c')))
    if chan == 'towbook':
        driver = member.get('Off_Platform_Driver__c')
        given = [t for t, v in status if v.lower() == 'dispatched' and t <= first_er]
    else:
        driver = final
        given = [t for t, v in holders if v == final and t <= first_er] or [t for t, v in status if v.lower() == 'dispatched' and t <= first_er]
    ended = [t for t, v in status if v.lower() in TERMINAL]
    on_loc = next((t for t, v in status if v.lower() == 'on location'), None)
    w_end = min(((ended[-1] if ended else now) + WINDOW_AFTER), created + MAX_WINDOW)
    return {
        'created': created, 'member': member, 'channel': chan, 'driver': driver, 'given': given[-1] if given else None,
        'driver_name': None if chan == 'towbook' else name, 'on_location': on_loc,
        'end': on_loc or (ended[-1] if ended else None) or now, 'w_end': max(w_end, created + WINDOW_BEFORE),
        'w_start': created - WINDOW_BEFORE, 'member_wo': member.get('ERS_Work_Order__c') or (raw.get('wo') or {}).get('Id'),
    }


# ---- the driver's other jobs ------------------------------------------------------------------------------------

class _Trail:
    """Status and holder history per SA, from the 'trail' query."""

    def __init__(self, rows: list):
        self.status, self.holder = defaultdict(list), defaultdict(list)
        for r in sorted(rows, key=lambda r: parse_dt(r['CreatedDate'])):
            t, sid, v = parse_dt(r['CreatedDate']), r['ServiceAppointmentId'], r.get('NewValue')
            if r.get('Field') == 'Status':
                self.status[sid].append((t, v or ''))
            elif r.get('Field') == 'ERS_Assigned_Resource__c' and (v is None or _is_id(v)):
                self.holder[sid].append((t, v))

    def status_at(self, sid, t):
        last = [v for c, v in self.status[sid] if c <= t]
        return last[-1] if last else None

    def holder_at(self, sid, t):
        last = [v for c, v in self.holder[sid] if c <= t]
        return last[-1] if last else None

    def first(self, sid, value):
        return next((c for c, v in self.status[sid] if v.lower() == value), None)


def _handed(tr: _Trail, job: dict, driver: str, towbook: bool, before=FAR):
    """When this leg was given to the driver: Towbook = last Dispatched; FSL = last ERS_Assigned_Resource__c id row = driver."""
    if towbook:
        xs = [c for c, v in tr.status[job['Id']] if v.lower() == 'dispatched' and c <= before]
    else:
        xs = [c for c, v in tr.holder[job['Id']] if v == driver and c <= before]
    return xs[-1] if xs else None


def _leg_state(tr: _Trail, job: dict, driver: str, towbook: bool, t):
    st = (tr.status_at(job['Id'], t) or '').lower()
    if _is_drop(_wt(job)):
        return 'towing' if st in ('en route', 'on location') else None
    if st not in ACTIVE:
        return None
    if towbook:
        return st if _handed(tr, job, driver, True, t) else None
    return st if tr.holder_at(job['Id'], t) == driver else None


def on_plate(jobs: list, tr: _Trail, ctx: dict, at) -> dict:
    """{work order id: {'state', 'job'}} for the WOs on the driver's plate at `at` (one WO counts once; towing wins)."""
    towbook = ctx['channel'] == 'towbook'
    legs = defaultdict(list)
    for j in jobs:
        if j.get('ERS_Work_Order__c') and j['ERS_Work_Order__c'] != ctx['member_wo']:
            legs[j['ERS_Work_Order__c']].append(j)
    out = {}
    for w, js in legs.items():
        found = [(s, j) for j in js if (s := _leg_state(tr, j, ctx['driver'], towbook, at))]
        if not found:
            continue
        state = 'towing' if any(s == 'towing' for s, _ in found) else max((s for s, _ in found), key=lambda s: RANK.get(s, 0))
        pick = next((j for _, j in found if not _is_drop(_wt(j))), None) or next((j for j in js if not _is_drop(_wt(j))), found[0][1])
        out[w] = {'state': state, 'job': pick}
    return out


def jumped_ahead(jobs: list, tr: _Trail, ctx: dict, plate: dict) -> list:
    """WOs not on the plate when the call was given, given to the driver afterwards and reached before the member was."""
    towbook, A, end = ctx['channel'] == 'towbook', ctx['given'], ctx['end']
    legs = defaultdict(list)
    for j in jobs:
        if j.get('ERS_Work_Order__c') and j['ERS_Work_Order__c'] != ctx['member_wo'] and not _is_drop(_wt(j)):
            legs[j['ERS_Work_Order__c']].append(j)
    out = []
    for w, js in legs.items():
        if w in plate:
            continue
        given = [h for j in js if (h := _handed(tr, j, ctx['driver'], towbook))]
        reached = [r for j in js if (r := tr.first(j['Id'], 'on location'))]
        if given and A < min(given) < end and reached and min(reached) < end:
            out.append({'job': js[0], 'given_at': min(given), 'reached_at': min(reached)})
    return sorted(out, key=lambda x: x['given_at'])


def _job_view(j: dict, tr: _Trail) -> dict:
    lat, lon = j.get('Latitude'), j.get('Longitude')
    return {'sa': j.get('AppointmentNumber'), 'wo': (j.get('ERS_Work_Order__r') or {}).get('WorkOrderNumber'), 'work_type': _wt(j),
            'lat': None if lat is None or _is_drop(_wt(j)) else round(lat, 4),
            'lon': None if lon is None or _is_drop(_wt(j)) else round(lon, 4)}


def driver_load(ctx: dict, jobs: list, trail_rows: list) -> dict | None:
    """Section 'driver_load' (one driver) or None when no driver or no 'given' moment."""
    if not ctx['driver'] or not ctx['given']:
        return None
    tr = _Trail(trail_rows)
    plate = on_plate(jobs, tr, ctx, ctx['given'])
    ahead = []
    for w, p in plate.items():
        j = p['job']
        ahead.append({**_job_view(j, tr), 'state': p['state'], 'label': LABELS[p['state']], 'is_current': p['state'] in RANK,
                      'on_location': _iso(tr.first(j['Id'], 'on location'))})
    ahead.sort(key=lambda a: (-RANK.get(a['state'], 0), a['wo'] or ''))
    current = next((a for a in ahead if a['is_current']), None)
    after = [{**_job_view(x['job'], tr), 'given_at': _iso(x['given_at']), 'reached_at': _iso(x['reached_at'])}
             for x in jumped_ahead(jobs, tr, ctx, plate)]
    return {'driver': ctx['driver_name'] or 'Towbook Driver', 'channel': ctx['channel'], 'given_at': _iso(ctx['given']),
            'current': current and {k: current[k] for k in ('sa', 'wo', 'work_type', 'state', 'label')},
            'ahead': ahead, 'after': after, 'jobs_in_window': len({j.get('ERS_Work_Order__c') for j in jobs} - {ctx['member_wo']})}


# ---- member calls and texts -------------------------------------------------------------------------------------

def _mins(t, created) -> float:
    return round((t - created).total_seconds() / 60, 1)


def build_calls(rows: list, created: datetime) -> list:
    """One entry per member call. Only CallType 'Inbound' counts; 'Transfer' rows are folded into their parent call.
    kind: original (< 15 min after the WO was created), callback (>= 15 min, on an 'MCC ERS' line), membership_line (other)."""
    by_id = {r['Id']: r for r in rows}

    def root(r, hops=0):
        prev = by_id.get(r.get('PreviousCallId'))
        return r if (r.get('CallType') or '').lower() == 'inbound' or not prev or hops > 6 else root(prev, hops + 1)

    parents = {r['Id']: [] for r in rows if (r.get('CallType') or '').lower() == 'inbound'}
    for r in rows:
        if (r.get('CallType') or '').lower() == 'transfer':
            top = root(r)
            if top['Id'] in parents:
                parents[top['Id']].append(r)
    out = []
    for r in sorted((r for r in rows if r['Id'] in parents), key=lambda r: r['CallStartDateTime']):
        ts = parse_dt(r['CallStartDateTime'])
        after = _mins(ts, created)
        line = r.get('ToPhoneNumber') or ''
        kind = 'original' if after < CALLBACK_MIN else 'callback' if line.upper().startswith('MCC ERS') else 'membership_line'
        out.append({'id': f'c{len(out) + 1}', 'ts': _iso(ts), 'end': _iso(parse_dt(r.get('CallEndDateTime'))),
                    'answered_at': _iso(parse_dt(r.get('CallAcceptDateTime'))), 'duration_s': r.get('CallDurationInSeconds'),
                    'line': line, 'kind': kind, 'min_after_create': after, 'direction': 'inbound',
                    'agent': (r.get('User') or {}).get('Name'),
                    'transfers': [{'ts': _iso(parse_dt(t['CallStartDateTime'])), 'to': t.get('ToPhoneNumber'), 'agent': (t.get('User') or {}).get('Name')}
                                  for t in sorted(parents[r['Id']], key=lambda t: t['CallStartDateTime'])]})
    return out


def is_ers_sms(session: dict) -> bool:
    ch = session.get('MessagingChannel') or {}
    return any('ers sms' in str(ch.get(k) or '').replace('_', ' ').lower() for k in ('MasterLabel', 'DeveloperName'))


def build_texts(rows: list, created: datetime) -> list:
    """Inbound texts: one per member-started messaging session on the ERS SMS channel (a session, not a message)."""
    out = []
    for r in sorted(rows, key=lambda r: r['CreatedDate']):
        if r.get('Origin') != 'InboundInitiated' or not is_ers_sms(r):
            continue
        ts = parse_dt(r.get('StartTime') or r['CreatedDate'])
        out.append({'id': f't{len(out) + 1}', 'ts': _iso(ts), 'end': _iso(parse_dt(r.get('EndTime'))), 'min_after_create': _mins(ts, created),
                    'agent': (r.get('Owner') or {}).get('Name'), 'messages': r.get('EndUserMessageCount')})
    return out


# ---- insights (Henry's wording, H4) -----------------------------------------------------------------------------

def _late(items: list, promise, key='ts') -> list:
    return [x for x in items if promise and parse_dt(x[key]) > promise]


def short_driver_name(name: str) -> str:
    """Salesforce adds the garage's truck number to a driver's name ("Marcus Gibson 100"); people say "Marcus Gibson". Same rule as the Garage view."""
    return re.sub(r'\s+\d{2,3}[A-Z]{0,2}$', '', name or '')


def build_insights(calls: list, texts: list, load: dict | None, promise, on_location) -> list:
    out = []
    backs = [c for c in calls if c['kind'] == 'callback']
    if backs:
        late = _late(backs, promise)
        before_arrival = [c for c in late if on_location is None or parse_dt(c['ts']) < on_location]
        text = f"The member called AAA back {_plural(len(backs), 'time', 'times')}. The first call came {round(backs[0]['min_after_create'])} min after they asked for help."
        if late:
            text += f' {len(late)} of these came after the promised arrival time.'
        level = 'bad' if before_arrival else 'warn' if len(backs) >= 2 or late else 'info'
        out.append({'code': 'CALLED_BACK', 'level': level, 'text': text, 'ts': backs[0]['ts']})
    if texts:
        late = _late(texts, promise)
        text = f"The member texted AAA {_plural(len(texts), 'time', 'times')}." + (f' {len(late)} came after the promised arrival time.' if late else '')
        out.append({'code': 'TEXTED_IN', 'level': 'warn' if late else 'info', 'text': text, 'ts': texts[0]['ts']})
    if load:
        who = short_driver_name(load['driver']) if load['channel'] != 'towbook' else 'the Towbook driver'
        if load['ahead']:
            n = len(load['ahead'])
            text = f"When this call went to {who}, they still had {_plural(n, 'other job', 'other jobs')} to finish first."
            if load['current']:
                text += f" One was already {load['current']['label']}."
            out.append({'code': 'DRIVER_AHEAD', 'level': 'warn' if n >= 2 else 'info', 'text': text, 'ts': load['given_at']})
        if load['after']:
            n = len(load['after'])
            arrived_late = bool(promise and on_location and on_location > promise)
            out.append({'code': 'DRIVER_MORE_AFTER', 'level': 'bad' if arrived_late else 'warn', 'ts': load['after'][0]['given_at'],
                        'text': f"{who[0].upper() + who[1:]} served {_plural(n, 'member', 'members')} who called later before reaching this member."})
    return sorted(out, key=lambda i: LEVELS[i['level']])[:4]


def build_extras(ctx: dict, jobs: list, trail_rows: list, voice: list, sessions: list, promise, notes: list) -> dict:
    """The public /extras answer (minus sf_calls / cache, added by the router)."""
    created = ctx['created']
    calls, texts = build_calls(voice, created), build_texts(sessions, created)
    load = driver_load(ctx, jobs, trail_rows)
    notes = list(notes)
    if ctx['channel'] == 'towbook' and not ctx['driver']:
        notes.append(TOWBOOK_NOTE)
    if load:
        notes += [LIMIT_NOTES['towbook' if ctx['channel'] == 'towbook' else 'fleet'], TIMES_NOTE]
    return {'window': {'from': _iso(ctx['w_start']), 'to': _iso(ctx['w_end'])}, 'calls': calls, 'inbound_texts': texts,
            'thread_available': any((s.get('Conversation') or {}).get('ConversationIdentifier') for s in sessions if is_ers_sms(s)),
            'driver_load': [load] if load else [], 'insights': build_insights(calls, texts, load, promise, ctx['on_location']),
            'notes': notes}


def phone_digits(*values) -> list:
    """Distinct 10-digit numbers (last 10 digits of each value that has them)."""
    return sorted({d[-10:] for v in values if len(d := re.sub(r'\D', '', v or '')) >= 10})
