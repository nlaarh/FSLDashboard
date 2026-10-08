"""Work Order Replay: a call story turned into animation steps (who sent what to whom, in time order).

Pure, no I/O. Input is the dict compose() returns; output is what the replay player draws:
  steps     [{id, ts, clock (ET), dt (s since the call came in), kind, from, via, to, touch, title, detail,
              actor, role, names, flag}]   nodes: member, intake, sf, fsl, dispatcher, towbook, garage, driver
  problems  plain-language findings from the story, each pointing at the steps that show it
  decision  was the pick near, free and qualified (numbers from the story, no new queries)
Never carries phone numbers or street addresses (the story already withholds them).
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from wo_explain import explain
from wo_replay_why import attach_why
from wo_takeaways import takeaways

ET = ZoneInfo('America/New_York')
SRC_NODE = {'IVR': 'src_ivr', 'DRR': 'src_drr', 'Intake': 'src_mcc', 'RAP': 'src_partner', 'Call Mover': 'src_partner'}
CAPTURE = {'src_ivr': 'Replicant voice AI took the call', 'src_drr': 'Member filled in the web or app form (DRR)',
           'src_mcc': 'A call-center agent (MCC) took the call', 'src_partner': 'A partner sent the call in'}
INTAKE = {'IVR': 'Voice AI (Replicant)', 'Intake': 'Call-center agent', 'DRR': 'Member web or app',
          'RAP': 'Partner (RAP)', 'Call Mover': 'Partner (Call Mover)'}
ROLE = {'FSL_AUTO_SCHEDULE': 'FSL auto-schedule', 'FSL_ENGINE': 'FSL optimizer', 'INTEGRATION': 'Integration',
        'TOWBOOK_SYNC': 'Towbook', 'DRIVER': 'Driver', 'HUMAN': 'AAA staff', 'GARAGE_DISPATCHER': 'Garage dispatcher',
        'CALL_TAKER': 'Call taker', 'OTHER': 'Other'}
SYSTEM_VIA = {'FSL_AUTO_SCHEDULE': 'fsl', 'FSL_ENGINE': 'fsl', 'INTEGRATION': 'intake', 'TOWBOOK_SYNC': 'towbook'}
HUMAN_CLASSES = {'HUMAN', 'GARAGE_DISPATCHER', 'CALL_TAKER', 'OTHER'}
_SUFFIX = re.compile(r'\s+\d{2,3}[A-Z]{0,2}$')
_GARAGE_CODE = re.compile(r'^\w+\s+-\s+')


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace('Z', '+00:00'))


def _clock(iso: str) -> str:
    return _dt(iso).astimezone(ET).strftime('%H:%M:%S')


_PLACEHOLDER = re.compile(r'^(?:Towbook-(\w+)\b.*|\d{3}-\s*ST\s*SPOT\b.*)$', re.I)


def _driver(name):
    """Display name: the garage suffix is dropped, and the Towbook / SPOT placeholders read as what they are."""
    m = _PLACEHOLDER.match((name or '').strip())
    if m:
        return f'Towbook {m.group(1)}' if m.group(1) else 'SPOT queue (no driver)'
    return _SUFFIX.sub('', name or '').strip()


def _garage(name):
    return _GARAGE_CODE.sub('', name or '').title() if name else ''


def _route(cls: str, start='sf'):
    """(via node, kind) for an action taken by an actor class."""
    if cls in SYSTEM_VIA:
        return SYSTEM_VIA[cls], 'system'
    return 'dispatcher', 'human'


def _step(sid, ts, kind, frm, to, title, actor=None, cls=None, via=None, detail='', touch=None, names=None, flag=None, content=None):
    return {'id': sid, 'ts': ts, 'kind': kind, 'from': frm, 'via': via, 'to': to, 'touch': touch or [], 'title': title,
            'detail': detail, 'actor': actor or '', 'role': ROLE.get(cls, ''), 'names': names or {}, 'flag': flag, 'content': content or [], 'explain': None}


_FIELD = {'Status': 'Status', 'ERS_Assigned_Resource__c': 'Driver', 'ServiceTerritory': 'Garage', 'AAA_ERS_Account_Facility__c': 'Garage',
          'ERS_PTA__c': 'Promise (min)', 'FSL__InJeopardyReason__c': 'Jeopardy reason', 'FSL__InJeopardy__c': 'In jeopardy'}
_ID = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')


def _plain(v) -> str:
    t = str(v)
    return t[:-2] if t.endswith('.0') else t


def _content(e: dict) -> list:
    """What was inside the change: only the fields a dispatcher reads, no noise, no ids, no addresses.
    Several changes to one field in the same save collapse to first old value -> last new value."""
    seen = {}
    for f in e.get('fields') or []:
        label = _FIELD.get(f['field'])
        new, old = f.get('new'), f.get('old')
        if not label or _ID.match(str(new or '')) or _ID.match(str(old or '')):
            continue
        fmt = _driver if label == 'Driver' else _garage if label == 'Garage' else _plain
        o = fmt(old) if str(old or '') not in ('', 'None') else None
        n = fmt(new) if str(new or '') not in ('', 'None') else 'none'
        first = seen.get(label, (o, n))[0]
        seen[label] = (first or o, n)
    return [f'{k}: {o + " → " if o and o != n else ""}{n}' for k, (o, n) in seen.items()]


def event_steps(story: dict) -> list:
    hdr = story['header']
    first_garage = _garage((hdr.get('channel_path') or [{}])[0].get('garage') or hdr.get('final_garage'))
    sa_no = next((leg['number'] for leg in story['resolution']['legs'] if leg['selected']), None)
    out, driver, garage = [], None, first_garage
    for e in story['events']:
        if e.get('hidden') or e.get('leg', 'member') != 'member':
            continue
        k, cls, actor, ts, eid = e['kind'], e.get('actor_class'), e.get('actor'), e['ts'], e['id']
        via, vkind = _route(cls)
        if k == 'E01_sa_created':
            ch = INTAKE.get(hdr.get('source'), hdr.get('source') or 'Unknown channel')
            src = SRC_NODE.get(hdr.get('source'), 'src_partner')
            out.append(_step('C0', ts, 'member', 'member', src, f'Call captured: {ch}', None, None,
                             detail=CAPTURE.get(src, ''), content=['Where the work was captured', ch]))
            out.append(_step(eid, ts, 'system', src, 'sf', 'Service appointment created in Salesforce', actor, cls, via='intake',
                             detail=_promise(story) or 'Routed to the garage', touch=['garage'],
                             names={'sf': sa_no or 'Salesforce', 'garage': garage}))
        elif k == 'E04_assigned':
            name = _driver(e.get('driver'))
            if str(e.get('driver') or '').startswith('Towbook'):
                driver = e['driver']
                out.append(_step(eid, ts, vkind, 'sf', 'towbook', f'Offered to Towbook garage {e["driver"].split()[-1]}', actor, cls,
                                 names={'towbook': _driver(e['driver'])}))
                continue
            driver = name or driver
            title = f'Assigned to {name}' if name else 'Driver removed (unassigned)'
            out.append(_step(eid, ts, vkind, 'sf', 'driver', title, actor, cls, via=via,
                             names={'driver': name or 'No driver', **({'dispatcher': actor} if vkind == 'human' else {}),
                                    **({'fsl': ROLE[cls]} if via == 'fsl' else {}),}))
        elif k == 'E06_dispatched' and str(e.get('driver') or driver or '').startswith('Towbook'):
            code = str(e.get('driver') or driver).split('-')[-1].split()[0]
            out.append(_step(eid, ts, vkind, 'sf', 'towbook', f'Offered to Towbook garage {code}', actor, cls, via=via if vkind == 'human' else None,
                             names={'towbook': f'Towbook {code}'}))
        elif k == 'E06_dispatched':
            auto = cls in SYSTEM_VIA
            out.append(_step(eid, ts, vkind, 'sf', 'driver', f'{"Auto-released" if auto else "Released"} to {driver or "the driver"} (Dispatched)',
                             actor, cls, via=via, names={'dispatcher': actor} if vkind == 'human' else {}))
        elif k == 'E07_accepted':
            who, kind = ('towbook', 'system') if cls == 'TOWBOOK_SYNC' else ('driver', 'driver')
            out.append(_step(eid, ts, kind, who, 'sf', 'Towbook garage accepted' if who == 'towbook' else 'Driver accepted in the FSL app', actor, cls))
        elif k in ('E07_declined', 'E07_rejected'):
            who, kind = ('towbook', 'system') if k == 'E07_declined' else ('driver', 'driver')
            secs = e.get('seconds_from_offer')
            why = e.get('reason') or 'reason not recorded'
            fast = f' in {secs} s' if k == 'E07_declined' and secs is not None else ''
            out.append(_step(eid, ts, kind, who, 'sf', f'{"Garage declined" if who == "towbook" else "Driver rejected"}{fast}', actor, cls,
                             detail=why, flag={'text': f'{"Declined" if who == "towbook" else "Rejected"}{fast}', 'level': 'warn'}))
        elif k == 'E09_garage_change':
            garage = _garage(e.get('to')) or garage
            out.append(_step(eid, ts, vkind, 'sf', 'garage', f'Moved to {garage}', actor, cls, via=via if vkind == 'human' else None,
                             names={'garage': garage, **({'dispatcher': actor} if vkind == 'human' else {})}))
        elif k == 'E10_pullback':
            out.append(_step(eid, ts, vkind, 'driver', 'sf', 'Pulled back from the driver (Spotted)', actor, cls, via=via,
                             flag={'text': 'Pulled back after dispatch', 'level': 'warn'}, names={'dispatcher': actor} if vkind == 'human' else {}))
        elif k in ('E11_en_route', 'E11_on_location', 'E17_end'):
            status = next((f['new'] for f in e['fields'] if f['field'] == 'Status'), '')
            who, kind = ('towbook', 'system') if cls == 'TOWBOOK_SYNC' else ('driver', 'driver')
            out.append(_step(eid, ts, kind, who, 'sf', status or k, actor, cls))
        elif k == 'E12_pta':
            out.append(_step(eid, ts, 'mark', 'sf', 'sf', f'Promise changed: {e.get("pta_from") or "none"} to {e.get("pta_to")} min', actor, cls))
        elif k == 'E13_jeopardy':
            out.append(_step(eid, ts, 'mark', 'sf', 'sf', 'Call in jeopardy: promise overdue', actor, cls,
                             flag={'text': 'Promise passed with the member still waiting', 'level': 'bad'}))
    by_id = {e['id']: e for e in story['events']}
    for st in out:
        if not st['content'] and st['id'] in by_id:
            st['content'] = _content(by_id[st['id']])
    return out


def _promise(story: dict) -> str:
    p = story.get('pta') or {}
    return f'Promise to the member: {int(p["initial_min"])} min' if p.get('initial_min') else ''


def promise_step(story: dict):
    """The moment the member's original promise ran out, flagged when no driver had arrived by then."""
    p = story.get('pta') or {}
    if not p.get('due_initial'):
        return None
    late = p.get('met_initial') is False
    return _step('P1', p['due_initial'], 'mark', 'sf', 'sf', 'Promise time reached',
                 detail='Driver had not arrived yet' if late else 'Driver arrived in time',
                 flag={'text': f'Arrived {abs(round(p["margin_initial_min"]))} min after the promise', 'level': 'bad'} if late and p.get('margin_initial_min') is not None else None)


