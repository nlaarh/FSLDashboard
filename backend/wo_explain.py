"""Work Order Replay: when something went wrong, WHY it may have happened. Rules and a fixed catalog, no AI.

Each problem has a code, an icon key (the page maps it to an icon), the likely reasons ranked most likely first, and what to check.
The first reasons are built from THIS call's own numbers when we have them (the priority-matrix ladder, the text's outcome, the
minutes waited); the general reasons after them are the usual causes in this org and are worded "may". Salesforce does not record
why a driver did not accept or why a garage declined, so those say so instead of guessing. Pure, no I/O.
"""

# icon keys: warning, zone, spot, owner, hourglass, shuffle, text_off, text_late, no_service, reject, decline, pullback, truck, clock, route, flow
CATALOG = {
    'STUCK_GRID': ('zone', 'Stuck in a zone with no garage', [
        'Every garage ranked for this zone was closed at that hour or was skipped, so nobody could take it.',
        'None of the garages ranked for this zone handles this type of work.',
        'The address may have plotted in the wrong zone, or outside every zone polygon, so no garage list applied to it.',
        'Each garage in the list declined or timed out and nothing sent the call on to the next one.'],
        ['Open the priority matrix for this zone: garage order, hours and the work types each garage covers.',
         'Look at the pin on the map: is it inside the zone polygon it was given?',
         'Check who finally moved the call out of the zone, and when.']),
    'PARKED_SPOT': ('spot', 'Parked in the SPOT queue', [
        'No garage in the matrix accepted the call, so a dispatcher parked it in the SPOT queue until someone could place it.',
        'The call may have been parked in a different region\'s SPOT than the priority matrix names.'],
        ['See who parked it and who rescued it, and how long it waited between the two.']),
    'NO_OWNER': ('owner', 'Nobody owned the call', [
        'A driver rejection hands the call back to the queue, but nothing re-assigns it automatically. It waits until a dispatcher notices.',
        'The Watchlist "Call Not Assigned - Rejected" is the alert meant to catch this.'],
        ['Check whether a dispatcher was watching that list when the rejection happened.']),
    'WAIT_BUSY': ('hourglass', 'Waiting on a busy driver', [
        'The call was released to a driver who was still working another job, so they could not accept yet.',
        'Calls are released on a timer (the auto-release batch), not when a driver becomes free.',
        'The scheduler may have had no free qualified driver nearby, so it picked someone already busy.'],
        ['See which job the driver was on and how long it ran.', 'Check whether a free qualified driver existed at the time (the "right driver" card).']),
    'WAIT_FREE': ('hourglass', 'A free driver did not accept', [
        'The driver was logged in and not busy, but did not accept. Salesforce does not record why.',
        'They may have been away from the app or phone, in a dead zone, or on a break that was not entered.'],
        ['Ask the driver or the fleet supervisor; the data cannot say.']),
    'SLOW_RELEASE': ('clock', 'Assigned but not released', [
        'The call had a driver but was not released to them: it was waiting for the auto-release batch or for a dispatcher.'],
        ['Check who released it and whether releases were running on schedule.']),
    'CHURN': ('shuffle', 'Reassigned again and again', [
        'The optimizer re-runs every few minutes on calls that are not yet released. Each run can pick a different driver as positions and workloads change.',
        'Each new pick restarts the wait for the member.'],
        ['Ask the FSL admin whether not-yet-released calls can be locked to their first pick.']),
    'FAR_PICK': ('route', 'A closer driver existed', [
        'The scheduling policy may weigh "as soon as possible" over "least travel", so the closest driver is not always chosen.',
        'The closest driver may have been judged unavailable at that moment (busy, off shift or no fresh GPS).',
        'The pick may have been made outside the FSL scheduler.'],
        ['Look at the candidate list in the "Why this driver" section of each pick.']),
    'BUSY_PICK': ('hourglass', 'Picked a busy driver over a free one', [
        'The current policy has no objective that spreads work across drivers, so it can stack calls on one driver while others are free.'],
        ['Ask the FSL admin about adding a balance objective.']),
    'DECLINES': ('decline', 'Towbook garages declined', [
        'A Towbook garage that declines within a minute is usually an automatic rule: closed, full, or out of its area.',
        'Each decline moves the call to the next garage in the list, which adds minutes before anyone is working it.'],
        ['Check each garage\'s hours and service area against this address and work type.']),
    'REJECT': ('reject', 'The driver rejected the call', [
        '"Out of Area" means the driver was too far away to take it (the map shows how far).',
        'A rejection sends the call back to the queue; if nothing re-assigns it, it waits.'],
        ['Check how far the driver was and why the call was assigned to someone out of range.']),
    'PULLBACK': ('pullback', 'Pulled back from the driver', [
        'A dispatcher took the call back after it was released, usually because the driver was not accepting or was too far.'],
        ['Review the pull-back with the dispatcher involved.']),
    'LONG_DRIVE': ('truck', 'A long drive', [
        'The driver was far from the member when they set off, or traffic and weather slowed them.'],
        ['Compare the driver\'s distance at the pick with the distance of the closest driver.']),
    'LONG_ONSCENE': ('truck', 'A long job at the member', [
        'Some jobs take longer (tows, lockouts, tire changes). This one ran past what is normal for the work type.'],
        ['Check the work type and whether the job needed a second truck.']),
    'LATE': ('clock', 'Arrived after the promise', [
        'The wait was spent in the steps flagged above (reassigning, declines, waiting to accept, the drive).'],
        ['Look at which flagged step took the longest.']),
    'REBASED': ('clock', 'The promise was changed', [
        'The garage or Towbook changed the arrival time after accepting, so the call can look on time against the new promise.'],
        ['Judge the call against the original promise, as this replay does.']),
    'NO_SERVICE': ('no_service', 'The member did not get service', [
        'The call ended without a driver arriving. The usual causes are: the member canceled after waiting, the call was stuck with no owner, or the driver could not complete it.'],
        ['Look at the cancel reason and how long the call was stuck before the end.']),
    'TEXT_FAILED': ('text_off', 'A text to the member did not go out', [],
        ['Check the member\'s text consent, the mobile number on the work order, and the send log row for the error.']),
    'TEXT_NONE': ('text_off', 'The member got no texts', [
        'The member may not have agreed to receive texts, or there is no mobile number on the work order.',
        'The text flows run only from 2026-09-01 in the send log; earlier calls show no texts here.'],
        ['Check the member\'s text consent and the mobile number on the work order.']),
    'TEXT_LATE_ETA': ('text_late', 'The arrival-time text came late', [
        'The "garage and arrival time" text goes out when a garage accepts the call. This call waited for acceptance.'],
        ['Look at how long the call waited before a garage accepted.']),
    'TEXT_STILL_WORKING': ('text_off', 'No "still working on it" text', [
        'That text depends on the call staying in one state. Every decline, rejection or re-spot restarts its timer.',
        'There is a known gap in the "not accepted" text flows, with their status check set to OR instead of AND.'],
        ['Ask the flow owner to fix the not-accepted flows.']),
}

