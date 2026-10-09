"""Garage Live: one garage's open tickets and drivers, assembled from reads that already exist (no Salesforce here).

  tickets   the shared Watchlist snapshot: every open appointment of the last 24 h with its drivers (AssignedResource) and status history
  drivers   ref_data: who is on shift (truck login), last GPS position (2 min copy), territory membership
  flags     the Watchlist's own alerts for this garage (same flags, same wording)

build() is pure (everything comes in as arguments) so the rules are tested with plain dicts. The router gathers the inputs.
Towbook garages have no driver GPS: their tickets are shown, their drivers never named or drawn.
"""

import re
import threading
from collections import deque
from datetime import datetime, timedelta, timezone

import ref_data
import watchlist_call_map as wcm
from garage_live_rules import THRESHOLDS, build_attention
from report_card_snapshot import miles
from utils import is_fleet_territory, parse_dt

ACTIVE_CATEGORIES = {'None', 'Scheduled', 'Dispatched', 'InProgress', 'CheckedIn'}
TERMINAL = {'completed', 'canceled', 'cancelled', 'cannot complete', 'unable to complete', 'no-show'}
ON_SCENE = {'on location', 'in progress'}
DRIVING = {'en route', 'travel'}
LIGHT_JOB = re.compile(r'battery|jump|lockout|lock.?out|tire|fuel|gas|diesel|miscellaneous|winch', re.I)
FSL_TYPES = {'Fleet Driver', 'On-Platform Contractor Driver'}
# Same leave-outs as the Command Center's driver list (test accounts, spares, spot trucks)
DRIVER_EXCLUDE = ('Test %', '000-%', '0 %', '100A %', '%SPOT%')
DRIVER_EXCLUDE_EXACT = ('Travel User',)
QUEUE_LABEL = {'on_scene': 'on scene', 'driving': 'driving to it', 'waiting': 'not started'}

# ── Where each driver was seen (for "has not moved in 15 min") ──
_trail: dict = {}
_trail_lock = threading.Lock()
TRAIL_KEEP = timedelta(minutes=40)


def reset_trail() -> None:
    with _trail_lock:
        _trail.clear()


def note_position(driver_id: str, lat, lon, now: datetime) -> float | None:
    """Remember where the driver is now; return how many minutes the position has stayed within the radius (None = unknown / no GPS)."""
    if lat is None:
        return None
    radius = THRESHOLDS['stationary_radius_mi']
    with _trail_lock:
        q = _trail.setdefault(driver_id, deque(maxlen=200))
        if not q or q[-1][0] < now:
            q.append((now, lat, lon))
        while q and now - q[0][0] > TRAIL_KEEP:
            q.popleft()
        first = now
        for t, la, lo in reversed(q):
            if miles(la, lo, lat, lon) > radius:
                break
            first = t
        return (now - first).total_seconds() / 60


def _dt(v) -> datetime | None:
    d = parse_dt(v) if v else None
    return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if d else None