def sms_steps(story: dict) -> list:
    out = []
    for n, r in enumerate(story['sms'].get('rows') or [], 1):
        ok = r['outcome'] == 'sent'
        mins = f' ({int(r["checkpoint_min"])} min)' if r.get('checkpoint_min') else ''
        title = f'Text: {r["label"]}{mins}' if ok else f'Text NOT sent: {r["label"]}{mins}'
        out.append(_step(f'S{n}', r['ts'].replace('+0000', 'Z'), 'sms', 'sf', 'member', title, 'Salesforce text flow', None,
                         detail='Sent' if ok else (r.get('reason') or r['outcome']),
                         content=[f'Message: {r["label"]}{mins}', 'Flow: ' + (r.get('definition') or 'unknown').replace('_', ' '),
                                  'Outcome: ' + ('sent' if ok else r['outcome'] + (f' ({r["reason"]})' if r.get('reason') else ''))],
                         flag=None if ok else {'text': f'Text not sent: {r["outcome"]}', 'level': 'bad'}))
    for n, w in enumerate(story['sms'].get('why_not') or [], 1):
        if w.get('ts'):   # only when we know when the text was due; otherwise it stays in the problem list, not on the timeline
            out.append(_step(f'W{n}', w['ts'], 'mark', 'sf', 'sf', 'A text that should have gone out did not',
                             detail=w.get('text') or str(w), flag={'text': w.get('text') or 'Expected text missing', 'level': 'bad'}))
    return out


