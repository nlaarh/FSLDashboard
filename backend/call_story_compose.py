"""Call Story: raw Salesforce bundle (+ day snapshot + norms) -> story response (architecture 7.2). Pure CPU.

Runs on every request, so a newly built day snapshot or new norms show up without re-reading Salesforce.
The SA record comes from report_card_snapshot.sa_record and the verdict from report_card_verdicts, so the story
and the Day view always agree on a call.
"""

from collections import defaultdict
from datetime import datetime, time as dtime, timezone

import call_story_causes as causes_mod
from call_story_events import (_is_id, build_events, channel_path, matrix_ladder, pta_block, towbook_final_decision)
from call_story_segments import extract, place_kind, severity
from call_story_sms import sms_block
from report_card_snapshot import CHANNEL_MAP, GRADED_CHANNELS, sa_record
from report_card_verdicts import RulesNotAvailable, rules_for, sa_features, supports, verdict
from utils import _ET, parse_dt, to_eastern

CANDIDATE_FREE = ('NOT_GRADED_TOWBOOK', 'NOT_GRADED_CANCELED_PRE_ASSIGN', 'INBOUND_CASCADE', 'BOUNCED')


def legs_of(raw: dict) -> tuple:
    sas = sorted(raw['sas'], key=lambda s: s['CreatedDate'])
    member = [s for s in sas if 'drop' not in ((s.get('WorkType') or {}).get('Name') or '').lower()]
    return member, [s for s in sas if s not in member]


from wo_replay_why import pick_trail  # noqa: E402


def compose(raw: dict, cfg: dict, sa_number: str | None = None, snapshot_for=None, norms_for=None,
            rules_version: str | None = None, now: datetime | None = None) -> dict:
    """snapshot_for(territory_id, date) -> snapshot | None; norms_for(date) -> Norms."""
    now = now or datetime.now(timezone.utc)
    member, drops = legs_of(raw)
    if not member:
        return {'status': 'no_service_appointment', 'resolution': raw['resolution'], 'header': _header(raw, None, [], [], None)}
    sa = next((s for s in member if s['AppointmentNumber'] == sa_number), member[0])
    rows = sorted((h for h in raw['history'] if h['ServiceAppointmentId'] == sa['Id']),
                  key=lambda h: (h['CreatedDate'], h.get('Id') or ''))      # sa_record expects time order
    ar = next((a for a in raw['assigned'] if a['ServiceAppointmentId'] == sa['Id']), None)
    created = parse_dt(sa['CreatedDate'])
    et_date = to_eastern(created).date()
    day_start = datetime.combine(et_date, dtime(0), tzinfo=_ET).astimezone(timezone.utc)
    snap = snapshot_for(sa.get('ServiceTerritoryId'), et_date.isoformat()) if snapshot_for else None
    snap_sa = next((s for s in (snap or {}).get('sas', []) if s['id'] == sa['Id']), None)
    if snap_sa is None:
        snap = None

    names, dtype, users = {}, {}, set()
    for a in raw['assigned']:
        sr = a.get('ServiceResource') or {}
        names[sr.get('Name')] = a['ServiceResourceId']
        dtype[a['ServiceResourceId']] = sr.get('ERS_Driver_Type__c')
        if sr.get('RelatedRecordId'):
            users.add(sr['RelatedRecordId'])
    for d in (snap or {}).get('drivers', []):
        names.setdefault(d['name'], d['id'])
        dtype.setdefault(d['id'], d['driver_type'])
    roster = [i for i, t in dtype.items() if CHANNEL_MAP.get(t) in GRADED_CHANNELS]
    record = sa_record(sa, rows, ar, names, roster, dtype, {}, users, day_start)
    rules = rules_for(rules_version) if rules_version else rules_for()
    events = build_events(raw, sa, rules, cfg, users, {n: CHANNEL_MAP.get(dtype.get(i)) for n, i in names.items()})
    tb_accept = towbook_final_decision(events)
    if tb_accept and record['channel'] not in GRADED_CHANNELS:
        record['channel'] = 'towbook'                                  # spec 4.2 / T5
    first_garage = next((h['NewValue'] for h in rows if h['Field'] == 'ServiceTerritory' and not h.get('OldValue')
                         and h.get('NewValue') and not _is_id(h['NewValue'])),
                        (sa.get('ServiceTerritory') or {}).get('Name'))
    open_jobs, driver_channel, blocking_src = _snapshot_helpers(snap)
    segs = extract(record, cfg, open_jobs, driver_channel or (lambda d: CHANNEL_MAP.get(dtype.get(d))), first_garage)
    pta = pta_block(record, events, sa, cfg)
    norms = norms_for(et_date.isoformat()) if norms_for else None
    due0 = parse_dt(pta['due_initial'])
    for g in segs:
        g['baseline'] = norms.baseline(g) if norms else None
        g['floor_min'] = cfg['floors_min'][g['kind']]
        g['severity'], g['severity_reason'] = severity(g, g['baseline'], due0, cfg)
        g['event_ids'] = [e['id'] for e in events if not e['hidden'] and (_near(e['ts'], g['from']) or _near(e['ts'], g['to']))]
    path = channel_path(events, first_garage, record['created'])
    if tb_accept and path[-1]['channel'] is None:
        path[-1]['channel'] = 'towbook'
    ladder = matrix_ladder(raw.get('matrix'), path, events, created, cfg)
    status_events = [(e['ts'], e['value']) for e in record['events'] if e['field'] == 'status']
    sms = sms_block(raw, raw['wo'], member, status_events, cfg)
    v = _verdict(snap, snap_sa, record, rules, created, now, sa.get('ServiceTerritoryId'))
    ctx = {'events': events, 'segments': segs, 'pta': pta, 'sms': sms, 'verdict': v, 'ladder': ladder,
           'record': record, 'first_garage': first_garage, 'final_garage': (sa.get('ServiceTerritory') or {}).get('Name'),
           'spot_for_grid': next((r['garage'] for r in ladder if place_kind(r['garage'], cfg) == 'SPOT'), None),
           'blocking': blocking_src(segs) if blocking_src else {}, 'driver_info': _driver_info(snap, segs), 'cfg': cfg}
    found = causes_mod.find_causes(ctx)
    bullets = causes_mod.bullets(found) or [{'text': causes_mod.NO_DELAY, 'cause_codes': [], 'event_ids': [], 'headline': False}]
    return {
        'meta': {'rules_version': cfg['rules_version'], 'verdict_rules_version': rules['rules_version'],
                 'snapshot_used': {'territory_id': sa.get('ServiceTerritoryId'), 'date': et_date.isoformat(),
                                   'built_at': snap['built_at'], 'provisional': snap['provisional']} if snap else None},
        'resolution': {**raw['resolution'], 'legs': [{'sa_id': s['Id'], 'number': s['AppointmentNumber'],
                                                      'work_type': (s.get('WorkType') or {}).get('Name'),
                                                      'role': 'member' if s in member else 'drop_off',
                                                      'selected': s is sa} for s in member + drops]},
        'header': _header(raw, sa, path, ladder, record),
        'pta': pta, 'events': events, 'segments': segs, 'sms': sms, 'causes': found, 'verdict': v,
        'bullets': bullets, 'data_notes': _notes(raw, sa, member, segs, record, cfg),
        'pick_trail': pick_trail(snap, snap_sa),
        'performer': (sa.get('Off_Platform_Driver__r') or {}).get('Name') if tb_accept else None,
    }