# why a text did not go out, by the reason the send log holds (matched case-insensitively, hyphens and spaces ignored)
TEXT_REASONS = [
    ('noconsent', 'The member has not agreed to receive texts, or opted out.'),
    ('nomeu', 'The member has no messaging record (they never opted in through the messaging channel).'),
    ('nophone', 'There is no mobile number on the work order.'),
    ('nolink', 'The tracking link could not be built, so the text was not sent.'),
    ('noar', 'No driver or garage was assigned yet when the text tried to go out.'),
    ('nochannel', 'No messaging channel is set up for this garage or work type.'),
    ('noteligible', 'This kind of call is not eligible for that message.'),
    ('failed', 'The messaging platform reported an error sending it (see the error text).'),
]


def text_reason(reason: str | None, outcome: str | None) -> str:
    key = ''.join(ch for ch in ((reason or '') + ' ' + (outcome or '')).lower() if ch.isalnum())
    return next((t for k, t in TEXT_REASONS if k in key), 'The text was skipped. The send log does not say why.')


def explain(code: str, **ctx) -> dict:
    """{code, icon, title, why[], check[]}: this call's own facts first, then the usual causes."""
    icon, title, why, check = CATALOG[code]
    own = []
    if code == 'STUCK_GRID':
        ladder = ctx.get('ladder') or []
        closed = [r for r in ladder if r.get('state') == 'skipped_closed']
        for r in closed[:3]:
            own.append(f"This call: {r['garage']} (rank {int(r['rank'])}) was closed (hours {r.get('hours') or 'unknown'}), so it was skipped.")
        wt = ctx.get('work_type')
        no_type = [r for r in ladder if wt and r.get('worktype') and wt not in r['worktype'] and r.get('state') != 'final']
        for r in no_type[:2]:
            own.append(f"This call: {r['garage']} (rank {int(r['rank'])}) does not list {wt} work.")
        if ctx.get('grid') and not own:
            own.append(f"This call: it sat in zone {ctx['grid']} for {ctx.get('minutes', '?')} min with no garage.")
    elif code in ('WAIT_BUSY', 'WAIT_FREE') and ctx.get('minutes') is not None:
        own.append(f"This call: it waited {round(ctx['minutes'])} min for {ctx.get('driver') or 'the driver'} to accept.")
    elif code == 'REJECT' and ctx.get('reason'):
        own.append(f"This call: the reason recorded was \"{ctx['reason']}\".")
    elif code == 'DECLINES' and ctx.get('seconds'):
        own.append('This call: ' + ', '.join(f"{s} s" for s in ctx['seconds']) + ' from offer to decline.')
    elif code == 'TEXT_FAILED':
        own = [text_reason(r, o) for r, o in ctx.get('reasons', [])][:3]
    return {'code': code, 'icon': icon, 'title': title, 'why': own + list(why), 'check': list(check)}