def _mins(since: datetime | None, now: datetime) -> int | None:
    return max(0, int((now - since).total_seconds() // 60)) if since else None


def status_since(hist: list, status: str) -> datetime | None:
    """When the appointment last entered `status` (Status history), or None when history has no such row."""
    best = None
    for h in hist or []:
        if h.get('Field') == 'Status' and h.get('NewValue') == status:
            d = _dt(h.get('CreatedDate'))
            if d and (best is None or d > best):
                best = d
    return best


def is_open(sa: dict) -> bool:
    return sa.get('StatusCategory') in ACTIVE_CATEGORIES and (sa.get('Status') or '').lower() not in TERMINAL


def is_drop_off(sa: dict) -> bool:
    return 'drop' in ((sa.get('WorkType') or {}).get('Name') or '').lower()


def _current_ar(ars: list) -> dict | None:
    return ars[-1] if ars else None


def _is_towbook_resource(sr: dict) -> bool:
    return (sr.get('ERS_Driver_Type__c') or '').startswith('Off-Platform') or (sr.get('Name') or '').lower().startswith('towbook')


def promise_due(sa: dict) -> datetime | None:
    """Created + the promised minutes (ERS_PTA__c), the Watchlist's own definition of the promise."""
    created = _dt(sa.get('CreatedDate'))
    try:
        pta = float(sa.get('ERS_PTA__c'))
    except (TypeError, ValueError):
        return None
    return created + timedelta(minutes=pta) if created and 0 < pta <= 999 else None


def _job_status(status: str) -> str:
    s = (status or '').lower()
    return 'on_scene' if s in ON_SCENE else 'driving' if s in DRIVING else 'waiting'


def driver_state(jobs: list) -> tuple:
    """(status, current job, queue) from a driver's open jobs. A Tow Drop-Off that is moving means towing; it never counts as a call.
    status: free | waiting (has a job, not started) | driving | on_scene | towing."""
    status, cur, queue = 'free', None, []
    for j in sorted(jobs, key=lambda j: j.get('given_at') or ''):
        here = _job_status(j['status'])
        if j['drop']:
            if here != 'waiting' and wcm.RANK['towing'] >= wcm.RANK[status]:
                status, cur = 'towing', j
            continue
        queue.append({**j, 'label': QUEUE_LABEL[here], 'here': here})
        if wcm.RANK[here] > wcm.RANK[status] or (here == status and status == 'waiting' and cur is None):
            status, cur = here, j
    if cur and not cur['drop']:
        queue = [q for q in queue if q['sa_id'] != cur['sa_id']]
    return status, cur, queue


def _open_jobs(snap: dict, now: datetime) -> tuple[dict, dict]:
    """(jobs by driver id, current assignment by SA id) over every open appointment of the snapshot, so a driver's queue is complete
    even when it holds calls of another garage."""
    jobs, current = {}, {}
    for sa in snap['sas']:
        if not is_open(sa):
            continue
        ar = _current_ar(snap['ar_by_sa'].get(sa['Id']))
        sr = (ar or {}).get('ServiceResource') or {}
        if not ar or _is_towbook_resource(sr):
            current[sa['Id']] = {'towbook': bool(ar)}
            continue
        did = sr.get('Id') or ar.get('ServiceResourceId')
        since = status_since(snap['hist_by_sa'].get(sa['Id']), sa.get('Status'))
        given = _dt(ar.get('CreatedDate'))
        current[sa['Id']] = {'driver_id': did, 'driver_name': sr.get('Name'), 'given_at': given, 'since': since, 'sr': sr}
        jobs.setdefault(did, []).append({
            'sa_id': sa['Id'], 'sa': sa.get('AppointmentNumber'), 'number': sa.get('AppointmentNumber'), 'status': sa.get('Status'),
            'work_type': (sa.get('WorkType') or {}).get('Name'), 'is_light': bool(LIGHT_JOB.search((sa.get('WorkType') or {}).get('Name') or '')),
            'drop': is_drop_off(sa), 'territory_id': sa.get('ServiceTerritoryId'), 'given_at': _iso(given) or '',
            'since': since, 'lat': sa.get('Latitude'), 'lon': sa.get('Longitude')})
    return jobs, current


def _ticket(sa: dict, cur: dict, snap: dict, flags: list, now: datetime) -> dict:
    status = sa.get('Status') or ''
    st = (status or '').lower()
    waiting = st not in ON_SCENE
    since = status_since(snap['hist_by_sa'].get(sa['Id']), status)
    due = promise_due(sa)
    late_min = (now - due).total_seconds() / 60 if due and waiting else None
    created = _dt(sa.get('CreatedDate'))
    woli = (snap['wo_by_woli'].get(sa.get('ParentRecordId')) or {})
    not_accepted = None
    if st in ('dispatched', 'assigned') and cur.get('driver_id'):
        not_accepted = _mins(max(x for x in (since, cur.get('given_at')) if x) if (since or cur.get('given_at')) else None, now)
    return {
        'sa_id': sa['Id'], 'number': sa.get('AppointmentNumber'), 'status': status, 'work_type': (sa.get('WorkType') or {}).get('Name') or '',
        'woli_id': sa.get('ParentRecordId'), 'wo_number': (woli.get('wo') or {}).get('WorkOrderNumber') or '', 'wo_id': woli.get('wo_id') or '',
        'priority': (sa.get('WO_Priority_Code__c') or '').strip(), 'city': sa.get('City') or '', 'address': sa.get('Street') or '',
        'lat': sa.get('Latitude'), 'lon': sa.get('Longitude'),
        'created_at': _iso(created), 'promise_at': _iso(due), 'age_min': _mins(created, now),
        'late_min': round(late_min) if late_min is not None else None, 'late': wcm.lateness(late_min),
        'waiting': waiting, 'status_since': _iso(since), 'status_min': _mins(since, now), 'on_scene_at': _iso(since) if not waiting else None,
        'not_accepted_min': not_accepted, 'towbook': bool(cur.get('towbook')),
        'driver_id': cur.get('driver_id'), 'driver_name': None if cur.get('towbook') else cur.get('driver_name'),
        'flags': flags,
    }


def _driver(did: str, row: dict | None, jobs: list, truck: dict | None, snap_sr: dict, now: datetime, observe: bool) -> dict:
    status, cur, queue = driver_state(jobs)
    src = row or snap_sr or {}
    lat, lon = src.get('LastKnownLatitude'), src.get('LastKnownLongitude')
    gps = _dt(src.get('LastKnownLocationDate'))
    age = _mins(gps, now)
    stale = age is None or age > THRESHOLDS['gps_map_max_age_min']
    since = (cur or {}).get('since') if status != 'waiting' else (_dt(cur['given_at']) if cur else None)
    caps = [c.strip() for c in ((truck or {}).get('ERS_Truck_Capabilities__c') or '').split(';') if c.strip()]
    out = {
        'id': did, 'name': src.get('Name') or '', 'truck': ((truck or {}).get('Name') or '').split(' - ')[0] or None, 'caps': caps,
        'phone': (src.get('RelatedRecord') or {}).get('Phone') or None,
        'status': status, 'label': wcm.LABEL[status], 'status_since': _iso(since), 'status_min': _mins(since, now),
        'lat': None if stale else lat, 'lon': None if stale else lon, 'stale_position': stale, 'gps_at': _iso(gps), 'gps_age_min': age,
        'held': len(queue) + (1 if cur and not cur['drop'] else 0),
        'job': {k: cur[k] for k in ('sa_id', 'number', 'status', 'work_type', 'is_light', 'territory_id')} if cur else None,
        'queue': [{'sa_id': q['sa_id'], 'number': q['number'], 'work_type': q['work_type'], 'label': q['label'], 'territory_id': q['territory_id']} for q in queue],
        'stationary_min': None,
    }
    if observe and out['lat'] is not None:
        out['stationary_min'] = note_position(did, out['lat'], out['lon'], now)
    return out


def garage_kind(name: str, has_fsl_drivers: bool) -> str:
    return 'fleet' if is_fleet_territory(name) else 'on_platform' if has_fsl_drivers else 'towbook'


def build(garage_id: str, snap: dict, result: dict, driver_rows: list, truck_rows: list, member_rows: list,
          now: datetime, skills_provider=None, info: dict | None = None) -> dict | None:
    """The Garage Live body for one garage, or None when nothing is known about the garage id. info = {name, lat, lon} from the garages list
    (the garage's position and its name when it has no open call). skills_provider(woli_ids, driver_ids) ->
    ({woli: skills}, {driver: skills}) or None (unknown): without it the 'closer driver' rule stays silent."""
    sas = [s for s in snap['sas'] if is_open(s)]
    garage_sas = [s for s in sas if s.get('ServiceTerritoryId') == garage_id]
    terr = next((s.get('ServiceTerritory') or {} for s in snap['sas'] if s.get('ServiceTerritoryId') == garage_id), None)
    info = info or {}
    if terr is None and not info and not any(m.get('ServiceTerritoryId') == garage_id for m in member_rows):
        return None
    name = (terr or {}).get('Name') or info.get('name') or ''
    glat, glon = info.get('lat'), info.get('lon')
    phone = next((((s.get('AAA_ERS_Account_Facility__r') or {}).get('Phone')) for s in garage_sas if (s.get('AAA_ERS_Account_Facility__r') or {}).get('Phone')), None)

    jobs, current = _open_jobs(snap, now)
    drivers_all = {d['Id']: d for d in driver_rows if not any(ref_data.like(d.get('Name'), p) for p in DRIVER_EXCLUDE)
                   and (d.get('Name') or '').lower() not in {n.lower() for n in DRIVER_EXCLUDE_EXACT}}
    trucks = {t['ERS_Driver__c']: t for t in truck_rows}
    roster = {m['ServiceResourceId'] for m in member_rows if m.get('ServiceTerritoryId') == garage_id} & set(drivers_all)
    on_shift = {i for i in roster if i in trucks}

    flags_by_sa: dict = {}
    alerts = [a for a in result.get('operational_alerts', []) if a.get('territory_id') == garage_id]
    for a in alerts:
        if a.get('sa_id'):
            flags_by_sa.setdefault(a['sa_id'], []).append(a['flag'])
    tickets = [_ticket(s, current.get(s['Id'], {}), snap, flags_by_sa.get(s['Id'], []), now) for s in garage_sas if not is_drop_off(s)]

    holding = {current[s['Id']]['driver_id'] for s in garage_sas if current.get(s['Id'], {}).get('driver_id')}
    has_fsl = bool(roster) or bool(holding) or any((current.get(s['Id']) or {}).get('sr', {}).get('ERS_Driver_Type__c') in FSL_TYPES for s in garage_sas)
    kind = garage_kind(name, has_fsl)
    towbook = kind == 'towbook'

    drivers = []
    if not towbook:
        for did in sorted(on_shift | holding):
            snap_sr = next((c['sr'] for c in current.values() if c.get('driver_id') == did), {})
            drivers.append(_driver(did, drivers_all.get(did), jobs.get(did, []), trucks.get(did), snap_sr, now, observe=True))
    for t in tickets:
        t['driver_phone'] = next((d['phone'] for d in drivers if d['id'] == t['driver_id']), None)

    off = len(roster - on_shift - holding)
    free = sum(1 for d in drivers if d['status'] == 'free')
    summary = {'open_calls': len(tickets), 'waiting_calls': sum(1 for t in tickets if t['waiting']),
               'late_calls': sum(1 for t in tickets if (t['late_min'] or 0) >= THRESHOLDS['late_min']),
               'drivers': {'free': free, 'busy': len(drivers) - free, 'off': off}}

    notes = ['Towbook garage: no driver GPS, so only the tickets are shown.'] if towbook else []
    skills_for = _qualifier(tickets, drivers, trucks, skills_provider, notes)
    entries = [{'sa_id': next((t['sa_id'] for t in tickets if t['number'] == e.get('sa_number')), None), 'reason': e.get('reason')}
               for e in result.get('watchlist', []) if any(t['number'] == e.get('sa_number') for t in tickets)]
    attention = build_attention(tickets, drivers, alerts, entries, summary, skills_for, towbook=towbook)
    return {'garage': {'id': garage_id, 'name': name, 'kind': kind, 'lat': glat, 'lon': glon, 'phone': phone, 'has_gps': not towbook},
            'summary': summary, 'tickets': tickets, 'drivers': drivers, 'attention': attention, 'notes': notes,
            'thresholds': THRESHOLDS, 'watchlist_at': result.get('last_updated'), 'built_at': _iso(now)}


def _qualifier(tickets, drivers, trucks, provider, notes):
    """skills_for(ticket, driver) -> bool, reading the call's required skills and the drivers' skills once. Skills are only asked for when a
    free driver and a waiting call both exist; an unreadable answer silences the rule (never guesses)."""
    free = [d for d in drivers if d['status'] == 'free' and d.get('lat') is not None]
    wait = [t for t in tickets if t['waiting'] and not t['towbook'] and t.get('woli_id') and t.get('lat') is not None
            and (t.get('age_min') or 0) >= THRESHOLDS['suggest_after_min']]
    if not provider or not free or not wait:
        return lambda t, d: False
    got = provider(sorted({t['woli_id'] for t in wait}), sorted(d['id'] for d in free))
    if got is None:
        notes.append('Driver skills could not be read, so "closer driver" suggestions are off for now.')
        return lambda t, d: False
    by_woli, by_driver = got
    return lambda t, d: t['woli_id'] in by_woli and wcm.qualified(by_woli[t['woli_id']], by_driver.get(d['id'], set()), set(d.get('caps') or []))
