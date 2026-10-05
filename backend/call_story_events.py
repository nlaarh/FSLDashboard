"""Call Story: raw SA history -> grouped events E00-E18, actor classes, channel path, matrix ladder.
call-story-spec 4.1/4.2/6, architecture 4.1/4.2. Pure, no I/O.

Rows with the same CreatedDate and the same actor form one event; the event's kind is the most significant change
in it. Noise fields are kept (hidden) for the raw view. Ids are E1, E2... in time order.
"""

import re
from datetime import timedelta

from call_story_segments import place_kind
from report_card_verdicts import actor_class, pick_class
from utils import parse_dt, to_eastern

_SF_ID = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')
NOISE = {'SchedStartTime', 'SchedEndTime', 'StateCode', 'CountryCode', 'ActualDuration', 'FSL__Auto_Schedule__c',
         'ERS_For_Spotting__c', 'FSL__GanttLabel__c', 'Duration', 'ArrivalWindowStartTime', 'ArrivalWindowEndTime'}
# Never returned (architecture 7.2): street address, precise location, the default-valued facility-change reason.
PII_FIELDS = {'Street', 'Latitude', 'Longitude', 'ERS_Reason_for_changing_Facility__c', 'Description'}
PRIORITY = ['E01_sa_created', 'E10_pullback', 'E09_garage_change', 'E07_rejected', 'E07_declined', 'E07_accepted',
            'E06_dispatched', 'E04_assigned', 'E11_en_route', 'E11_on_location', 'E17_end', 'E12_pta', 'E13_jeopardy',
            'E14_address', 'E15_note', 'E02_first_garage', 'E00_status', 'E99_other']
TERMINAL = ('Completed', 'Unable to Complete', 'Cancel Call - Service Not En Route', 'Cancel Call - Service En Route',
            'Canceled', 'No-Show')


def _iso(dt):
    return dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z') if dt else None


def _is_id(v):
    return bool(v) and bool(_SF_ID.match(str(v)))


def redact_row(h: dict) -> dict:
    if h.get('Field') in PII_FIELDS:
        return {**h, 'OldValue': '(hidden)' if h.get('OldValue') else None, 'NewValue': '(hidden)' if h.get('NewValue') else None}
    return h


def _row_kind(h, pullback: bool, cfg: dict):
    f, old, new = h['Field'], h.get('OldValue'), h.get('NewValue')
    if f == 'created':
        return 'E01_sa_created'
    if f == 'Status':
        if new == 'Spotted' and pullback:
            return 'E10_pullback'
        return {'Dispatched': 'E06_dispatched', 'Accepted': 'E07_accepted', 'Declined': 'E07_declined',
                'Rejected': 'E07_rejected', 'En Route': 'E11_en_route', 'On Location': 'E11_on_location',
                'Assigned': 'E04_assigned'}.get(new, 'E17_end' if new in TERMINAL else 'E00_status')
    if f in ('ServiceTerritory', 'AAA_ERS_Account_Facility__c'):
        if _is_id(new) or _is_id(old):
            return None
        return 'E09_garage_change' if old and new != old else 'E02_first_garage'
    if f == 'ERS_Assigned_Resource__c':
        if _is_id(new) or (new is None and _is_id(old)):
            return None
        return 'E04_assigned'
    if f == 'ERS_PTA__c':
        return 'E12_pta'
    if f == 'FSL__InJeopardy__c':
        return 'E13_jeopardy' if str(new).lower() == 'true' else 'E99_other'
    if f in ('Street', 'Latitude', 'Longitude', 'PostalCode', 'City'):
        return 'E14_address'
    if f == 'ServiceNote':
        return 'E15_note'
    return 'E99_other'


