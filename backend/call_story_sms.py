"""Call Story: member texts (call-story-spec 7, architecture 4.5). Pure, no I/O.

We can prove a text was handed to the SMS channel, never that a phone received it ("Sent != delivered").
"""

from utils import parse_dt

# Message_Definition__c prefix -> label shown in the story (spec 7.3)
LABELS = [
    ('Message_1_Sent_upon_initial_call_placement', 'Call received'),
    ('Facility_Assigned_WO_Id_PTA_SMS', 'Garage and PTA'),
    ('Message_3_When_Call_is_not_accepted_by_a_driver', 'Still working on it'),
    ('Message_4_Sent_when_call_is_accepted_by_a_driver', 'Driver accepted, update'),
    ('Message_1_Sent_upon_when_driver_is_enroute', 'Driver en route'),
    ('Message_2a', 'Driver en route'),
    ('Message_6', 'Driver en route'),
    ('Message_9_', 'Tow drop-off leg'),
    ('Message 9a', 'Tow drop-off leg'),
    ('Message_9', 'Driver en route'),
    ('Message_5_Sent_when_system_or_driver_marks_On_Location', 'Driver on location'),
    ('Message_7', 'Call completed'),
    ('Message_8', 'Call completed'),
    ('Survey_IC_SMS', 'Survey'),
    ('Opt_in_Confirmation', 'Opt-in confirmation'),
]
DELIVERY = {'available': False, 'label': 'Sent ≠ delivered: delivery to the phone is not visible to FleetPulse'}
STILL_WORKING = 'Message_3_When_Call_is_not_accepted_by_a_driver'


def label(definition: str | None) -> str:
    d = definition or ''
    if d.startswith('Message_9_') and 'Tire' in d:
        return 'Driver en route'
    return next((lbl for prefix, lbl in LABELS if d.startswith(prefix)), d or 'Text')


def sms_block(raw: dict, wo: dict, legs: list, status_events: list, cfg: dict) -> dict:
    """status_events: [(ts, status)] of the member-facing leg, for the timer rule."""
    c = cfg['sms']
    source = raw.get('sms_source') or 'send_log'
    rows = []
    if source == 'send_log':
        for r in raw.get('sms') or []:
            if (r.get('Message_Definition__c') or '') in c['exclude_definitions']:
                continue                                    # to dispatcher contacts, not to the member
            outcome = (r.get('Outcome__c') or '').lower()
            rows.append({'ts': r.get('Sent_At__c') or r.get('CreatedDate'), 'label': label(r.get('Message_Definition__c')),
                         'definition': r.get('Message_Definition__c'),
                         'checkpoint_min': r.get('Checkpoint_Minutes__c'),
                         'outcome': 'sent' if outcome == 'sent' else 'failed' if outcome.startswith('failed') else 'skipped',
                         'reason': None if outcome == 'sent' else (r.get('Error_Message__c') or r.get('Outcome__c')),
                         'inferred': False, 'delivery_status': None, 'leg_sa_id': r.get('Service_Appointment__c')})
    else:
        for r in raw.get('sms') or []:                      # before 9/1: sessions only, type unknown (spec 7.5)
            rows.append({'ts': r.get('CreatedDate'), 'label': 'Text sent (type unknown)', 'definition': None,
                         'outcome': 'sent', 'reason': None, 'inferred': False, 'delivery_status': None})
    rows.sort(key=lambda r: r['ts'] or '')
    return {'source': source, 'log_starts': c['log_start_utc'][:10], 'delivery': dict(DELIVERY), 'rows': rows,
            'why_not': why_not(wo, rows, status_events, cfg), 'opted_in': wo.get('SMS_Opt_In__c')}


def why_not(wo: dict, rows: list, status_events: list, cfg: dict) -> list:
    """Spec 7.4, checked in order."""
    out = []
    if wo.get('SMS_Opt_In__c') is False:
        return [{'code': 'NOT_OPTED_IN', 'text': 'Member not opted in to texts. No texts and no survey.'}]
    for r in rows:
        if r['outcome'] != 'sent':
            out.append({'code': 'NOT_SENT', 'text': f"{r['label']}: not sent ({r['reason']})", 'ts': r['ts']})
    restarts, longest = timer_runs(status_events, cfg)
    sent_still = any(r['definition'] == STILL_WORKING and r['outcome'] == 'sent' for r in rows)
    first = cfg['sms']['not_accepted_checkpoints_min'][0]
    unaccepted = _unaccepted_minutes(status_events)
    if unaccepted is not None and unaccepted >= first and not sent_still:
        out.append({'code': 'TIMER_RESTARTED' if restarts else 'NO_STILL_WORKING_TEXT', 'restarts': restarts,
                    'longest_run_min': longest, 'unaccepted_min': unaccepted,
                    'text': (f"No 'still working' text: the timer restarted {restarts} times because the call kept being "
                             'declined, rejected or re-spotted.') if restarts else
                            "No 'still working' text was logged although the call waited unaccepted."})
    if not rows and wo.get('SMS_Opt_In__c') is not False:
        out.append({'code': 'NO_TEXT_LOGGED', 'text': 'No text logged for this call.'})
    return out


def timer_runs(status_events: list, cfg: dict) -> tuple:
    """The 30/50/80-min flows start when the SA enters Assigned/Dispatched and are dropped when it leaves them
    (spec 7.4). Returns (restarts = times the status left Assigned/Dispatched before acceptance, longest run min)."""
    entry = set(cfg['sms']['not_accepted_entry_statuses'])
    leaves, start, longest = 0, None, 0.0
    for ts, st in status_events:
        t = parse_dt(ts)
        if st in ('Accepted', 'En Route', 'On Location'):
            if start:
                longest = max(longest, (t - start).total_seconds() / 60)
            break
        if st in entry and start is None:
            start = t
        elif st not in entry and start is not None:
            longest = max(longest, (t - start).total_seconds() / 60)
            leaves, start = leaves + 1, None
    return leaves, round(longest, 1)


def _unaccepted_minutes(status_events: list):
    if not status_events:
        return None
    first = parse_dt(status_events[0][0])
    acc = next((parse_dt(ts) for ts, st in status_events if st in ('Accepted', 'En Route', 'On Location')), None)
    end = acc or parse_dt(status_events[-1][0])
    return round((end - first).total_seconds() / 60, 1)
