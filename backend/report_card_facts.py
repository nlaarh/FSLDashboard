"""Scheduler Report Card: deterministic day fact sheet + template narrative. Pure, no I/O.

architecture.md section 11 (AI from fact sheets only) and metrics-spec.md 10A.2 (finding -> likely config
cause -> lever) and 12 (lever whitelist). Every number the narrative may use is a fact here. Drivers
are anonymised as D1, D2... (by calls assigned); the real-name map stays server-side.
"""

import hashlib
import json
import re
from collections import Counter, defaultdict

from utils import parse_dt, to_eastern

FACTS_VERSION = 'facts-v3'
FAILURE = ('BOUNCED', 'STACKED', 'FAR_PICK', 'LATE_DESPITE_CAPACITY')
SEVERITY_RANK = {'high': 0, 'medium': 1, 'low': 2}

# metrics-spec section 12, verbatim ids. The AI may only recommend these.
LEVERS = {
    'L01': ('Add an open-jobs penalty or cap to IT System User driver picks made without FSL auto-schedule', 'Integration team', False),
    'L02': ('Route IT System User picks without auto-schedule through FSL auto-schedule (FSL__Auto_Schedule__c) instead of a direct write', 'Dispatch systems + integration team', True),
    'L03': ('Add a territory-wide rebalance pass for queued SAs when a qualified driver goes idle (RSO is single-resource)', 'FSL admin (Apex RSO)', False),
    'L04': ("Rebalance the 'Copy of Highest Priority' weights (raise Minimize Travel vs ASAP)", 'FSL admin', True),
    'L05': ('Limit In-Day reshuffles of not-yet-dispatched SAs (commit after first pick or near PTA)', 'FSL admin', True),
    'L06': ('Dispatcher pull-back review and coaching', 'Dispatch supervisor', None),
    'L07': ('Add capacity or shift coverage in the hour blocks where CAPACITY_SHORT concentrates', 'Ops / workforce', None),
    'L08': ('Faster rescue from Towbook garages / priority-matrix review', 'Ops + priority matrix owner', None),
    'L09': ('Driver execution coaching (accept -> en route, travel)', 'Fleet supervisor', None),
    'L10': ('Fix skill / truck-capability data or the assignment rule humans use', 'Fleet admin', None),
    'L11': ('Truck-login / GPS hygiene', 'Fleet admin', None),
    'L12': ('Add a Maximum Travel From Home work rule to the active policy', 'FSL admin', True),
    'L13': ('Add Secondary territory memberships for neighbouring garages', 'FSL admin', True),
}

# Plain action for ops directors: (owner, action). {policy} is filled from the captured config.
LEVER_ACTIONS = {
    'L01': ('Integration team', "stop IT System User picks made without FSL auto-schedule from giving calls to busy drivers"),
    'L02': ('Dispatch systems', "send IT System User picks that skip FSL auto-schedule through FSL auto-schedule instead"),
    'L03': ('FSL admin', "add a rebalance step that moves waiting calls to a driver who has just become free"),
    'L04': ('FSL admin', "raise the travel weight in '{policy}' so the closest driver wins more often"),
    'L05': ('FSL admin', "lock a call to its driver after the first pick instead of reshuffling it"),
    'L06': ('Dispatch supervisor', "review pull-backs with the dispatchers involved"),
    'L07': ('Operations', "add drivers or shift coverage in the hours where calls ran short"),
    'L08': ('Operations', "speed up rescues of calls stuck at Towbook garages"),
    'L09': ('Fleet supervisor', "coach drivers on accepting and getting on the road quickly"),
    'L10': ('Fleet admin', "fix driver skill and truck equipment records"),
    'L11': ('Fleet admin', "make drivers log into their truck before they take calls"),
    'L12': ('FSL admin', "add a maximum travel distance rule to '{policy}'"),
    'L13': ('FSL admin', "let neighbouring garages' drivers cover this territory (secondary memberships)"),
}


def _pct(n, d):
    return round(100 * n / d) if d else 0


