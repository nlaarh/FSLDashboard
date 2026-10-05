"""Work Order Replay: the takeaways for one call, in plain words. Rules only, no AI.

went_well   what the system and the people did right (each with the number that shows it)
went_wrong  what cost the member time or trust, worst first, each with its evidence and the replay steps that show it
improve     what to change, taken from the existing lever library (report_card_facts.LEVER_ACTIONS) plus a few texting rules
Every line is a sentence built from numbers already in the story (counts, minutes, miles, text outcomes). A threshold decides
good or bad; nothing is guessed. Pure, no I/O.
"""

from report_card_facts import LEVER_ACTIONS
import re

from wo_explain import explain

FAST_FIRST_PICK_S = 120        # a driver was picked within 2 minutes of the call arriving
FAST_ACCEPT_MIN = 5            # the driver accepted within 5 minutes of dispatch
CHURN_PICKS = 3                # this many picks before the first dispatch = optimizer churn
LATE_ETA_TEXT_MIN = 10         # the first "garage and ETA" text later than this after the call arrived is late
FAR_EXTRA_MILES = 1.0          # the pick was this much farther than the closest qualified driver
SEV_WEIGHT = {'bad': 0, 'warn': 1, 'info': 2}
_ETA_LABELS = ('Garage and PTA', 'Garage + PTA')


_SUFFIX = re.compile(r'\s+\d{2,3}[A-Z]{0,2}$')


def _short(n):
    return _SUFFIX.sub('', n or '').strip()


def _mi(x):
    return f'{x:.1f}'


def _min(x):
    x = round(x)
    return f'{x} min' if x < 120 else f'{x // 60} h {x % 60} min'


def _secs(steps):
    import re
    return [int(m.group(1)) for st in steps for m in [re.search(r' in (\d+) s', st['title'])] if m]


