"""Replay extras, Salesforce reads (replay-v2 design 3.4): at most 2 composite requests, SELECT only.

Round 1 (one request): the work order's phones, the driver's other jobs, and their status/holder trail.
Round 2 (one request, skipped when there is nothing to match): VoiceCall and MessagingSession.

Phones live in memory inside this function only: they are never returned, cached or logged. The conversation ids the
text thread needs are returned separately and kept server side (memory cache), never sent to the browser."""

import logging
from datetime import datetime, timedelta, timezone

import replay_extras as rx
from report_card_build import CompositeError, Puller, _in, _iso
from sf_client import sanitize_soql
from utils import parse_dt

log = logging.getLogger('replay_extras')
MAX_CALLS = 4
JOBS_BEFORE = timedelta(hours=12)
JOBS_AFTER = timedelta(hours=1)
VOICE_FIELDS = ('Id, CallStartDateTime, CallEndDateTime, CallDurationInSeconds, CallAcceptDateTime, ToPhoneNumber, CallType, '
                'PreviousCallId, User.Name')
SESSION_FIELDS = ('Id, CreatedDate, StartTime, EndTime, Status, Origin, EndUserMessageCount, Owner.Name, '
                  'Conversation.ConversationIdentifier, MessagingChannel.MasterLabel, MessagingChannel.DeveloperName')


def _phone_forms(digits: list) -> list:
    """Salesforce stores VoiceCall.FromPhoneNumber as '+1 585 831 9725' (older rows '+15858319725')."""
    return [f for d in digits for f in (f'+1 {d[:3]} {d[3:6]} {d[6:]}', f'+1{d}')]


def _lit(values) -> str:
    return ','.join(f"'{sanitize_soql(v)}'" for v in values)


def _jobs_where(ctx: dict) -> str:
    """The driver's ERS service appointments around this call. Towbook: only Off_Platform_Driver__c (the garage
    placeholder in ERS_Assigned_Resource__c is the same on every call of that garage). FSL: the final holder."""
    flt = (f"Off_Platform_Driver__c = '{sanitize_soql(ctx['driver'])}'" if ctx['channel'] == 'towbook'
           else f"ERS_Assigned_Resource__c = '{sanitize_soql(ctx['driver'])}'")
    return (f"{flt} AND CreatedDate >= {_iso(ctx['given'] - JOBS_BEFORE)} AND CreatedDate <= {_iso(ctx['end'] + JOBS_AFTER)} "
            f"AND RecordType.Name = 'ERS Service Appointment'")


def _round1(ctx: dict, wo_id: str) -> dict:
    q = {'phones': f"SELECT Mobile_Phone__c, Callback_Phone__c FROM WorkOrder WHERE Id = '{sanitize_soql(wo_id)}'"}
    if ctx['driver'] and ctx['given']:
        where = _jobs_where(ctx)
        q['jobs'] = ('SELECT Id, AppointmentNumber, ERS_Work_Order__c, ERS_Work_Order__r.WorkOrderNumber, WorkType.Name, Status, '
                     f'CreatedDate, Latitude, Longitude FROM ServiceAppointment WHERE {where} ORDER BY CreatedDate LIMIT 200')
        q['trail'] = ('SELECT ServiceAppointmentId, Field, NewValue, CreatedDate FROM ServiceAppointmentHistory '
                      f"WHERE Field IN ('Status','ERS_Assigned_Resource__c') AND ServiceAppointmentId IN "
                      f'(SELECT Id FROM ServiceAppointment WHERE {where}) ORDER BY CreatedDate, Id')
    return q


def _round2(ctx: dict, digits: list, end_users: list) -> dict:
    span = f'CreatedDate >= {_iso(ctx["w_start"])} AND CreatedDate <= {_iso(ctx["w_end"])}'
    q = {}
    if digits:
        q['calls'] = (f'SELECT {VOICE_FIELDS} FROM VoiceCall WHERE FromPhoneNumber IN ({_lit(_phone_forms(digits))}) AND {span} '
                      'ORDER BY CallStartDateTime LIMIT 50')
    who = (f'MessagingEndUserId IN ({_in(end_users)})' if end_users else
           f'MessagingEndUserId IN (SELECT Id FROM MessagingEndUser WHERE MessagingPlatformKey IN ({_lit("+1" + d for d in digits)}))' if digits else '')
    if who:
        q['sessions'] = f"SELECT {SESSION_FIELDS} FROM MessagingSession WHERE Origin = 'InboundInitiated' AND {span} AND {who} LIMIT 50"
    return q


def pull_extras(raw: dict, promise_iso: str | None, now: datetime | None = None, puller: Puller | None = None) -> tuple:
    """(public extras dict without sf_calls/cache, private {'conversations': [ids]}). Raises CompositeError / RuntimeError
    when round 1 fails; a failed round 2 only drops calls and texts, with a note."""
    now = now or datetime.now(timezone.utc)
    p = puller or Puller(max_calls=MAX_CALLS)
    ctx = rx.member_context(raw, now)
    wo_id = raw['wo']['Id']
    got = p.composite(_round1(ctx, wo_id))
    ph = (got['phones'] or [{}])[0]
    digits = rx.phone_digits(ph.get('Mobile_Phone__c'), ph.get('Callback_Phone__c'))
    end_users = sorted({s['Messaging_End_User__c'] for s in raw.get('sms') or [] if s.get('Messaging_End_User__c')})
    notes, voice, sessions = [] if digits else [rx.NO_PHONE_NOTE], [], []
    q2 = _round2(ctx, digits, end_users)
    if q2:
        try:
            second = p.composite(q2)
            voice, sessions = second.get('calls', []), second.get('sessions', [])
        except (CompositeError, RuntimeError) as e:
            log.warning('replay extras: calls/texts read failed for %s: %s', wo_id, e)
            notes.append('Member calls and texts could not be loaded.')
    jobs = got.get('jobs', [])
    if len(jobs) >= 200:
        notes.append('This driver had a very busy day; only the first 200 jobs were checked.')
    out = rx.build_extras(ctx, jobs, got.get('trail', []), voice, sessions, parse_dt(promise_iso), notes)
    out['sf_calls'] = p.calls
    convs = sorted({(s.get('Conversation') or {}).get('ConversationIdentifier') for s in sessions if rx.is_ers_sms(s)} - {None})
    return out, {'conversations': convs, 'window': (ctx['w_start'], ctx['w_end'])}
