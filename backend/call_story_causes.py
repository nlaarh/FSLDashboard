"""Call Story: deterministic causes C01-C19, the headline cause and template bullets (call-story-spec 8).
Pure, no I/O. The AI only narrates these; it can never add one.
"""

from call_story_config import SEVERITY_ORDER
from call_story_segments import place_kind
from utils import parse_dt, to_eastern

NAMES = {'C01': 'RANK_SKIPPED', 'C02': 'TOWBOOK_DECLINE', 'C03': 'DRIVER_REJECT', 'C04': 'ORPHANED_AFTER_REJECT',
         'C05': 'PARKED_IN_SPOT', 'C06': 'IN_GRID', 'C07': 'OPTIMIZER_CHURN', 'C08': 'SLOW_RELEASE',
         'C09': 'QUEUED_BEHIND_JOB', 'C10': 'NO_ACCEPT_FREE_DRIVER', 'C11': 'PULLBACK', 'C12': 'INBOUND_CASCADE',
         'C13': 'DECISION_QUALITY', 'C14': 'LONG_DRIVE', 'C15': 'LONG_ON_SCENE', 'C16': 'PTA_REBASELINED',
         'C17': 'MEMBER_NOT_UPDATED', 'C18': 'CANCELED_WHILE_STUCK', 'C19': 'DISPATCHER_SPOT_REGION'}
LEVERS = {'C02': 'L08', 'C04': 'L08', 'C05': 'L08', 'C07': 'L05', 'C08': 'L05', 'C10': 'L09', 'C11': 'L06',
          'C12': 'L08', 'C14': 'L09', 'C15': 'L09', 'C18': 'L08'}
DECISION_LEVER = {'STACKED': 'L03', 'FAR_PICK': 'L04', 'LATE_DESPITE_CAPACITY': 'L03', 'LATE_EXECUTION': 'L09',
                  'CAPACITY_SHORT': 'L07'}
SEGMENT_CAUSE = {'S7': 'C04', 'S8': 'C05', 'S9': 'C06', 'S2': 'C08', 'S5': 'C14', 'S6': 'C15'}
HEADLINE_BY_CODE = {'BOUNCED': 'C11', 'INBOUND_CASCADE': 'C12', 'STACKED': 'C13', 'FAR_PICK': 'C13',
                    'LATE_DESPITE_CAPACITY': 'C13', 'LATE_EXECUTION': 'C13', 'CAPACITY_SHORT': 'C13'}


def _at_least(seg, level):
    return SEVERITY_ORDER.index(seg['severity']) >= SEVERITY_ORDER.index(level)


def _hm(ts):
    return to_eastern(ts).strftime('%H:%M') if ts else '?'


def _events_between(events, a, b):
    lo, hi = parse_dt(a), parse_dt(b) if b else None
    return [e for e in events if lo <= parse_dt(e['ts']) and (hi is None or parse_dt(e['ts']) <= hi)]


def _event_at(events, ts, window_s=2):
    t = parse_dt(ts)
    return next((e for e in events if t and abs((parse_dt(e['ts']) - t).total_seconds()) <= window_s and not e['hidden']), None)


def diagnosis(code: str, actor_class: str | None) -> str | None:
    """metrics-spec 10A.2 hypotheses for C07/C08/C13 when the optimizer or the integration decided."""
    if actor_class == 'INTEGRATION' and code in ('STACKED', 'FAR_PICK'):
        return ('Consistent with the pick being decided outside Salesforce code (IT System User, no FSL auto-schedule '
                'stamp), so no scheduling policy or workload rule was checked')
    if actor_class == 'FSL_AUTO_SCHEDULE' and code in ('STACKED', 'LATE_DESPITE_CAPACITY'):
        return 'Consistent with no workload-balance objective in this org (FSL auto-schedule ran a policy without one)'
    if actor_class != 'FSL_ENGINE':
        return None
    return {
        'OPTIMIZER_CHURN': 'Consistent with In-Day and RSO optimization re-running every few minutes on calls not yet dispatched',
        'SLOW_RELEASE': 'Consistent with In-Day and RSO optimization re-running every few minutes on calls not yet dispatched',
        'FAR_PICK': "Consistent with the active policy weighting Minimize Travel far below ASAP (soonest, not closest)",
        'STACKED': 'Consistent with no workload-balance objective in this org and RSO working one resource at a time',
        'LATE_DESPITE_CAPACITY': 'Consistent with no workload-balance objective in this org and RSO working one resource at a time',
    }.get(code)