def takeaways(story: dict, steps: list) -> dict:
    well, wrong, levers = [], [], {}

    def good(text, step_ids=()):
        well.append({'text': text, 'step_ids': list(step_ids)})

    hdr = story.get('header') or {}

    def bad(text, sev='bad', step_ids=(), lever=None, code=None, **ctx):
        wrong.append({'text': text, 'severity': sev, 'step_ids': list(step_ids), 'explain': explain(code, **ctx) if code else None})
        if lever:
            levers.setdefault(lever, []).append(text)

    by = lambda pred: [s for s in steps if pred(s)]
    assigns = by(lambda s: s['title'].startswith('Assigned to') and not s['names'].get('driver', '').startswith(('SPOT', 'Towbook')))
    dispatches = by(lambda s: 'Released' in s['title'] or 'Auto-released' in s['title'])
    declines = by(lambda s: s['title'].startswith('Garage declined'))
    rejects = by(lambda s: s['title'].startswith('Driver rejected'))
    pullbacks = by(lambda s: s['title'].startswith('Pulled back'))
    ids = lambda xs: [x['id'] for x in xs]
    pta = story.get('pta') or {}
    segs = {g['kind']: g for g in story.get('segments') or []}
    ev = ((story.get('verdict') or {}).get('evidence')) or {}

    # ---- the outcome the member felt: arrival against the promise ----
    if pta.get('arrival') is None:
        bad('No driver arrived at the member on this call.', 'bad', code='NO_SERVICE')
    elif pta.get('margin_initial_min') is not None:
        m = pta['margin_initial_min']
        if m >= 0:
            good(f"The driver arrived {_min(m)} before the original promise of {_min(pta['initial_min'])}.")
        else:
            bad(f"The driver arrived {_min(-m)} after the original promise of {_min(pta['initial_min'])} "
                f"(arrived {_min(pta['response_min'])} after the call).", 'bad', ['P1'] if any(s['id'] == 'P1' for s in steps) else [], code='LATE')
        if pta.get('rebased') and m < 0:
            bad('The promise was re-based later, so on paper this call can look on time. Judged on the first promise it was late.', 'warn', code='REBASED')

    # ---- picking the driver ----
    if assigns:
        first = assigns[0]
        if first['dt'] <= FAST_FIRST_PICK_S:
            good(f"A driver was picked {first['dt']} s after the call arrived.", [first['id']])
        else:
            bad(f"It took {_min(first['dt'] / 60)} to pick the first driver.", 'warn', [first['id']], 'L05')
    first_dispatch_dt = dispatches[0]['dt'] if dispatches else None
    pre = [a for a in assigns if first_dispatch_dt is None or a['dt'] < first_dispatch_dt]
    if len(pre) >= CHURN_PICKS:
        bad(f"The call was assigned {len(pre)} times before it was first released to a driver "
            f"({', '.join(a['names']['driver'] for a in pre)}). Each re-pick restarted the clock.", 'warn', ids(pre), 'L05', code='CHURN')
    elif len(assigns) == 1:
        good('The first driver picked kept the call: it was never re-assigned.', ids(assigns))
    late_picks = [a for a in assigns if first_dispatch_dt is not None and a['dt'] > first_dispatch_dt]
    if late_picks:
        bad(f"The call was re-assigned {len(late_picks)} time{'s' if len(late_picks) != 1 else ''} after it had already been released to a driver.", 'warn', ids(late_picks), 'L06', code='PULLBACK')

    # ---- was it the best choice ----
    if ev.get('pick_miles') is not None and ev.get('closest_q_miles') is not None:
        extra = ev.get('extra_miles') or (ev['pick_miles'] - ev['closest_q_miles'])
        if ev.get('picked_closest'):
            good(f"The closest qualified driver was picked ({_mi(ev['pick_miles'])} mi).")
        elif extra >= FAR_EXTRA_MILES:
            bad(f"A closer qualified driver existed: {_mi(ev['closest_q_miles'])} mi away against the {_mi(ev['pick_miles'])} mi driver picked "
                f"({_mi(extra)} mi farther).", 'warn', ids(assigns[-1:]), 'L04', code='FAR_PICK')
        if (ev.get('pick_open_jobs') or 0) >= 1 and ev.get('closest_free_q_miles') is not None:
            bad(f"The driver picked already had {ev['pick_open_jobs']} other open job{'s' if ev['pick_open_jobs'] != 1 else ''}, "
                f"while a free qualified driver was {_mi(ev['closest_free_q_miles'])} mi away.", 'warn', ids(assigns[-1:]), 'L03', code='BUSY_PICK')
        elif (ev.get('pick_open_jobs') or 0) == 0:
            good('The driver picked had no other open jobs.')

    # ---- waiting for the garage or driver to say yes ----
    s3 = segs.get('S3')
    if s3 and s3.get('severity') in ('SLOW', 'STUCK', 'CRITICAL'):
        who = _short(s3.get('driver')) or 'the driver'
        state = 'a busy driver' if s3.get('driver_state') == 'BUSY' else 'a free driver' if s3.get('driver_state') == 'FREE' else 'a driver'
        bad(f"The call waited {_min(s3['minutes'])} for {who} to accept it. It had been released to {state}"
            f"{' who was still on another job' if s3.get('driver_state') == 'BUSY' else ' who did not accept'}.",
            'bad' if s3['severity'] != 'SLOW' else 'warn', s3.get('event_ids') or [], 'L09' if s3.get('driver_state') == 'FREE' else 'L03',
            code='WAIT_FREE' if s3.get('driver_state') == 'FREE' else 'WAIT_BUSY', minutes=s3['minutes'], driver=_short(s3.get('driver')))
    elif s3 and s3.get('minutes') is not None and s3['minutes'] <= FAST_ACCEPT_MIN:
        good(f"The driver accepted within {max(1, round(s3['minutes']))} min of being released.")
    if len(declines) >= 2:
        fast = [d for d in declines if d['detail'] != 'reason not recorded' or 'in ' in d['title']]
        bad(f"{len(declines)} Towbook garages declined the call one after another, and the call changed hands each time.", 'bad', ids(declines), 'L08', code='DECLINES', seconds=_secs(declines))
    elif len(declines) == 1:
        bad('A Towbook garage declined the call, so it had to move on to the next garage.', 'warn', ids(declines), 'L08', code='DECLINES', seconds=_secs(declines))
    for r in rejects:
        bad(f"The driver rejected the call ({r['detail'] or 'reason not recorded'}).", 'warn', [r['id']], 'L08', code='REJECT', reason=r['detail'])
    if pullbacks:
        bad('A dispatcher pulled the call back from the driver after it was released.', 'warn', ids(pullbacks), 'L06', code='PULLBACK')

    # ---- time with no owner ----
    for kind, label, lever, code in (('S7', 'nobody owned the call after the rejection', 'L08', 'NO_OWNER'), ('S8', 'the call sat parked in the SPOT queue', 'L08', 'PARKED_SPOT'),
                                     ('S9', 'the call sat in a zone with no garage', 'L08', 'STUCK_GRID'), ('S2', 'the call was assigned but not released to the driver', 'L05', 'SLOW_RELEASE')):
        g = segs.get(kind)
        if g and g.get('severity') in ('SLOW', 'STUCK', 'CRITICAL'):
            bad(f"For {_min(g['minutes'])} {label}.", 'bad' if g['severity'] != 'SLOW' else 'warn', g.get('event_ids') or [], lever, code=code,
                ladder=hdr.get('matrix_ladder'), work_type=hdr.get('work_type'), grid=(hdr.get('grid') or {}).get('name'), minutes=g['minutes'])

    # ---- driving and working ----
    s5, s6 = segs.get('S5'), segs.get('S6')
    if s5 and s5.get('severity') in ('STUCK', 'CRITICAL'):
        bad(f"The drive to the member took {_min(s5['minutes'])}.", 'warn', s5.get('event_ids') or [], 'L09', code='LONG_DRIVE')
    elif s5 and s5.get('severity') == 'OK' and s5.get('minutes') is not None:
        good(f"The drive to the member took {_min(s5['minutes'])}, normal for this kind of call.")
    if s6 and s6.get('severity') in ('STUCK', 'CRITICAL'):
        bad(f"The job at the member took {_min(s6['minutes'])}, longer than usual.", 'info', s6.get('event_ids') or [], 'L09', code='LONG_ONSCENE')

    # ---- what the member was told ----
    rows = (story.get('sms') or {}).get('rows') or []
    sent = [r for r in rows if r['outcome'] == 'sent']
    failed = [r for r in rows if r['outcome'] != 'sent']
    sms_ids = [s['id'] for s in steps if s['kind'] == 'sms']
    if failed:
        bad(f"{len(failed)} text{'s' if len(failed) != 1 else ''} to the member did not go out ({', '.join(sorted({r['outcome'] for r in failed}))}).", 'bad', [s['id'] for s in steps if s['kind'] == 'sms' and s.get('flag')],
            code='TEXT_FAILED', reasons=[(r.get('reason'), r['outcome']) for r in failed])
    elif sent:
        good(f"All {len(sent)} texts to the member went out.", sms_ids)
    if not rows and (story.get('sms') or {}).get('source') == 'send_log':
        bad('The member received no texts on this call.', 'bad', code='TEXT_NONE')
    eta = next((s for s in steps if s['kind'] == 'sms' and any(l in s['title'] for l in _ETA_LABELS)), None)
    if eta and eta['dt'] / 60 > LATE_ETA_TEXT_MIN:
        bad(f"The member's first text with the garage and the arrival time came {_min(eta['dt'] / 60)} after the call arrived.", 'bad', [eta['id']], code='TEXT_LATE_ETA')
        levers.setdefault('TXT1', []).append('late first ETA text')
    elif eta:
        good(f"The member got the garage and arrival time within {max(1, round(eta['dt'] / 60))} min.", [eta['id']])
    for w in (story.get('sms') or {}).get('why_not') or []:
        bad(w.get('text') or 'A text that should have gone out did not.', 'bad', [], 'TXT2', code='TEXT_STILL_WORKING')

    wrong.sort(key=lambda x: SEV_WEIGHT.get(x['severity'], 3))
    verdict = ('poor' if any(w['severity'] == 'bad' for w in wrong) and pta.get('margin_initial_min', 0) < 0
               else 'mixed' if wrong else 'good')
    head = {'good': 'This call went well.', 'mixed': 'The call got there, but with avoidable problems.', 'poor': 'This call went wrong for the member.'}[verdict]
    return {'verdict': verdict, 'headline': head, 'went_well': well, 'went_wrong': wrong, 'improve': _improve(levers)}


_TEXT_FIXES = {
    'TXT1': ('Flow owner', 'send the member the garage and arrival time the moment a garage accepts, not when the flow next runs'),
    'TXT2': ('Flow owner', 'make the "still working on it" texts fire again after every decline, rejection or re-spot'),
}


def _improve(levers: dict) -> list:
    out = []
    for code, why in sorted(levers.items(), key=lambda kv: -len(kv[1])):
        owner, action = _TEXT_FIXES.get(code) or LEVER_ACTIONS.get(code, (None, None))
        if action:
            out.append({'owner': owner, 'action': action.replace("'{policy}'", 'the scheduling policy').replace('{policy}', 'the scheduling policy'), 'because': why[:2]})
    return out