def _near(ts, ref, window_s=2):
    if not ts or not ref:
        return False
    return abs((parse_dt(ts) - parse_dt(ref)).total_seconds()) <= window_s


def _snapshot_helpers(snap):
    if not snap:
        return None, None, None
    jobs = defaultdict(list)
    for s in snap['sas']:
        if s.get('busy') and s.get('final_driver_id') and not s['is_drop_off']:
            jobs[s['final_driver_id']].append((parse_dt(s['busy'][0]), parse_dt(s['busy'][1]), s))
    channels = {d['id']: d['channel'] for d in snap['drivers']}
    by_name = {d['name']: d['id'] for d in snap['drivers']}

    def open_jobs(d, t, exclude):
        return sum(1 for a, b, s in jobs.get(d, ()) if a <= t < b and s['id'] != exclude)

    def blocking(segs):
        """C09: the job the busy driver was on when this call was dispatched to them (from the day snapshot)."""
        out = {}
        for g in segs:
            if g['kind'] != 'S3' or g.get('driver_state') != 'BUSY':
                continue
            t = parse_dt(g['from'])
            for a, b, s in jobs.get(by_name.get(g.get('driver')), ()):
                m = s['milestones']
                if a <= t < b and m['t_ol']:
                    end = parse_dt(m['t_end'])
                    out[g['id']] = {'blocking_sa': s['number'], 'blocking_work_type': s['work_type'],
                                    'blocking_on_scene_min': round((end - parse_dt(m['t_ol'])).total_seconds() / 60, 1)
                                    if end else None}
                    break
        return out
    return open_jobs, channels.get, blocking