def _hour_label(h):
    nxt = (h + 1) % 24
    ampm = lambda x: f"{(x % 12) or 12} {'AM' if x < 12 else 'PM'}"
    return f'{h:02d}:00-{nxt:02d}:00 ET ({ampm(h)}-{ampm(nxt)})'


class _Sheet:
    def __init__(self):
        self.facts = []

    def add(self, kind, label, value, display, **extra):
        f = {'id': f'F{len(self.facts) + 1}', 'kind': kind, 'label': label, 'value': value, 'display': display, **extra}
        self.facts.append(f)
        return f['id']


def driver_aliases(rows: list, snapshot: dict) -> dict:
    order = [r['id'] for r in rows] + [d['id'] for d in snapshot['drivers'] if d['id'] not in {r['id'] for r in rows}]
    return {did: f'D{i + 1}' for i, did in enumerate(order)}


def anonymise(text: str, names: dict, alias: dict) -> str:
    for did, name in sorted(names.items(), key=lambda kv: -len(kv[1] or '')):
        if name and did in alias:
            text = text.replace(name, alias[did])
    return text


def build_fact_sheet(snapshot: dict, verdicts: dict, rows: list, summary: dict, rules: dict) -> tuple:
    """-> (fact_sheet, driver_map {alias: name}). Deterministic for the same inputs."""
    alias = driver_aliases(rows, snapshot)
    names = {d['id']: d['name'] for d in snapshot['drivers']}
    sas = {sa['id']: sa for sa in snapshot['sas'] if sa['id'] in verdicts}
    num = {k: sa['number'] for k, sa in sas.items()}
    ev = {k: v['evidence'] for k, v in verdicts.items()}
    ex = lambda ids: sorted(num[i] for i in ids)[:5]
    sh = _Sheet()
    ids = {}

    fr = summary['failure_rate']
    ids['calls'] = sh.add('total', 'Scored calls (ERS, created this day, no Tow Drop-Off)', len(verdicts), str(len(verdicts)))
    ids['failure'] = sh.add('rate', 'Scheduler failures among graded decisions (BOUNCED, STACKED, FAR_PICK, LATE_DESPITE_CAPACITY)',
                            fr['value'], f"{fr['failures']} of {fr['graded']} ({_pct(fr['failures'], fr['graded'])}%)",
                            n=fr['graded'], count=fr['failures'])
    m13 = summary['M13']
    ids['pta'] = sh.add('rate', 'PTA met (arrived calls)', m13['value'], f"{m13['met']} of {m13['n']} ({_pct(m13['met'], m13['n'])}%)",
                        n=m13['n'], count=m13['met'], missed=m13['n'] - m13['met'])
    late = member_wait(sas, rules)
    basis = 'original promise' if rules.get('pta_basis') == 'initial' else 'current PTA'
    ids['late'] = sh.add('impact', f'Minutes members waited past the {basis} (arrival, or the member cancel time), all late calls',
                         sum(late.values()), f"{sum(late.values()):,} minutes on {len(late)} late calls", calls=len(late))
    ids['resp'] = sh.add('metric', 'Median response, minutes', summary['M12']['median'], f"{summary['M12']['median']} min")
    m20 = summary['M20']
    ids['m20'] = sh.add('rate', 'Decisions where a qualified driver >0.5 mi closer was idle',
                        _pct(m20['idle_closer'], m20['n']) / 100, f"{m20['idle_closer']} of {m20['n']}", n=m20['n'], count=m20['idle_closer'])
    m17 = summary['M17']
    ids['m17'] = sh.add('rate', 'Closest qualified driver picked (straight-line)', _pct(m17['picked'], m17['n']) / 100,
                        f"{m17['picked']} of {m17['n']} ({_pct(m17['picked'], m17['n'])}%)", n=m17['n'], count=m17['picked'], band=m17['band'])
    by_code = defaultdict(list)
    for k, v in verdicts.items():
        by_code[v['code']].append(k)
    for code in sorted(by_code, key=lambda c: (-len(by_code[c]), c)):
        ids[f'code:{code}'] = sh.add('verdict', f'Calls with verdict {code}', len(by_code[code]),
                                     f'{len(by_code[code])} of {len(verdicts)}', examples=ex(by_code[code]))
    by_flag = defaultdict(list)
    for k, v in verdicts.items():
        for fl in v['flags']:
            by_flag[fl].append(k)
    for fl in sorted(by_flag):
        ids[f'flag:{fl}'] = sh.add('flag', f'Calls flagged {fl}', len(by_flag[fl]), f'{len(by_flag[fl])} of {len(verdicts)}',
                                   examples=ex(by_flag[fl]))
    by_actor = defaultdict(list)
    for k, e in ev.items():
        if e['final_actor_class']:
            by_actor[e['final_actor_class']].append(k)
    for cls in sorted(by_actor, key=lambda c: -len(by_actor[c])):
        fails = [k for k in by_actor[cls] if verdicts[k]['code'] in FAILURE]
        ids[f'actor:{cls}'] = sh.add('pattern', f'Final decisions by {cls}: count, and scheduler failures among them',
                                     len(by_actor[cls]), f'{len(by_actor[cls])} decisions, {len(fails)} failures',
                                     count=len(fails), examples=ex(fails))
    _hour_patterns(sh, ids, sas, ev, verdicts, ex)
    _driver_patterns(sh, ids, sas, ev, verdicts, ex, rows, alias, names)
    _config_facts(sh, ids, snapshot)
    diagnosis = _diagnose(sh, ids, verdicts, ev, rows, rules, ex, alias, late, num)
    used = sorted({g['lever_id'] for g in diagnosis})
    sheet = {
        'facts_version': FACTS_VERSION, 'rules_version': rules['rules_version'],
        'scope': {'garage': snapshot['territory']['name'], 'service_date': snapshot['service_date'],
                  'day_mode': snapshot['channel_summary']['mode']},
        'facts': sh.facts, 'diagnosis': diagnosis,
        'levers': [{'lever_id': k, 'lever': LEVERS[k][0], 'owner': LEVERS[k][1], 'fsl_native': LEVERS[k][2],
                    'action': next(g['action'] for g in diagnosis if g['lever_id'] == k)} for k in used],
        'caveats': ['Availability is observed, not counterfactual.', 'Distances are straight-line.',
                    'Skills and truck capabilities are current values.', 'Policy config is as of the build, not that day.'],
    }
    return sheet, {a: names.get(did) for did, a in alias.items()}