def find_causes(ctx: dict) -> list:
    """ctx: events, segments, pta, sms, verdict, ladder, record, final_garage, spot_for_grid, blocking, driver_info."""
    ev, segs, out = ctx['events'], ctx['segments'], []
    vis = [e for e in ev if not e['hidden']]

    def add(code, ts, event_ids=(), segment_ids=(), evidence=None, verdict_code=None, lever=None, diag=None):
        out.append({'code': code, 'name': NAMES[code], 'ts': ts, 'event_ids': list(event_ids),
                    'segment_ids': list(segment_ids), 'evidence': evidence or {}, 'verdict_code': verdict_code,
                    'lever': lever or LEVERS.get(code), 'diagnosis': diag, 'headline': False})

    skipped = [r for r in ctx.get('ladder') or [] if r['state'] == 'skipped_closed']
    if skipped:
        add('C01', ctx['record']['created'], evidence={'skipped': [{'rank': r['rank'], 'garage': r['garage'],
                                                                     'hours': r['hours']} for r in skipped],
                                                        'inferred': True})
    garage = ctx.get('first_garage')
    for i, e in enumerate(vis):
        if e.get('moved'):
            garage = e['to']
        if e['kind'] == 'E07_declined' and e['actor_class'] == 'TOWBOOK_SYNC':
            nxt = next((x['to'] for x in vis[i + 1:] if x.get('moved')), None)
            add('C02', e['ts'], [e['id']], evidence={'garage': garage, 'seconds': e.get('seconds_from_offer'),
                                                     'automatic_like': e.get('summary_code') == 'DECLINED_AUTO',
                                                     'reason': e.get('reason'), 'next_garage': nxt})
        elif e['kind'] == 'E07_rejected':
            add('C03', e['ts'], [e['id']], evidence={'reason': e.get('reason') or 'reason not recorded for this hop',
                                                     'by': e['actor']})
        elif e['kind'] == 'E10_pullback':
            dispatches = [x for x in vis if x['kind'] == 'E06_dispatched']
            first = dispatches[0]['ts'] if dispatches else None
            re_disp = next((x['ts'] for x in dispatches if parse_dt(x['ts']) > parse_dt(e['ts'])), None)
            lost = round((parse_dt(re_disp) - parse_dt(first)).total_seconds() / 60, 1) if first and re_disp else None
            add('C11', e['ts'], [e['id']], evidence={'by': e['actor'], 'minutes_lost': lost},
                verdict_code='BOUNCED')
    for g in segs:
        if g['kind'] == 'S7' and _at_least(g, 'SLOW') and g['severity_reason'] != 'always_flag':
            # always_flag marks every no-owner gap; "orphaned" needs real lateness (p75/floor or worse)
            act = _event_at(ev, g['to']) if g['to'] else None
            add('C04', g['from'], [act['id']] if act else [], [g['id']],
                {'minutes': g['minutes'], 'acted_by': act['actor'] if act else None})
        elif g['kind'] == 'S8':
            start, end = _event_at(ev, g['from']), _event_at(ev, g['to']) if g['to'] else None
            spot = start.get('to') or start.get('driver') if start else None
            matrix_spot = ctx.get('spot_for_grid')
            other_region = bool(matrix_spot and spot and spot.replace(' ', '') != matrix_spot.replace(' ', ''))
            add('C05', g['from'], [x['id'] for x in (start, end) if x], [g['id']],
                {'spot': spot, 'minutes': g['minutes'], 'parked_by': start['actor'] if start else None,
                 'rescued_by': end['actor'] if end else None, 'matrix_spot': matrix_spot, 'other_region': other_region})
            if other_region and start and start['actor_class'] == 'HUMAN':
                add('C19', g['from'], [start['id']], [g['id']], {'used': spot, 'matrix_spot': matrix_spot,
                                                               'by': start['actor']}, lever=None)
        elif g['kind'] == 'S9':
            add('C06', g['from'], [], [g['id']], {'grid': g['garage'], 'minutes': g['minutes']})
        elif g['kind'] == 'S2' and (g['minutes'] or 0) > 10 or (g['kind'] == 'S2' and _at_least(g, 'STUCK')):
            rel = _event_at(ev, g['to']) if g['to'] else None
            add('C08', g['from'], [rel['id']] if rel else [], [g['id']],
                {'minutes': g['minutes'], 'released_by': rel['actor'] if rel else None,
                 'released_by_class': rel['actor_class'] if rel else None}, verdict_code='SLOW_RELEASE')
        elif g['kind'] == 'S3' and _at_least(g, 'SLOW') and g.get('driver_state') == 'BUSY':
            add('C09', g['from'], [], [g['id']], {'minutes': g['minutes'], 'driver': g.get('driver'),
                                                  **(ctx.get('blocking') or {}).get(g['id'], {})})
        elif g['kind'] == 'S3' and _at_least(g, 'SLOW') and g.get('driver_state') == 'FREE':
            add('C10', g['from'], [], [g['id']], {'minutes': g['minutes'], 'driver': g.get('driver'),
                                                  **(ctx.get('driver_info') or {}).get(g['id'], {}),
                                                  'note': 'FSL does not record why a driver did not accept'})
        elif g['kind'] == 'S5' and _at_least(g, 'STUCK'):
            add('C14', g['from'], [], [g['id']], {'minutes': g['minutes'],
                                                  'miles': (ctx['verdict'].get('evidence') or {}).get('pick_miles')})
        elif g['kind'] == 'S6' and _at_least(g, 'STUCK'):
            add('C15', g['from'], [], [g['id']], {'minutes': g['minutes'], 'work_type': g.get('work_type')})
    _decision_causes(ctx, add)
    _member_causes(ctx, add, segs)
    out.sort(key=lambda c: (c['ts'] or '', c['code']))
    head = headline(out, ctx['verdict'], segs)
    if head:
        head['headline'] = True
    return out


