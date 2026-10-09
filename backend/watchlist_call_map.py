"""Watchlist call map: everything the full-window map of one open call needs, in ONE Salesforce composite request.

The request holds 5 SELECTs (no reference between them, so a failed one never blocks the others):
  sa        the call, its garage (name, phone, position) and the driver it is assigned to (position, phones, who assigned)
  contacts  Contact records under the garage's facility account that have a phone
  cases     every Case linked to the work order, with its Status history as a child query
  skills    the skills the work order line item requires
  drivers   the garage's on-shift (truck login, no absence) FSL drivers: skills, truck, last known position, open jobs
The story (steps), who is working it, and the member's calls and texts come from the cached call story and replay extras.

Pure helpers (no I/O) are at the top so they can be tested with plain dicts. SELECT only. Positions are the drivers' current
LastKnown fields (never the GPS history: that read takes 30 s or more). Distances are straight-line miles.
"""

import logging
from datetime import datetime, timedelta, timezone

from sf_client import sanitize_soql, sf_composite_query
from report_card_snapshot import miles
from utils import parse_dt

log = logging.getLogger('watchlist.callmap')

FSL_TYPES = ("'Fleet Driver'", "'On-Platform Contractor Driver'")
HUMAN_PROFILE = 'membership user'          # the human dispatcher in this org; Contact Center, System Admin and integration users are not
OPEN_CATEGORIES = ("'Scheduled'", "'Dispatched'", "'InProgress'")
GPS_MAX_AGE_MIN = 60                       # a driver whose last position is older than this is left off the map
MAX_PEERS = 12
MAX_CONTACTS = 3
LABEL = {'free': 'free', 'driving': 'driving to a job', 'on_scene': 'on a job', 'towing': 'towing', 'waiting': 'has a job, not started'}
RANK = {'free': 0, 'waiting': 1, 'driving': 2, 'on_scene': 3, 'towing': 4}


# ── pure helpers ────────────────────────────────────────────────────────────

def lateness(minutes_late) -> dict:
    """The member pin colour: none while not late, yellow up to 30 min late, orange 30 to under 90, red from 90 (the pin pulses)."""
    if minutes_late is None or minutes_late <= 0:
        return {'level': 'ok', 'minutes': 0}
    level = 'yellow' if minutes_late <= 30 else 'orange' if minutes_late < 90 else 'red'
    return {'level': level, 'minutes': int(round(minutes_late))}