_STUCK = ('SLOW', 'STUCK', 'CRITICAL')


def problem_steps(story: dict) -> list:
    """A long gap with nobody working the call has no event of its own, so it would be invisible in the replay. Each one becomes a
    warning step at the moment the wait began, with the reasons it may have happened."""
    hdr = story.get('header') or {}
    base = dict(ladder=hdr.get('matrix_ladder'), work_type=hdr.get('work_type'), grid=(hdr.get('grid') or {}).get('name'))
    out = []
    for g in story.get('segments') or []:
        if g.get('severity') not in _STUCK:
            continue
        m, lvl = g['minutes'], 'bad' if g['severity'] != 'SLOW' else 'warn'
        who = _driver(g.get('driver'))
        spec = {'S7': ('NO_OWNER', f'No owner for {_dur(m)}'), 'S8': ('PARKED_SPOT', f'Parked in the SPOT queue for {_dur(m)}'),
                'S9': ('STUCK_GRID', f"Stuck in zone {base['grid'] or ''} for {_dur(m)}".replace('zone  ', 'a zone ')),
                'S2': ('SLOW_RELEASE', f'Assigned but not released for {_dur(m)}'),
                'S3': ('WAIT_BUSY' if g.get('driver_state') == 'BUSY' else 'WAIT_FREE', f"Waiting {_dur(m)} for {who or 'the driver'} to accept")}.get(g['kind'])
        if not spec:
            continue
        code, title = spec
        st = _step(g['id'], g['from'], 'mark', 'sf', 'sf', title, detail=f"Severity: {g['severity'].lower()}",
                   flag={'text': title, 'level': lvl}, content=[f'Minutes: {round(m)}'])
        st['explain'] = explain(code, minutes=m, driver=who, **base)
        out.append(st)
    return out