def _hour_patterns(sh, ids, sas, ev, verdicts, ex):
    by_hour = defaultdict(list)
    for k, sa in sas.items():
        by_hour[to_eastern(sa['created']).hour].append(k)
    misses = {h: [k for k in ks if ev[k]['pta_met'] is False] for h, ks in by_hour.items()}
    for h in sorted(misses, key=lambda h: (-len(misses[h]), h))[:3]:
        if len(misses[h]) < 2:
            continue
        arrived = [k for k in by_hour[h] if ev[k]['pta_met'] is not None]
        short = [k for k in misses[h] if verdicts[k]['code'] == 'CAPACITY_SHORT']
        ids[f'hour:{h}'] = sh.add('pattern', f'PTA missed, calls created {_hour_label(h)}', len(misses[h]),
                                  f'{len(misses[h])} of {len(arrived)} arrived calls missed PTA; {len(short)} CAPACITY_SHORT',
                                  n=len(arrived), count=len(short), examples=ex(misses[h]))


def _driver_patterns(sh, ids, sas, ev, verdicts, ex, rows, alias, names):
    by_drv = defaultdict(list)
    for k, sa in sas.items():
        if sa['final_driver_id']:
            by_drv[sa['final_driver_id']].append(k)
    miss = {d: [k for k in ks if ev[k]['pta_met'] is False] for d, ks in by_drv.items()}
    for d in sorted(miss, key=lambda d: (-len(miss[d]), alias.get(d, '')))[:3]:
        if len(miss[d]) < 2:
            continue
        arrived = [k for k in by_drv[d] if ev[k]['pta_met'] is not None]
        ids[f'driver_miss:{d}'] = sh.add('pattern', f'{alias.get(d)}: PTA missed on calls they served', len(miss[d]),
                                         f'{len(miss[d])} of {len(arrived)} arrived calls', driver=alias.get(d), examples=ex(miss[d]))
    counts = Counter(r['health'] for r in rows)
    ids['health'] = sh.add('health', 'Driver-day health (h1): healthy / watch / unhealthy', counts['unhealthy'],
                           f"{counts['healthy']} healthy, {counts['watch']} watch, {counts['unhealthy']} unhealthy")
    for r in rows:
        if r['health'] == 'healthy':
            continue
        h = r['health_detail']
        mine = [k for k in by_drv.get(r['id'], []) if verdicts[k]['code'] != 'GOOD'] or by_drv.get(r['id'], [])
        ids[f'health:{r["id"]}'] = sh.add(
            'health', f"{alias[r['id']]} health {r['health']} (owner: {h['owner']})",
            {'workload': h['lenses']['workload'], 'execution': h['lenses']['execution']},
            '; '.join(anonymise(x['text'], names, alias) for x in h['reasons']),
            driver=alias[r['id']], owner=h['owner'], health=r['health'], examples=ex(mine))