def working_now(history: list, assigned: list, member_sa_id: str, now: datetime) -> dict | None:
    """The human dispatcher on the call: the most recent action on this SA (its history) or on its assigned-resource rows made by a
    user whose profile is 'Membership User'. AssignedResource.CreatedBy is the reliable assigner. Anyone else (Contact Center,
    System Admin, integration users, the optimizer) is NOT a dispatcher. Returns {name, at, minutes_ago, what} or None."""
    best = None
    for h in history or []:
        if h.get('ServiceAppointmentId') == member_sa_id:
            who = h.get('CreatedBy') or {}
            if ((who.get('Profile') or {}).get('Name') or '').lower() == HUMAN_PROFILE:
                best = _later(best, who.get('Name'), h.get('CreatedDate'), f"changed {h.get('Field')}")
    for a in assigned or []:
        who = a.get('CreatedBy') or {}
        if ((who.get('Profile') or {}).get('Name') or '').lower() == HUMAN_PROFILE:
            best = _later(best, who.get('Name'), a.get('CreatedDate'), 'assigned a driver')
    if not best:
        return None
    best['minutes_ago'] = max(0, int((now - parse_dt(best['at'])).total_seconds() // 60))
    return best


def _later(best, name, at, what):
    if not name or not at or (best and parse_dt(best['at']) >= parse_dt(at)):
        return best
    return {'name': name, 'at': at, 'what': what}


def contact_counts(extras: dict | None, steps: list) -> dict:
    """What the member did and what AAA sent: calls (original + callbacks), member texts, AAA texts, last contact from the member."""
    calls = [c for c in (extras or {}).get('calls') or [] if c.get('kind') in ('original', 'callback')]
    texts = (extras or {}).get('inbound_texts') or []
    out_texts = [s for s in steps if s.get('kind') == 'sms']
    stamps = [x['ts'] for x in calls + texts if x.get('ts')]
    return {'available': extras is not None, 'calls': len(calls), 'texts_in': len(texts), 'texts_out': len(out_texts),
            'last_member_contact': max(stamps, key=parse_dt) if stamps else None}


def strip_text_content(steps: list) -> list:
    """For people without the replay permission: the AAA texts keep their time and title but lose their message text."""
    return [{**s, 'detail': '', 'content': []} if s.get('kind') == 'sms' else s for s in steps]


def driver_state(jobs: list, this_sa: str | None = None) -> tuple:
    """(status, queue) from a driver's open jobs. queue = the other open calls in the order they were given (drop-offs only count as towing).
    Each job: {sa, status, work_type, lat, lon, given_at}."""
    status, queue = 'free', []
    for j in sorted(jobs, key=lambda j: j.get('given_at') or ''):
        if j['sa'] == this_sa:
            continue
        s, wt = (j.get('status') or '').lower(), (j.get('work_type') or '').lower()
        here = 'on_scene' if s == 'on location' else 'driving' if s == 'en route' else 'waiting'
        if 'drop' in wt:
            if here != 'waiting':
                status = max(status, 'towing', key=RANK.get)
            continue
        status = max(status, here, key=RANK.get)
        queue.append({**j, 'label': {'on_scene': 'on scene', 'driving': 'driving to it', 'waiting': 'not started'}[here]})
    return status, queue


def qualified(required: set, skills: set, caps: set) -> bool:
    """The Report Card rule: the call's required skills are a subset of the driver's skills plus the logged-in truck's capabilities."""
    return {r.lower() for r in required} <= ({x.lower() for x in skills} | {x.lower() for x in caps})


def _parse_jobs(sr: dict) -> list:
    out = []
    for ar in (sr.get('ServiceAppointments') or {}).get('records') or []:
        sa = ar.get('ServiceAppointment') or {}
        out.append({'sa': sa.get('AppointmentNumber'), 'status': sa.get('Status'), 'work_type': (sa.get('WorkType') or {}).get('Name'),
                    'lat': sa.get('Latitude'), 'lon': sa.get('Longitude'), 'given_at': ar.get('CreatedDate')})
    return out


def _phone(sr: dict) -> str | None:
    rec = sr.get('RelatedRecord') or {}
    return rec.get('MobilePhone') or rec.get('Phone') or None


def build_drivers(rows: list, required: set, member: tuple, this_sa: str, assigned_id: str | None, now: datetime, sa_status: str | None = None) -> tuple:
    """(peers, assigned_entry): the qualified, on-shift, fresh-GPS drivers other than the assigned one (nearest first, capped), and the
    assigned driver's own entry when the garage roster holds them. Drivers on shift but not qualified are counted, never listed."""
    peers, mine, not_qualified, no_gps = [], None, 0, 0
    for sr in rows:
        caps = {c.strip() for t in (sr.get('Assets__r') or {}).get('records') or [] for c in (t.get('ERS_Truck_Capabilities__c') or '').split(';') if c.strip()}
        skills = {(s.get('Skill') or {}).get('MasterLabel') for s in (sr.get('ServiceResourceSkills') or {}).get('records') or []} - {None}
        is_assigned = sr['Id'] == assigned_id
        if not is_assigned and (not (sr.get('Assets__r') or {}).get('records') or (sr.get('ResourceAbsences') or {}).get('records')):
            continue                                   # not logged in to a truck, or on an absence today: not on shift
        if not is_assigned and not qualified(required, skills, caps):
            not_qualified += 1
            continue
        gps = parse_dt(sr.get('LastKnownLocationDate'))
        fresh = gps is not None and now - gps <= timedelta(minutes=GPS_MAX_AGE_MIN)
        lat, lon = (sr.get('LastKnownLatitude'), sr.get('LastKnownLongitude')) if fresh else (None, None)
        if lat is None and not is_assigned:
            no_gps += 1
            continue
        status, queue = driver_state(_parse_jobs(sr), this_sa)
        if is_assigned:                                 # the assigned driver is also doing THIS call: its status counts
            s = (sa_status or '').lower()
            status = max(status, 'on_scene' if s == 'on location' else 'driving' if s == 'en route' else 'waiting', key=RANK.get)
        trucks = (sr.get('Assets__r') or {}).get('records') or []
        entry = {'id': sr['Id'], 'name': sr.get('Name'), 'phone': _phone(sr), 'truck': (trucks[0].get('Name') if trucks else None),
                 'skills': sorted(skills | caps), 'status': status, 'label': LABEL[status], 'held': len(queue), 'queue': queue,
                 'lat': lat, 'lon': lon, 'gps_at': sr.get('LastKnownLocationDate'),
                 'miles': round(miles(lat, lon, *member), 1) if lat is not None and member[0] is not None else None}
        if is_assigned:
            mine = entry
        else:
            peers.append(entry)
    peers.sort(key=lambda p: p['miles'] if p['miles'] is not None else 9999)
    return peers[:MAX_PEERS], mine, {'not_qualified': not_qualified, 'no_gps': no_gps}


def suggestion(sa_status: str, assigned: dict | None, peers: list) -> dict | None:
    """A free, qualified driver closer than the assigned one, while the member is still waiting for the assigned driver to arrive."""
    if (sa_status or '').lower() in ('on location', 'completed', 'canceled', 'cancelled', 'unable to complete', 'no-show'):
        return None
    free = [p for p in peers if p['held'] == 0 and p['status'] == 'free' and p['miles'] is not None]
    if not free:
        return None
    best = free[0]
    if assigned is None:
        return {'driver': best['name'], 'miles': best['miles'], 'text': f"{best['name']} is free, qualified and {best['miles']} mi away. No driver has the call yet."}
    if assigned.get('miles') is not None and best['miles'] >= assigned['miles']:
        return None
    ahead = assigned['held']
    tail = (f"The assigned driver, {assigned['name']}, has {ahead} job{'s' if ahead != 1 else ''} ahead." if ahead
            else f"The assigned driver, {assigned['name']}, is {assigned['miles']} mi away." if assigned.get('miles') is not None
            else f"The assigned driver, {assigned['name']}, has no recent GPS position.")
    return {'driver': best['name'], 'miles': best['miles'], 'text': f"{best['name']} is free, qualified and {best['miles']} mi away. {tail}".strip()}


def case_events(cases: list) -> list:
    """Case rows (with their Status history) as timeline events: created, each status change, closed."""
    out = []
    for c in cases:
        base = {'case_id': c['Id'], 'number': c.get('CaseNumber'), 'subject': c.get('Subject') or '',
                'kind_of': ' · '.join(x for x in ((c.get('RecordType') or {}).get('Name'), c.get('Type'), c.get('Reason')) if x)}
        who = (c.get('CreatedBy') or {}).get('Name')
        out.append({**base, 'id': f"case:{c['Id']}:created", 'ts': c['CreatedDate'], 'type': 'case_created', 'by': who,
                    'title': f"Case {c.get('CaseNumber')} opened", 'detail': ' · '.join(x for x in (base['kind_of'], base['subject'], f'by {who}' if who else '') if x)})
        for h in (c.get('Histories') or {}).get('records') or []:
            if h.get('Field') == 'Status' and h.get('NewValue') and h.get('OldValue') is not None:
                out.append({**base, 'id': f"case:{c['Id']}:{h['CreatedDate']}", 'ts': h['CreatedDate'], 'type': 'case_status',
                            'by': (h.get('CreatedBy') or {}).get('Name'), 'title': f"Case {c.get('CaseNumber')}: {h.get('OldValue')} to {h['NewValue']}", 'detail': ''})
        if c.get('IsClosed') and c.get('ClosedDate'):
            out.append({**base, 'id': f"case:{c['Id']}:closed", 'ts': c['ClosedDate'], 'type': 'case_closed', 'by': None,
                        'title': f"Case {c.get('CaseNumber')} closed", 'detail': c.get('Status') or ''})
    return sorted(out, key=lambda e: parse_dt(e['ts']))


def case_summary(cases: list) -> dict:
    open_ = [c for c in cases if not c.get('IsClosed')]
    return {'count': len(cases), 'open': len(open_), 'numbers': [c.get('CaseNumber') for c in (open_ or cases)][:3],
            'items': [{'id': c['Id'], 'number': c.get('CaseNumber'), 'status': c.get('Status'), 'is_closed': bool(c.get('IsClosed')),
                       'subject': c.get('Subject') or '', 'type': c.get('Type'), 'reason': c.get('Reason')} for c in cases]}


# ── the one Salesforce request ──────────────────────────────────────────────

AR_SUB = """(SELECT ServiceResourceId, ServiceResource.Name, ServiceResource.LastKnownLatitude, ServiceResource.LastKnownLongitude,
   ServiceResource.LastKnownLocationDate, ServiceResource.ERS_Driver_Type__c, ServiceResource.RelatedRecord.Phone,
   ServiceResource.RelatedRecord.MobilePhone, CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name
   FROM ServiceResources ORDER BY CreatedDate)"""
JOBS_SUB = f"""(SELECT ServiceAppointment.AppointmentNumber, ServiceAppointment.Status, ServiceAppointment.WorkType.Name,
   ServiceAppointment.Latitude, ServiceAppointment.Longitude, CreatedDate FROM ServiceAppointments
   WHERE ServiceAppointment.StatusCategory IN ({','.join(OPEN_CATEGORIES)}))"""


def queries(sa_id: str, geo: bool, towbook: bool, lat: float | None = None, lon: float | None = None) -> dict:
    """The named SOQL of the composite. geo = the call sits in a 000 (unassigned) queue: drivers are picked by a box around the call
    (about 70 miles), not by garage. towbook = no driver GPS exists, so the drivers query is left out. Salesforce allows 2 semi-joins
    per query, so the garage roster uses one (through a reference to the sa result) and the rest is filtered in Python."""
    s = sanitize_soql(sa_id)
    sa_of = f"SELECT {{f}} FROM ServiceAppointment WHERE Id = '{s}'"
    scope = ("AND Id IN (SELECT ServiceResourceId FROM ServiceTerritoryMember WHERE ServiceTerritoryId = '@{sa.records[0].ServiceTerritoryId}' "
             "AND EffectiveStartDate <= TODAY AND (EffectiveEndDate = null OR EffectiveEndDate >= TODAY))")
    if geo:
        if lat is None or lon is None:
            towbook = True
        else:
            scope = (f"AND LastKnownLatitude > {float(lat) - 1} AND LastKnownLatitude < {float(lat) + 1} "
                     f"AND LastKnownLongitude > {float(lon) - 1.4} AND LastKnownLongitude < {float(lon) + 1.4}")
    q = {
        'sa': f"""SELECT Id, AppointmentNumber, Status, StatusCategory, CreatedDate, ERS_PTA__c, ERS_PTA_Due__c, ParentRecordId,
               ERS_Work_Order__c, ERS_Work_Order__r.WorkOrderNumber, WorkType.Name, WO_Priority_Code__c, City, Latitude, Longitude,
               ServiceTerritoryId, ServiceTerritory.Name, ServiceTerritory.Latitude, ServiceTerritory.Longitude,
               AAA_ERS_Account_Facility__c, AAA_ERS_Account_Facility__r.Name, AAA_ERS_Account_Facility__r.Phone, {AR_SUB}
               FROM ServiceAppointment WHERE Id = '{s}'""",
        'contacts': f"""SELECT Name, Title, Phone, MobilePhone, Mobile_Phone__c FROM Contact
               WHERE AccountId IN ({sa_of.format(f='AAA_ERS_Account_Facility__c')})
               AND (Phone != null OR MobilePhone != null OR Mobile_Phone__c != null) ORDER BY LastModifiedDate DESC LIMIT 10""",
        'cases': f"""SELECT Id, CaseNumber, Status, Subject, Type, Reason, RecordType.Name, CreatedDate, ClosedDate, IsClosed, CreatedBy.Name,
               (SELECT Field, OldValue, NewValue, CreatedDate, CreatedBy.Name FROM Histories WHERE Field = 'Status' ORDER BY CreatedDate)
               FROM Case WHERE ERS_Work_Order__c IN ({sa_of.format(f='ERS_Work_Order__c')}) ORDER BY CreatedDate""",
        'skills': f"SELECT Skill.MasterLabel FROM SkillRequirement WHERE RelatedRecordId IN ({sa_of.format(f='ParentRecordId')})",
    }
    if not towbook:
        q['drivers'] = f"""SELECT Id, Name, ERS_Driver_Type__c, LastKnownLatitude, LastKnownLongitude, LastKnownLocationDate,
               RelatedRecord.Phone, RelatedRecord.MobilePhone, (SELECT Skill.MasterLabel FROM ServiceResourceSkills),
               (SELECT Name, ERS_Truck_Capabilities__c FROM Assets__r WHERE RecordType.Name = 'ERS Truck'),
               (SELECT Id FROM ResourceAbsences WHERE Start <= TODAY AND End >= TODAY), {JOBS_SUB}
               FROM ServiceResource WHERE IsActive = true AND ERS_Driver_Type__c IN ({','.join(FSL_TYPES)}) AND LastKnownLatitude != null {scope}"""
    return q


def pull(sa_id: str, geo: bool, towbook: bool, lat=None, lon=None) -> dict:
    """{key: records} from one composite request. 'sa' failing is fatal; the others degrade to empty with a note in 'errors'."""
    got = sf_composite_query(queries(sa_id, geo, towbook, lat, lon))
    out, errors = {}, []
    for key, r in got.items():
        if r['status'] == 200:
            out[key] = r['body'].get('records', [])
        else:
            out[key] = []
            errors.append(key)
            log.warning('call map query %s failed: %s %s', key, r['status'], str(r['body'])[:200])
    if 'sa' in errors or not out.get('sa'):
        raise LookupError('That service appointment could not be read.')
    out['errors'], out['geo'] = errors, geo
    return out


def assemble(sf: dict, story_bits: dict, now: datetime, geo_radius_mi: float = 60.0) -> dict:
    """The endpoint body from the composite answer and the story pieces (history, steps, extras, promise)."""
    sa = sf['sa'][0]
    member = (sa.get('Latitude'), sa.get('Longitude'))
    ars = (sa.get('ServiceResources') or {}).get('records') or []
    cur = None if story_bits.get('towbook') else (ars[-1] if ars else None)       # Towbook drivers are never named: only the garage is known
    assigned_id = cur['ServiceResourceId'] if cur else None
    required = {(r.get('Skill') or {}).get('MasterLabel') for r in sf.get('skills', [])} - {None}
    rows = sf.get('drivers', [])
    if cur and not any(r['Id'] == assigned_id for r in rows):          # a driver from another garage: still shown, with no queue
        rec = cur.get('ServiceResource') or {}
        rows = rows + [{'Id': assigned_id, 'Name': rec.get('Name'), 'LastKnownLatitude': rec.get('LastKnownLatitude'),
                        'LastKnownLongitude': rec.get('LastKnownLongitude'), 'LastKnownLocationDate': rec.get('LastKnownLocationDate'),
                        'RelatedRecord': rec.get('RelatedRecord'), '_outside': True}]
    peers, mine, counts = build_drivers(rows, required, member, sa.get('AppointmentNumber'), assigned_id, now, sa.get('Status'))
    if sf.get('geo'):
        peers = [p for p in peers if p['miles'] is not None and p['miles'] <= geo_radius_mi]
    if mine:
        mine['queue_known'] = not any(r.get('_outside') for r in rows if r['Id'] == assigned_id)
    fac = sa.get('AAA_ERS_Account_Facility__r') or {}
    terr = sa.get('ServiceTerritory') or {}
    contacts = [{'name': c.get('Name'), 'title': c.get('Title'), 'phone': c.get('Phone') or c.get('MobilePhone') or c.get('Mobile_Phone__c')}
                for c in sf.get('contacts', [])][:MAX_CONTACTS]
    due = story_bits.get('promise') or sa.get('ERS_PTA_Due__c')
    late_min = (now - parse_dt(due)).total_seconds() / 60 if due else None
    cases = sf.get('cases', [])
    return {
        'sa': {'id': sa['Id'], 'number': sa.get('AppointmentNumber'), 'wo_id': sa.get('ERS_Work_Order__c'),
               'wo_number': (sa.get('ERS_Work_Order__r') or {}).get('WorkOrderNumber'), 'status': sa.get('Status'),
               'status_category': sa.get('StatusCategory'), 'work_type': (sa.get('WorkType') or {}).get('Name'),
               'priority': sa.get('WO_Priority_Code__c'), 'city': sa.get('City'), 'lat': member[0], 'lon': member[1],
               'created_at': sa.get('CreatedDate'), 'promise_at': due, 'late': lateness(late_min), 'late_min': round(late_min) if late_min is not None else None,
               'towbook': story_bits.get('towbook', False)},
        'garage': {'name': fac.get('Name') or terr.get('Name'), 'phone': fac.get('Phone'), 'lat': terr.get('Latitude'), 'lon': terr.get('Longitude'),
                   'contacts': contacts},
        'driver': mine, 'peers': peers, 'peer_counts': counts, 'required_skills': sorted(required),
        'suggestion': suggestion(sa.get('Status'), mine, peers),
        'working': working_now(story_bits.get('history'), [a for a in ars], sa['Id'], now),
        'contact': contact_counts(story_bits.get('extras'), story_bits.get('steps') or []),
        'cases': {**case_summary(cases), 'events': case_events(cases)},
        'errors': sf.get('errors', []), 'fetched_at': now.isoformat(timespec='seconds'),
    }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