def _dur(m):
    m = round(m)
    return f'{m} min' if m < 120 else f'{m // 60} h {m % 60} min'


def attach_explain(steps: list, story: dict):
    """Adds step['explain'] to the flagged steps that do not have one yet: the reasons it may have happened."""
    import re
    pre, dispatched = [], False
    for st in steps:
        t = st['title']
        if 'Released' in t or 'Auto-released' in t:
            dispatched = True
        if t.startswith('Assigned to') and not dispatched:
            pre.append(st)
        if st.get('explain'):
            continue
        if t.startswith('Garage declined'):
            m = re.search(r' in (\d+) s', t)
            st['explain'] = explain('DECLINES', seconds=[int(m.group(1))] if m else [])
        elif t.startswith('Driver rejected'):
            st['explain'] = explain('REJECT', reason=None if st['detail'] == 'reason not recorded' else st['detail'])
        elif t.startswith('Pulled back'):
            st['explain'] = explain('PULLBACK')
        elif st['kind'] == 'sms' and st.get('flag'):
            st['explain'] = explain('TEXT_FAILED', reasons=[(st['detail'], 'skipped')])
        elif t.startswith('A text that should have gone out'):
            st['explain'] = explain('TEXT_STILL_WORKING')
        elif st.get('flag') and (t.startswith('Promise time reached') or t.startswith('Call in jeopardy')):
            st['explain'] = explain('LATE')
    if len(pre) >= 3:
        pre[2]['explain'] = pre[2].get('explain') or explain('CHURN')
        if not pre[2].get('flag'):
            pre[2]['flag'] = {'text': f'Assigned {len(pre)} times before it was released', 'level': 'warn'}


def build_replay(story: dict, where: dict | None = None) -> dict:
    header = _header(story, where)
    steps = sorted(event_steps(story) + sms_steps(story) + problem_steps(story) + ([promise_step(story)] if promise_step(story) else []), key=lambda s: _dt(s['ts']))
    if not steps:
        return {'header': header, 'steps': [], 'problems': [], 'decision': None, 'takeaways': None}
    t0 = _dt(steps[0]['ts'])
    for s in steps:
        s['clock'] = _clock(s['ts'])
        s['dt'] = max(0, round((_dt(s['ts']) - t0).total_seconds()))
    attach_why(steps, story.get('pick_trail'))
    attach_explain(steps, story)
    ids = {s['id'] for s in steps}
    problems = [{'text': b['text'], 'headline': bool(b.get('headline')), 'step_ids': [i for i in b.get('event_ids') or [] if i in ids]}
                for b in story.get('bullets') or []]
    return {'header': header, 'steps': steps, 'problems': problems, 'decision': _decision(story), 'takeaways': takeaways(story, steps)}


def _header(story: dict, where: dict | None = None) -> dict:
    h, leg = story['header'], next((x for x in story['resolution']['legs'] if x['selected']), {})
    return {'sa': leg.get('number'), 'wo': story['resolution']['wo']['number'], 'service': h.get('work_type'),
            'garage': _garage(h.get('final_garage')), 'where': where or {'member': None, 'garage': None}, 'channel': INTAKE.get(h.get('source'), h.get('source')),
            'date': _dt(story['events'][0]['ts']).astimezone(ET).strftime('%a %b %d, %Y') if story['events'] else None}


def _decision(story: dict):
    ev = ((story.get('verdict') or {}).get('evidence')) or {}
    if ev.get('pick_miles') is None:
        return None
    return {'pick_miles': ev['pick_miles'], 'pick_open_jobs': ev.get('pick_open_jobs'), 'pick_qualified': ev.get('pick_qualified'),
            'closest_qualified_miles': ev.get('closest_q_miles'), 'picked_closest': ev.get('picked_closest'),
            'closest_free_miles': ev.get('closest_free_q_miles'), 'candidates': ev.get('n_candidates'),
            'who_decided': ROLE.get(ev.get('final_actor_class'), ev.get('final_actor_class')), 'verdict': (story.get('verdict') or {}).get('primary')}