def _config_facts(sh, ids, snap):
    cfg = snap.get('config') or {}
    runs = (snap.get('optimizer_sf') or {}).get('requests') or []
    ids['runs'] = sh.add('config', 'FSL optimization runs on this garage or its drivers that day', len(runs), f'{len(runs)} runs')
    pols = cfg.get('policies_used') or []
    if pols:
        p = pols[0]
        w = {o['goal']: o['weight'] for o in p.get('objectives') or []}
        ids['policy'] = sh.add('config', f"Main optimizer policy '{p['name']}': runs and objective weights", p['seen_in_runs'],
                               f"{p['seen_in_runs']} of {len(runs)} runs; " + ', '.join(f'{g} {int(v)}' for g, v in w.items() if v is not None),
                               weights={g: v for g, v in w.items()}, policy_name=p['name'])
        ids['max_travel'] = sh.add('config', f"Policy '{p['name']}' has a Maximum Travel From Home work rule",
                                   int(any('travel from home' in (r['name'] or '').lower() for r in p.get('work_rules') or [])),
                                   'yes' if any('travel from home' in (r['name'] or '').lower() for r in p.get('work_rules') or []) else 'no')
    mt = cfg.get('membership_types') or {}
    ids['members'] = sh.add('config', 'Territory memberships by type (P = primary, S = secondary)', sum(mt.values()),
                            ', '.join(f'{k} {v}' for k, v in sorted(mt.items())), types=mt)


def _sev(n, total, failure=False):
    share = n / total if total else 0
    return 'high' if share >= 0.10 or (failure and n >= 5) else 'medium' if share >= 0.03 or failure else 'low'