def build_events(raw: dict, sa: dict, rules: dict, cfg: dict, driver_users: set, driver_types: dict) -> list:
    """Events for one leg (sa = its Q2 row)."""
    rows = sorted((h for h in raw['history'] if h['ServiceAppointmentId'] == sa['Id']),
                  key=lambda h: (h['CreatedDate'], h.get('Id') or ''))
    groups, prev_status, assignee, assigners = [], None, None, set()
    assigned_names = {h.get('NewValue') for h in rows if h['Field'] == 'ERS_Assigned_Resource__c'
                      and h.get('NewValue') and not _is_id(h['NewValue'])}

    def is_driver(h):
        """Spec 9: the actor is this SA's own driver (SR names carry a garage suffix, e.g. 'Antonio Hatch Jr. 100')."""
        name = (h.get('CreatedBy') or {}).get('Name') or ''
        return h.get('CreatedById') in driver_users or any(n == name or n.startswith(name + ' ') for n in assigned_names)
    for h in map(redact_row, rows):
        # E10: pulled back from a driver = Spotted straight after Dispatched/Accepted/En Route, not from a SPOT placeholder
        pullback = prev_status in ('Dispatched', 'Accepted', 'En Route') and place_kind(assignee, cfg) != 'SPOT'
        kind = _row_kind(h, pullback, cfg)
        if h['Field'] == 'Status':
            prev_status = h.get('NewValue')
        if kind is None:
            continue
        actor = (h.get('CreatedBy') or {}).get('Name')
        if h['Field'] == 'ERS_Assigned_Resource__c':
            assignee = h.get('NewValue') or assignee          # a clear keeps who it was taken from
            assigners.add(actor)
        g = groups[-1] if groups else None
        if g and g['_key'] == (h['CreatedDate'], actor):
            g['_kinds'].append(kind)
            g['fields'].append({'field': h['Field'], 'old': h.get('OldValue'), 'new': h.get('NewValue')})
            continue
        groups.append({'_key': (h['CreatedDate'], actor), '_kinds': [kind], 'ts': _iso(parse_dt(h['CreatedDate'])),
                       'actor': actor, 'actor_profile': ((h.get('CreatedBy') or {}).get('Profile') or {}).get('Name'),
                       'actor_is_driver': is_driver(h),
                       'fields': [{'field': h['Field'], 'old': h.get('OldValue'), 'new': h.get('NewValue')}]})
    events = []
    last_driver_channel = None
    for g in groups:
        kind = min(g.pop('_kinds'), key=PRIORITY.index)
        g.pop('_key')
        by_field = {}
        for f in g['fields']:
            by_field.setdefault(f['field'], []).append(f)
        assigned = by_field.get('ERS_Assigned_Resource__c')
        terr = by_field.get('ServiceTerritory') or by_field.get('AAA_ERS_Account_Facility__c')
        hidden = kind == 'E99_other' and all(f['field'] in NOISE for f in g['fields'])
        actor = {'actor': g['actor'], 'actor_profile': g['actor_profile'], 'actor_is_driver': g['actor_is_driver']}
        cls = (pick_class({**actor, 'ts': g['ts']}, {'auto_schedule_requested': sa.get('Auto_Schedule_Requested__c')}, rules)
               if assigned else actor_class(actor, rules))
        if kind == 'E01_sa_created' and g['actor_profile'] == 'Membership User' and g['actor'] not in assigners:
            cls = 'CALL_TAKER'                                                       # spec T6
        ev = {**g, 'kind': kind, 'actor_class': cls, 'hidden': hidden, 'leg': 'member'}
        # Several changes saved together share one event: read moves/assignments from the fields, not the kind.
        if assigned:
            ev['assigned'], ev['driver'] = True, assigned[-1]['new']
            ev['summary_code'] = 'UNASSIGNED' if not ev['driver'] else 'ASSIGNED'
            last_driver_channel = _name_channel(ev['driver'], driver_types, cfg)   # unknown type stays unknown
        if terr:
            ev['to'], ev['from'], ev['place_kind'] = terr[-1]['new'], terr[-1]['old'], place_kind(terr[-1]['new'], cfg)
            ev['moved'] = any(f['old'] and f['new'] != f['old'] for f in terr)
            if ev['moved']:
                ev['summary_code'] = f"MOVED_TO_{ev['place_kind']}"
        if 'ERS_PTA__c' in by_field:
            ev['pta_from'], ev['pta_to'] = by_field['ERS_PTA__c'][-1]['old'], by_field['ERS_PTA__c'][-1]['new']
        ev['channel'] = last_driver_channel
        events.append(ev)
    _attach_reasons(events, sa, cfg)
    _mark_decline_speed(events, cfg)
    for i, ev in enumerate(events, 1):
        ev['id'] = f'E{i}'
    return events


def _name_channel(name, driver_types: dict, cfg: dict):
    if not name:
        return None
    if name.lower().startswith('towbook'):
        return 'towbook'
    if place_kind(name, cfg) == 'SPOT':
        return 'spot'
    return driver_types.get(name)


def _attach_reasons(events: list, sa: dict, cfg: dict):
    """E08: reasons are not history-tracked and keep only the last value (T3). A rejection reason goes only to the
    Rejected event within 60 s of ERS_Rejected_Datetime__c; a facility decline reason only if there was exactly
    one Declined event. Otherwise 'reason not recorded for this hop'."""
    rejected_at = parse_dt(sa.get('ERS_Rejected_Datetime__c'))
    declines = [e for e in events if e['kind'] == 'E07_declined']
    for e in events:
        if e['kind'] == 'E07_rejected':
            close = rejected_at and abs((parse_dt(e['ts']) - rejected_at).total_seconds()) <= cfg['reason_attach_sec']
            e['reason'] = sa.get('ERS_Rejection_Reason__c') if close else None
        elif e['kind'] == 'E07_declined':
            e['reason'] = sa.get('ERS_Facility_Decline_Reason__c') if len(declines) == 1 else None