def _decision_causes(ctx, add):
    v, rec = ctx['verdict'], ctx['record']
    dec = rec['decision']
    if dec.get('n_pre_dispatch_picks', 0) >= 3 or 'OPTIMIZER_CHURN' in (v.get('flags') or []):
        picks = [e for e in ctx['events'] if e.get('assigned') and e.get('driver')]
        add('C07', picks[0]['ts'] if picks else rec['created'], [e['id'] for e in picks],
            evidence={'picks': len(picks), 'before_dispatch': dec.get('n_pre_dispatch_picks')},
            verdict_code='OPTIMIZER_CHURN', diag=diagnosis('OPTIMIZER_CHURN', 'FSL_ENGINE' if any(
                e['actor_class'] == 'FSL_ENGINE' for e in picks) else None))
    moves_in = [e for e in ctx['events'] if e.get('moved') and e['to'] == ctx.get('final_garage')
                and e['place_kind'] == 'GARAGE' and place_kind(e.get('from'), ctx['cfg']) == 'GARAGE']
    if rec['territory_moves']['in'] and moves_in:
        e = moves_in[-1]
        add('C12', e['ts'], [e['id']], evidence={'minutes_before_move': round(
            (parse_dt(e['ts']) - parse_dt(rec['created'])).total_seconds() / 60, 1), 'by': e['actor']},
            verdict_code='INBOUND_CASCADE')
    code = v.get('primary')
    if v.get('source') == 'day_snapshot' and code in DECISION_LEVER:
        ev = v.get('evidence') or {}
        cls = ev.get('final_actor_class')
        add('C13', ev.get('decision_ts') or rec['milestones']['t_asg'], [],
            evidence={k: ev.get(k) for k in ('pick_miles', 'pick_open_jobs', 'closest_q_miles', 'closest_free_q_miles',
                                                'final_actor', 'final_actor_class')},
            verdict_code=code, lever='L01' if cls == 'INTEGRATION' and code in ('STACKED', 'FAR_PICK') else DECISION_LEVER[code],
            diag=diagnosis(code, cls))


def _member_causes(ctx, add, segs):
    pta, sms, rec = ctx['pta'], ctx['sms'], ctx['record']
    if pta.get('rebased'):
        add('C16', pta['rebased']['ts'], [], evidence={
            'initial_min': pta['initial_min'], 'final_min': pta['final_min'], 'due_initial': pta['due_initial'],
            'due_final': pta['due_final'], 'met_initial': pta['met_initial'], 'met_final': pta['met_final'],
            'by': pta['rebased']['actor']})
    for w in sms.get('why_not') or []:
        if w['code'] in ('NOT_OPTED_IN', 'TIMER_RESTARTED', 'NO_STILL_WORKING_TEXT', 'NO_TEXT_LOGGED'):
            add('C17', rec['created'], [], evidence={'reason': w['code'], 'text': w['text'],
                                                     'restarts': w.get('restarts')}, lever=None)
            break
    end = rec['milestones']
    if (end.get('end_status') or '').lower().startswith('cancel'):
        stuck_open = [g for g in segs if g['kind'] in ('S7', 'S8', 'S9') and g['to'] == end['t_end']]
        if stuck_open or not rec.get('final_driver_id'):
            add('C18', end['t_end'], [], [g['id'] for g in stuck_open], {
                'cancel_reason': rec.get('cancel_reason'), 'where': stuck_open[0]['kind'] if stuck_open else 'no driver'})