def _diagnose(sh, ids, verdicts, ev, rows, rules, ex, alias, late, num) -> list:
    """metrics-spec 10A.2 as deterministic rules. Wording is 'consistent with', never 'caused by'."""
    total = len(verdicts)
    with_flag = lambda fl: [k for k, v in verdicts.items() if fl in v['flags']]
    with_code = lambda c: [k for k, v in verdicts.items() if v['code'] == c]
    pol = next((f for f in sh.facts if f['id'] == ids.get('policy')), None)
    pname = pol['policy_name'] if pol else 'the active policy'
    out = []

    def pair(finding, refs, owner, n, count_of, sev, cause, lever, calls, title, tags, **extra):
        """`count` is always one unit, named by `count_of`. Member impact = minutes past PTA on these calls."""
        missed = [k for k in calls if k in late]
        impact = sum(late[k] for k in missed)
        top = max(missed, key=lambda k: late[k]) if missed else None
        if top and late[top] > impact / 2 and len(missed) > 1:      # spec 5B refinement 3
            extra['mostly_one_call'] = num[top]
        who, what = LEVER_ACTIONS[lever][0], LEVER_ACTIONS[lever][1].format(policy=pname)
        out.append({'id': f'G{len(out) + 1}', 'finding_fact': finding, 'config_refs': [r for r in refs if r],
                    'owner': owner, 'severity': sev, 'cause': cause, 'lever_id': lever,
                    'example_sas': ex(sorted(calls, key=lambda k: -late.get(k, 0))),
                    'count': n, 'count_of': count_of, 'plain_title': _singular(title), 'tags': tags,
                    'impact_minutes': impact, 'late_calls': len(missed),
                    'action': f'{who}: {what}', 'headline_action': f'{what[0].upper()}{what[1:]} ({who})', **extra})

    # Spec B4a: Mulesoft/Replicant picks (and stamped IT System User picks) are FSL auto-schedule under r2. Only the
    # integration picks left (no auto-schedule stamp) are decided outside Salesforce code. FSL__Scheduling_Policy_Used__c
    # is never populated in this org, so it is never cited.
    integ_final = [k for k, e in ev.items() if e['final_actor_class'] == 'INTEGRATION']
    if total and len(integ_final) >= 3 and len(integ_final) / total >= 0.10:
        stamped = bool(rules.get('auto_schedule'))
        pair(ids['actor:INTEGRATION'], [], 'process', len(integ_final),
             'calls whose final pick was IT System User without FSL auto-schedule' if stamped
             else 'calls whose final pick was written by an integration account', _sev(len(integ_final), total),
             'Consistent with the pick being decided outside Salesforce code (no FSL auto-schedule stamp, most likely the '
             'MuleSoft service; unconfirmed with the integration team), so no scheduling policy or workload rule was checked'
             if stamped else 'Integration-account picks; rules r1 cannot tell FSL auto-schedule picks apart (use r2)',
             'L02', integ_final,
             (f'{len(integ_final)} calls were assigned by IT System User without FSL auto-schedule, so no scheduling rules '
              'were checked') if stamped else f'{len(integ_final)} calls were assigned by integration accounts',
             ['INTEGRATION', 'BYPASSED_OPTIMIZER'])
    rebalance = sorted(set(with_flag('MISSED_REBALANCE')) | set(with_code('STACKED')) | set(with_code('LATE_DESPITE_CAPACITY')))
    sched_health = [r for r in rows if r['health'] != 'healthy' and r['health_owner'] in ('scheduler', 'both')
                    and any(i['id'] in ('H1', 'H2') and i['band'] in ('watch', 'bad') for i in r['health_detail']['inputs'])]
    if rebalance or sched_health:
        pair(ids.get('flag:MISSED_REBALANCE') or ids.get('code:LATE_DESPITE_CAPACITY') or ids['health'],
             [ids['health'], ids.get('policy')] + [ids[f"health:{r['id']}"] for r in sched_health], 'scheduler',
             len(rebalance), 'calls with MISSED_REBALANCE, STACKED or LATE_DESPITE_CAPACITY',
             'high' if any(r['health'] == 'unhealthy' for r in sched_health) else 'medium',
             "Consistent with no workload-balance objective in this org's goal types and RSO re-optimising one "
             'resource at a time, so queued work is not moved to a driver who goes idle', 'L03', rebalance,
             f'{len(rebalance)} calls went to a busy or farther driver while a qualified driver was free nearby',
             ['MISSED_REBALANCE', 'STACKED', 'LATE_DESPITE_CAPACITY'],
             drivers_with_scheduler_owned_health=[f"{alias[r['id']]} ({r['health']})" for r in sched_health])
    integ = [k for k in with_code('STACKED') + with_code('FAR_PICK') if ev[k]['final_actor_class'] == 'INTEGRATION']
    if integ:
        pair(ids.get('code:STACKED') or ids['code:FAR_PICK'], [ids['actor:INTEGRATION']], 'scheduler',
             len(integ), 'STACKED or FAR_PICK calls whose final pick was IT System User without FSL auto-schedule',
             _sev(len(integ), total, True),
             'Consistent with the pick being decided outside Salesforce code (no FSL auto-schedule stamp), so no '
             'scheduling policy or workload rule was checked', 'L01', integ,
             f'{len(integ)} calls were given by IT System User to a busy or farther driver without FSL auto-schedule',
             ['STACKED', 'FAR_PICK', 'INTEGRATION'])
    far = [k for k in with_code('FAR_PICK') if ev[k]['final_actor_class'] == 'FSL_ENGINE']
    fsl = [k for k, e in ev.items() if e.get('graded') and e['final_actor_class'] == 'FSL_ENGINE']
    fsl_far = sorted((k for k in fsl if not ev[k]['picked_closest']), key=lambda k: -(ev[k]['extra_miles'] or 0))
    if fsl:   # spec 10A.2: the travel-weight cause applies to the optimizer's own picks only
        ids['fsl_closest'] = sh.add('rate', 'Closest qualified driver picked, FSL optimizer final decisions only',
                                    _pct(len(fsl) - len(fsl_far), len(fsl)) / 100,
                                    f'{len(fsl) - len(fsl_far)} of {len(fsl)} ({_pct(len(fsl) - len(fsl_far), len(fsl))}%)',
                                    n=len(fsl), count=len(fsl) - len(fsl_far), examples=ex(fsl_far))
    if pol and fsl and (far or (len(fsl) - len(fsl_far)) / len(fsl) < rules['metric_bands']['M17']['watch'][0]):
        pair(ids.get('code:FAR_PICK') if far else ids['fsl_closest'], [ids['policy']], 'scheduler', len(far) or len(fsl_far),
             'FSL optimizer final picks that were FAR_PICK' if far else 'FSL optimizer final picks that were not the closest',
             _sev(len(far), total, True) if far else 'medium',
             f"Consistent with policy '{pname}' weighting Minimize Travel far below ASAP: the optimizer picks the "
             'soonest driver, not the closest', 'L04', far or fsl_far,
             (f"{len(far)} optimizer picks sent a driver more than {rules['params']['FAR_PICK']['extra_mi']:g} miles "
              'farther than a free one' if far else
              f'{len(fsl_far)} optimizer picks sent a farther driver when a closer qualified one was available'),
             ['FAR_PICK', 'FSL_ENGINE'] if far else ['FSL_ENGINE'], far_pick_extra_mi=rules['params']['FAR_PICK']['extra_mi'])
        if any((ev[k].get('extra_free_miles') or 0) > 15 for k in far) and ids.get('max_travel'):
            pair(ids['code:FAR_PICK'], [ids['max_travel']], 'scheduler', len(far), 'FSL optimizer FAR_PICK calls', 'medium',
                 f"Consistent with no Maximum Travel From Home rule in '{pname}'", 'L12', far,
                 f'{len(far)} far-away picks had no travel limit to stop them', ['FAR_PICK'])
    churn = with_flag('OPTIMIZER_CHURN')
    if total and len(churn) / total >= 0.10:
        pair(ids['flag:OPTIMIZER_CHURN'], [ids['runs']], 'scheduler', len(churn), 'calls flagged OPTIMIZER_CHURN', _sev(len(churn), total),
             'Consistent with In-Day and RSO optimization re-running every few minutes on calls that are not yet dispatched',
             'L05', churn, f'{len(churn)} calls were reshuffled between drivers before anyone was sent',
             ['OPTIMIZER_CHURN'])
    for code, owner, lever, cause, refs, title in (
        ('CAPACITY_SHORT', 'capacity', 'L07', 'No qualified driver was free nearby when these calls needed one', [],
         '{n} calls ran late because no qualified driver was free nearby'),
        ('INBOUND_CASCADE', 'process', 'L13', 'Consistent with primary-only territory memberships: rescues from neighbouring '
                                              'garages are manual', [ids['members']],
         '{n} calls reached this garage late, after starting at another garage'),
        ('LATE_EXECUTION', 'driver', 'L09', 'Sound, quick picks to free drivers that still arrived late', [],
         '{n} calls ran late even though a free driver was sent quickly'),
    ):
        ks = with_code(code)
        if ks:
            pair(ids[f'code:{code}'], refs, owner, len(ks), f'calls with verdict {code}', _sev(len(ks), total), cause, lever, ks,
                 title.format(n=len(ks)), [code])
    bounced = [k for k in with_code('BOUNCED') if ev[k]['final_actor_class'] == 'HUMAN']
    if bounced:
        pair(ids['code:BOUNCED'], [], 'process', len(bounced), 'BOUNCED calls whose final decision was by a dispatcher (HUMAN)', _sev(len(bounced), total, True),
             'Driver pulled back or changed after dispatch, finished by a dispatcher', 'L06', bounced,
             f'{len(bounced)} calls were pulled back from a driver after dispatch and reassigned by a dispatcher',
             ['BOUNCED', 'HUMAN'])
    for flag, lever, cause, title in (
            ('SKILL_MISMATCH', 'L10', 'Match Skills checks resource skills while truck capabilities live on the truck asset',
             '{n} calls went to a driver without the required skill or truck equipment'),
            ('ASSIGNED_OFF_SHIFT', 'L11', 'Consistent with availability rules that do not use truck login '
                                          '(the Shift object is empty)',
             '{n} calls were given to drivers who were not yet logged into a truck')):
        ks = with_flag(flag)
        if ks:
            pair(ids[f'flag:{flag}'], [], 'process', len(ks), f'calls flagged {flag}', 'low', cause, lever, ks,
                 title.format(n=len(ks)), [flag])
    # Product owner: order by member impact (minutes past PTA on the finding's calls), then severity.
    return sorted(out, key=lambda g: (-g['impact_minutes'], SEVERITY_RANK[g['severity']], -g['count'], g['id']))