def _mark_decline_speed(events: list, cfg: dict):
    """C02 evidence: seconds from the offer (last garage move or assignment) to the Towbook decline."""
    offer = None
    for e in events:
        if e['kind'] in ('E01_sa_created', 'E02_first_garage') or e.get('moved') or e.get('assigned'):
            offer = parse_dt(e['ts'])
        if e['kind'] == 'E07_declined' and offer:
            secs = round((parse_dt(e['ts']) - offer).total_seconds())
            e['seconds_from_offer'] = secs
            e['summary_code'] = 'DECLINED_AUTO' if secs <= cfg['decline_auto_sec'] else 'DECLINED'


def towbook_final_decision(events: list) -> dict | None:
    """Spec 4.2 / T5: on a Towbook leg the final decision is the Status -> Accepted row by Towbook sync."""
    return next((e for e in reversed(events) if e['kind'] == 'E07_accepted' and e['actor_class'] == 'TOWBOOK_SYNC'), None)


def channel_path(events: list, first_garage: str | None, created_ts: str) -> list:
    """[{ts, garage, channel}] per garage held, channel taken from the first assignment while there."""
    hops = [{'ts': created_ts, 'garage': first_garage, 'channel': None}]
    for e in events:
        if e.get('moved'):
            hops.append({'ts': e['ts'], 'garage': e['to'], 'channel': None})
        if e.get('assigned') and e.get('driver') and hops[-1]['channel'] is None:
            hops[-1]['channel'] = e['channel']
    return hops


def matrix_ladder(matrix: dict | None, path: list, events: list, created, cfg: dict) -> list:
    """Ranks for the call's grid: final / tried / declined / rejected / skipped_closed (inferred from current
    operating hours) / not_reached. Current matrix, may differ from that day."""
    if not matrix or not matrix.get('rows'):
        return []
    held = [h['garage'] for h in path if h['garage']]
    final = held[-1] if held else None
    declined_at, rejected_at = set(), set()
    garage = held[0] if held else None
    for e in events:
        if e.get('moved'):
            garage = e['to']
        if e['kind'] == 'E07_declined':
            declined_at.add(garage)
        elif e['kind'] == 'E07_rejected':
            rejected_at.add(garage)
    ranks = sorted(matrix['rows'], key=lambda r: (r.get('rank') or 99, r.get('garage') or ''))
    first_rank = next((r['rank'] for r in ranks if r['garage'] in held), None)
    out = []
    for r in ranks:
        g = r['garage']
        if g == final:
            state = 'final'
        elif g in rejected_at:
            state = 'rejected'
        elif g in declined_at:
            state = 'declined'
        elif g in held:
            state = 'tried'
        elif first_rank and r['rank'] < first_rank and not is_open(r.get('slots'), created):
            state = 'skipped_closed'
        else:
            state = 'not_reached'
        out.append({**{k: r.get(k) for k in ('rank', 'garage', 'worktype', 'hours')}, 'state': state,
                    'inferred': state == 'skipped_closed'})
    return out


def is_open(slots: list | None, t) -> bool:
    """TimeSlot rows [{day: 'Monday', start: 'HH:MM', end: 'HH:MM'}] in Eastern time. No slots = always open."""
    if not slots:
        return True
    et = to_eastern(t)
    day, hm = et.strftime('%A'), et.strftime('%H:%M')
    return any(s['day'] == day and s['start'] <= hm < s['end'] for s in slots)


def pta_block(record: dict, events: list, sa: dict, cfg: dict) -> dict:
    """Architecture 4.4: graded against the ORIGINAL promise; the re-based one shown alongside (C16)."""
    m = record['milestones']
    arrival, due0, due1 = parse_dt(m['arrival']), parse_dt(record.get('pta_initial_due')), parse_dt(record.get('pta_due'))
    created = parse_dt(record['created'])
    rebased = None
    if record.get('pta_initial_min') is not None and record.get('pta_min') not in (None, record['pta_initial_min']):
        later = [e for e in events if 'pta_to' in e]
        later = [e for e in later if parse_dt(e['ts']) > created + timedelta(seconds=cfg['pta']['initial_window_sec'])]
        if later:
            rebased = {'ts': later[-1]['ts'], 'actor': later[-1]['actor']}
    met = lambda due: (arrival <= due) if (arrival and due) else None
    return {
        'basis_ts': _iso(parse_dt(sa.get('ERS_Spotting_Datetime__c')) or created),
        'initial_min': record.get('pta_initial_min'), 'final_min': record.get('pta_min'),
        'due_initial': record.get('pta_initial_due'), 'due_final': record.get('pta_due'),
        'arrival': m['arrival'], 'arrival_source': m['arrival_source'], 'graded_against': 'initial',
        'met_initial': met(due0), 'met_final': met(due1),
        'margin_initial_min': round((due0 - arrival).total_seconds() / 60, 1) if (arrival and due0) else None,
        'response_min': round((arrival - created).total_seconds() / 60, 1) if arrival else None,
        'rebased': rebased,
    }