def headline(causes: list, verdict: dict, segs: list):
    """The report-card primary verdict's cause; for Towbook (not graded) the first CRITICAL segment's cause."""
    code = HEADLINE_BY_CODE.get(verdict.get('primary'))
    if code:
        hit = next((c for c in causes if c['code'] == code), None)
        if hit:
            return hit
    for g in segs:
        if g['severity'] == 'CRITICAL':
            want = SEGMENT_CAUSE.get(g['kind']) or ('C09' if g.get('driver_state') == 'BUSY' else 'C10')
            hit = next((c for c in causes if c['code'] == want and g['id'] in c['segment_ids']), None)
            if hit:
                return hit
    return None


def bullets(causes: list) -> list:
    """Deterministic sentences, one per cause, in time order. Always shown; the AI paragraph is optional."""
    out = []
    for c in causes:
        e = c['evidence']
        text = {
            'C01': lambda: 'Higher-ranked garages were skipped as closed at that hour (inferred from current hours): '
                           + ', '.join(f"rank {s['rank']} {s['garage']}" for s in e['skipped']) + '.',
            'C02': lambda: f"{e['garage']} declined via Towbook in {e['seconds']} s"
                           + (' (within a minute, consistent with an automatic rule)' if e['automatic_like'] else '')
                           + (f"; reason: {e['reason']}" if e['reason'] else '')
                           + (f"; next tried: {e['next_garage']}" if e['next_garage'] else '') + '.',
            'C03': lambda: f"The driver rejected the call ({e['reason']}).",
            'C04': lambda: f"After the rejection nobody owned the call for {e['minutes']} min"
                           + (f" until {e['acted_by']} acted" if e['acted_by'] else '') + '.',
            'C05': lambda: f"The call was parked in {e['spot']} for {e['minutes']} min"
                           + (f" by {e['parked_by']}" if e['parked_by'] else '')
                           + (f"; rescued by {e['rescued_by']}" if e['rescued_by'] else '') + '.',
            'C06': lambda: f"The call sat in grid zone {e['grid']} with no garage for {e['minutes']} min.",
            'C07': lambda: f"The call was assigned {e['before_dispatch']} times before it was first dispatched.",
            'C08': lambda: f"Assigned but not released for {e['minutes']} min"
                           + (f"; released by {e['released_by']}" if e['released_by'] else '') + '.',
            'C09': lambda: f"Dispatched to a busy driver ({e['driver']}) and not accepted for {e['minutes']} min"
                           + (f": still on {e['blocking_sa']} ({e['blocking_on_scene_min']} min on scene)"
                              if e.get('blocking_sa') else '') + '.',
            'C10': lambda: f"Dispatched to a free driver ({e['driver']}) who did not accept for {e['minutes']} min.",
            'C11': lambda: f"{e['by']} pulled the call back after dispatch"
                           + (f"; {e['minutes_lost']} min lost before it was dispatched again" if e['minutes_lost'] else '') + '.',
            'C12': lambda: f"The call reached this garage {e['minutes_before_move']} min after it was created, from another garage.",
            'C13': lambda: f"Report card verdict {c['verdict_code']} at the final decision"
                           + (f" (pick {e['pick_miles']} mi, {e['pick_open_jobs']} open jobs)" if e.get('pick_miles') is not None else '') + '.',
            'C14': lambda: f"The drive took {e['minutes']} min.",
            'C15': lambda: f"On scene for {e['minutes']} min.",
            'C16': lambda: f"PTA re-based from {e['initial_min']:g} to {e['final_min']:g} min by {e['by']}: "
                           f"{'met' if e['met_initial'] else 'missed'} against the original promise, "
                           f"{'met' if e['met_final'] else 'missed'} against the new one.",
            'C17': lambda: e['text'],
            'C18': lambda: f"Canceled while the call had no owner ({e['where']})"
                           + (f": {e['cancel_reason']}" if e['cancel_reason'] else '') + '.',
            'C19': lambda: f"{e['by']} used {e['used']}, not the grid's own SPOT ({e['matrix_spot']}).",
        }[c['code']]()
        out.append({'text': text, 'cause_codes': [c['code']], 'event_ids': c['event_ids'], 'headline': c['headline']})
    return out


NO_DELAY = "No delay found; the call ran within this garage's normal times."