def _driver_info(snap, segs):
    """C10 evidence: was the free driver logged in and not absent when the call was dispatched to them."""
    if not snap:
        return {}
    by_name = {d['name']: d for d in snap['drivers']}
    out = {}
    for g in segs:
        d = by_name.get(g.get('driver'))
        if g['kind'] != 'S3' or g.get('driver_state') != 'FREE' or not d:
            continue
        t = parse_dt(g['from'])
        login = next((x for x in d['logins'] if parse_dt(x['start']) <= t < parse_dt(x['end'])), None)
        out[g['id']] = {'logged_in': bool(login), 'login_window': [login['start'], login['end']] if login else None,
                        'absent': any(parse_dt(x['start']) <= t < parse_dt(x['end']) for x in d['absences'])}
    return out


def _verdict(snap, snap_sa, record, rules, created, now, territory_id) -> dict:
    """Day snapshot verdict when the day is built (identical to the Day view); otherwise only the candidate-free
    codes, which cannot contradict the report card (architecture 3.3)."""
    if snap_sa is not None:
        try:
            if not supports(snap, rules):
                raise RulesNotAvailable(rules['rules_version'])
            drivers = {d['id']: d for d in snap['drivers']}
            v = verdict(sa_features(snap_sa, rules, drivers.get(snap_sa['final_driver_id'])), rules)
            return {'source': 'day_snapshot', 'primary': v['code'], 'flags': v['flags'], 'evidence': v['evidence'],
                    'rules_version': rules['rules_version'], 'note': None, 'build': None}
        except RulesNotAvailable:
            return {'source': 'none', 'primary': None, 'flags': [], 'evidence': {}, 'build': None,
                    'note': f"Day snapshot predates rules {rules['rules_version']}: rebuild the garage-day"}
    m = record['milestones']
    if not m.get('t_end') or to_eastern(created).date() >= to_eastern(now).date():
        return {'source': 'none', 'primary': None, 'flags': [], 'evidence': {}, 'build': None,
                'note': 'Call still open or from today: graded once the day is over and built'}
    v = verdict(sa_features(record, rules), rules)
    build = {'territory_id': territory_id, 'date': to_eastern(created).date().isoformat(), 'allowed': True}
    if v['code'] in CANDIDATE_FREE:
        return {'source': 'partial', 'primary': v['code'], 'flags': v['flags'], 'evidence': v['evidence'],
                'note': 'Decision quality not checked: garage-day not built', 'build': build}
    return {'source': 'none', 'primary': None, 'flags': [], 'evidence': {}, 'build': build,
            'note': 'Decision not graded: garage-day not built'}


def _header(raw, sa, path, ladder, record):
    wo = raw['wo']
    hdr = {'work_type': ((sa or {}).get('WorkType') or {}).get('Name'), 'tow': wo.get('Tow_Call__c'),
           'source': wo.get('Source__c'), 'priority': wo.get('Priority_Code__c'),
           'wo_number': wo.get('WorkOrderNumber'), 'call_key': wo.get('ERS_Call_Key__c'),
           'opted_in_sms': wo.get('SMS_Opt_In__c'),
           'end': {'status': (sa or {}).get('Status'), 'resolution': wo.get('Resolution_Code__c'),
                   'clear': wo.get('Clear_Code__c')}}
    if sa:
        hdr.update({'city': sa.get('City'), 'postal_code': sa.get('PostalCode'),
                    'grid': {'id': sa.get('ERS_Parent_Territory__c'), 'name': (sa.get('ERS_Parent_Territory__r') or {}).get('Name')},
                    'final_garage': (sa.get('ServiceTerritory') or {}).get('Name'), 'channel': record['channel'],
                    'channel_path': path, 'matrix_ladder': ladder, 'matrix_as_of': 'current',
                    'wo_created': wo.get('CreatedDate'), 'sa_created': sa['CreatedDate']})
    return hdr


def _notes(raw, sa, member, segs, record, cfg) -> list:
    notes = [dict(n) for n in raw.get('data_notes') or []]
    if len(member) > 1:
        notes.append({'code': 'MULTI_SA', 'text': f'This work order has {len(member)} member-facing appointments.'})
    if raw.get('sms_source') == 'messaging_session':
        notes.append({'code': 'PRE_SMS_LOG', 'text': 'Detailed text log starts 1 Sep 2026; texts before it show as type unknown.'})
    if record['channel'] == 'towbook' and not sa.get('ActualStartTime'):
        notes.append({'code': 'TOWBOOK_ACTUALSTART_EMPTY',
                      'text': 'Arrival is the history On Location time (Towbook ActualStartTime is empty).'})
    thin = sorted({g['kind'] for g in segs if not g['baseline'] or g['baseline']['n'] < cfg['baseline']['min_n']})
    if thin:
        notes.append({'code': 'NO_BASELINE', 'text': f"No baseline yet (n < {cfg['baseline']['min_n']}) for "
                                                     f"{', '.join(thin)}: severity from floors only."})
    return notes