MEMBER_CANCEL_REASONS = {'member could not wait', 'member found own service', 'member got themselves going',
                         'passerby assisted', 'ivr cancellation'}


def member_wait(sas: dict, rules: dict) -> dict:
    """Spec 5B: minutes past the promise per call, {sa_id: minutes > 0}. Promise = original (r2) or current (r1).
    End = arrival; a member cancel after the promise counts to the cancel time. PTA <= 0 or >= 999 counts 0."""
    initial = rules.get('pta_basis') == 'initial'
    out = {}
    for k, sa in sas.items():
        due, pta = parse_dt(sa['pta_initial_due' if initial else 'pta_due']), sa.get('pta_initial_min' if initial else 'pta_min')
        if not due or not pta or not 0 < pta < 999:
            continue
        m = sa['milestones']
        end = parse_dt(m['arrival'])
        if end is None and (sa.get('cancel_reason') or '').strip().lower() in MEMBER_CANCEL_REASONS:
            end = parse_dt(m['t_end'])
        if end and end > due:
            out[k] = round((end - due).total_seconds() / 60)
    return {k: v for k, v in out.items() if v > 0}


def fact_hash(sheet: dict) -> str:
    return hashlib.sha256(json.dumps(sheet, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def template_narrative(sheet: dict) -> dict:
    """Deterministic plain-English findings from the diagnosis (top 5 by member impact). Always validates."""
    fail = next(x for x in sheet['facts'] if x['label'].startswith('Scheduler failures'))
    pta = next(x for x in sheet['facts'] if x['label'].startswith('PTA met'))
    findings = [{'diagnosis_id': g['id'], 'title': g['plain_title'], 'text': _impact_sentence(g)}
                for g in sheet['diagnosis'][:5]]
    top = next((g for g in sheet['diagnosis'] if g['impact_minutes']), sheet['diagnosis'][0] if sheet['diagnosis'] else None)
    head = (f"{fail['count']} of {fail['n']} graded calls ({_pct(fail['count'], fail['n'])}%) were scheduled poorly, "
            f"and {pta['missed']} calls missed their promised arrival time.")
    if top:
        head += f" The biggest lever: {top['headline_action']}."
    return {'headline': head, 'headline_refs': [fail['id'], pta['id']] + ([top['id']] if top else []),
            'findings': findings}


def _singular(title: str) -> str:
    """'1 calls were ...' -> '1 call was ...' for the deterministic titles."""
    if not title.startswith('1 '):
        return title
    return re.sub(r'^1 (call|pick)s\b', r'1 \1', title).replace(' were ', ' was ', 1)


def _impact_sentence(g: dict) -> str:
    if not g['impact_minutes']:
        return 'None of these calls missed the promised arrival time.'
    out = (f"Members waited {g['impact_minutes']:,} minutes past their promised arrival time on "
           f"{g['late_calls']} of these calls.")
    if g.get('mostly_one_call'):
        out += f" Mostly one call ({g['mostly_one_call']})."
    return out
