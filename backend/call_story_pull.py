"""Call Story: input resolution and the sequential Salesforce plan (call-story-architecture 3).

Read-only SELECTs, one at a time (never sf_parallel), hard cap CS1.max_sf_calls. Required steps: resolve, WO, SAs,
history, assigned resources, texts, survey. Optional steps (matrix, optimizer trail) never break a story: a failure
or the call cap becomes a data note. Phone numbers are read only for the pre-9/1 text lookup and never stored.

Fields marked UNVERIFIED have not been checked with sf_describe yet (Salesforce was off-limits while Henry sampled):
ERS_Territory_Priority_Matrix__c fields, WorkOrder.Mobile_Phone__c, MessagingEndUser.MessagingPlatformKey format.
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone

from report_card_build import CallCapReached, CompositeError, Puller
from sf_client import sanitize_soql
from utils import parse_dt

log = logging.getLogger('call_story_pull')


class NotFound(Exception):
    pass


class Ambiguous(Exception):
    def __init__(self, candidates):
        super().__init__('ambiguous')
        self.candidates = candidates


class NotSupported(Exception):
    """422: not an ERS call, or older than Salesforce history keeps."""


WO_FIELDS = """Id, WorkOrderNumber, CreatedDate, ERS_Submitted_Date_Time__c, Source__c, ERS_Channel_Type__c, Priority_Code__c,
 Tow_Call__c, SMS_Opt_In__c, Trouble_Code__c, Resolution_Code__c, Clear_Code__c, Status_Reason__c, ERS_Call_Key__c,
 ERS_Source_Call_ID__c, Status"""
SA_FIELDS = """Id, AppointmentNumber, Status, CreatedDate, ActualStartTime, ActualEndTime, WorkType.Name, RecordType.Name,
 ServiceTerritoryId, ServiceTerritory.Name, ServiceTerritory.Latitude, ServiceTerritory.Longitude, ERS_Parent_Territory__c, ERS_Parent_Territory__r.Name, ParentRecordId,
 ERS_PTA__c, ERS_PTA_Due__c, ERS_Spotting_Datetime__c, ERS_Spotting_Number__c, ERS_Dispatch_Method__c,
 ERS_Dynamic_Priority__c, FSL__Duration_In_Minutes__c, FSL__Scheduling_Policy_Used__c, ERS_Facility_Decline_Reason__c,
 ERS_Rejection_Reason__c, ERS_Rejected_Datetime__c, ERS_Cancellation_Reason__c, Off_Platform_Driver__c,
 Off_Platform_Driver__r.Name, Off_Platform_Truck_Id__c, ERS_Tow_Pick_Up_Drop_off__c, Latitude, Longitude, City, PostalCode,
 Auto_Schedule_Requested__c"""
SMS_FIELDS = """Name, CreatedDate, Sent_At__c, Message_Definition__c, Source_Flow__c, Outcome__c, Error_Message__c,
 Checkpoint_Minutes__c, Service_Appointment__c, Messaging_End_User__c"""
SURVEY_FIELDS = "Name, ERS_Overall_Satisfaction__c, ERS_Survey_Completed_Date__c"
HIST_FIELDS = """Id, ServiceAppointmentId, Field, OldValue, NewValue, CreatedDate, CreatedById, CreatedBy.Name,
 CreatedBy.Profile.Name"""
AR_FIELDS = """ServiceAppointmentId, ServiceResourceId, ServiceResource.Name, ServiceResource.ERS_Driver_Type__c,
 ServiceResource.RelatedRecordId, CreatedDate, CreatedBy.Name"""


def classify(q: str, cfg: dict) -> tuple:
    """(input_type, normalised value) or raises ValueError. Runs before any SOQL."""
    q = (q or '').strip()
    inp = cfg['inputs']
    if re.match(inp['sa'], q, re.I):
        return 'sa', 'SA-' + re.sub(r'^SA-', '', q, flags=re.I)
    if re.match(inp['call_key'], q):
        return 'call_key', q
    if re.match(inp['wo'], q, re.I):
        return 'wo', re.sub(r'^WO-', '', q, flags=re.I)
    if re.match(inp['source_call_id'], q):
        return 'source_call_id', q
    if re.match(inp['id'], q):
        return 'id', q
    raise ValueError('Not a call number: use an SA#, WO#, call key or source call ID')


def resolve(p: Puller, kind: str, value: str) -> dict:
    """Spec 2. Returns the WO row; 8-digit numbers matching both a WO# and a source call ID are ambiguous."""
    v = sanitize_soql(value)
    if kind == 'sa':
        rows = p.all(f"SELECT ERS_Work_Order__c FROM ServiceAppointment WHERE AppointmentNumber = '{v}' LIMIT 1")
        return _wo_by(p, f"Id = '{sanitize_soql(rows[0]['ERS_Work_Order__c'])}'") if rows and rows[0].get('ERS_Work_Order__c') else _nf()
    if kind == 'id':
        if v.startswith('0WO'):
            return _wo_by(p, f"Id = '{v}'")
        obj, fld = ('ServiceAppointment', 'ERS_Work_Order__c') if v.startswith('08p') else ('WorkOrderLineItem', 'WorkOrderId')
        rows = p.all(f"SELECT {fld} FROM {obj} WHERE Id = '{v}' LIMIT 1")
        return _wo_by(p, f"Id = '{sanitize_soql(rows[0][fld])}'") if rows and rows[0].get(fld) else _nf()
    if kind == 'call_key':
        return _wo_by(p, f"ERS_Call_Key__c = '{v}'")
    if kind == 'wo':
        rows = p.all(f"SELECT {WO_FIELDS} FROM WorkOrder WHERE WorkOrderNumber = '{v}' OR ERS_Source_Call_ID__c = '{v}' LIMIT 3")
        if len(rows) > 1:
            raise _ambiguous(rows, v)
        return rows[0] if rows else _nf()
    return _wo_by(p, f"ERS_Source_Call_ID__c = '{v}'")


def _ambiguous(rows: list, v: str) -> Ambiguous:
    return Ambiguous([{'type': 'wo' if r['WorkOrderNumber'] == v else 'source_call_id',
                       'wo_number': r['WorkOrderNumber'], 'created': r['CreatedDate']} for r in rows])


def _nf():
    raise NotFound()


def _wo_by(p, where):
    rows = p.all(f"SELECT {WO_FIELDS} FROM WorkOrder WHERE {where} LIMIT 2")
    return rows[0] if rows else _nf()


def pull_story(q: str, cfg: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    t0 = time.time()
    kind, value = classify(q, cfg)
    p = Puller(max_calls=cfg['max_sf_calls'])
    try:
        raw = _pull_fast(p, q, kind, value, cfg, now)
    except CompositeError as e:                  # slow path: the same rows, one query at a time
        log.warning('call story composite failed (%s), reading sequentially', e)
        raw = _pull_sequential(p, q, kind, value, cfg, now)
    wo, sas = raw['wo'], raw['sas']
    _optional(raw, 'matrix', lambda: _matrix(p, sas), 'Priority matrix not read')
    _optional(raw, 'optimizer', lambda: _optimizer(p, raw), 'Optimizer trail not read')
    raw['sf_calls'] = p.calls
    raw['fetched_at'] = now.isoformat(timespec='seconds')
    raw['closed'] = _closed(sas, now, cfg)
    log.info('call story pull %s: %d calls, %d ms', wo['WorkOrderNumber'], p.calls, int((time.time() - t0) * 1000))
    return raw


def _checked(wo: dict, sas: list, now: datetime, cfg: dict):
    if parse_dt(wo['CreatedDate']) < now - timedelta(days=cfg['max_history_days']):
        raise NotSupported(f"Older than {cfg['max_history_days']} days: Salesforce history is gone")
    if not sas:
        raise NotFound()
    if not any((s.get('RecordType') or {}).get('Name') == 'ERS Service Appointment' for s in sas):
        raise NotSupported('Not an ERS call')


def _new_raw(q: str, kind: str, wo: dict, sas: list) -> dict:
    return {'resolution': {'input': q, 'input_type': kind, 'wo': {'id': wo['Id'], 'number': wo['WorkOrderNumber'],
                                                                 'call_key': wo.get('ERS_Call_Key__c'),
                                                                 'source_call_id': wo.get('ERS_Source_Call_ID__c')}},
            'wo': wo, 'sas': sas, 'data_notes': []}


def _hist_q(ids: str) -> str:
    return f"SELECT {HIST_FIELDS} FROM ServiceAppointmentHistory WHERE ServiceAppointmentId IN ({ids}) ORDER BY CreatedDate, Id"


def _verify_history(p: Puller, raw: dict, ids: str):
    """sf_query_all can stop silently on a page error: with 1000+ rows, compare against a COUNT."""
    if len(raw['history']) < 1000:
        return
    n = p.count(f"SELECT COUNT() FROM ServiceAppointmentHistory WHERE ServiceAppointmentId IN ({ids})")
    if n != len(raw['history']):
        raw['history'] = p.all(_hist_q(ids))
        if n != len(raw['history']):
            raw['partial'] = True
            raw['data_notes'].append({'code': 'HISTORY_COUNT_CHECKED', 'text': f'History incomplete: {len(raw["history"])} of {n} rows.'})


def _resolve_where(kind: str, v: str) -> str:
    """The WorkOrder filter for each input type (the single-query twin of resolve())."""
    if kind == 'sa':
        return f"Id IN (SELECT ERS_Work_Order__c FROM ServiceAppointment WHERE AppointmentNumber = '{v}')"
    if kind == 'id':
        if v.startswith('0WO'):
            return f"Id = '{v}'"
        if v.startswith('08p'):
            return f"Id IN (SELECT ERS_Work_Order__c FROM ServiceAppointment WHERE Id = '{v}')"
        return f"Id IN (SELECT WorkOrderId FROM WorkOrderLineItem WHERE Id = '{v}')"
    if kind == 'call_key':
        return f"ERS_Call_Key__c = '{v}'"
    if kind == 'wo':
        return f"(WorkOrderNumber = '{v}' OR ERS_Source_Call_ID__c = '{v}')"
    return f"ERS_Source_Call_ID__c = '{v}'"


def _pull_fast(p: Puller, q: str, kind: str, value: str, cfg: dict, now: datetime) -> dict:
    """One composite request: the WO with its SAs, texts and survey as child rows, then the history and assigned
    resources through a reference to the WO. Builds the same raw dict as _pull_sequential. Phones are never read here."""
    v = sanitize_soql(value)
    semi = "ServiceAppointmentId IN (SELECT Id FROM ServiceAppointment WHERE ERS_Work_Order__c = '@{wo.records[0].Id}')"
    got = p.composite({
        'wo': f"""SELECT {WO_FIELDS},
            (SELECT {SA_FIELDS} FROM Service_Appointments_del__r ORDER BY CreatedDate),
            (SELECT {SMS_FIELDS} FROM SMS_Send_Logs__r ORDER BY CreatedDate),
            (SELECT {SURVEY_FIELDS} FROM Work_Order_Survey_Results__r)
            FROM WorkOrder WHERE {_resolve_where(kind, v)} LIMIT 3""",
        'hist': f"SELECT {HIST_FIELDS} FROM ServiceAppointmentHistory WHERE {semi} ORDER BY CreatedDate, Id",
        'ar': f"SELECT {AR_FIELDS} FROM AssignedResource WHERE {semi}"})
    rows = got['wo']
    if not rows:
        raise NotFound()
    if kind == 'wo' and len(rows) > 1:
        raise _ambiguous(rows, v)
    wo = dict(rows[0])
    kids = {k: (wo.pop(k, None) or {}).get('records', [])
            for k in ('Service_Appointments_del__r', 'SMS_Send_Logs__r', 'Work_Order_Survey_Results__r')}
    sas = kids['Service_Appointments_del__r']
    _checked(wo, sas, now, cfg)
    raw = _new_raw(q, kind, wo, sas)
    raw['history'], raw['assigned'], raw['survey'] = got['hist'], got['ar'], kids['Work_Order_Survey_Results__r']
    _verify_history(p, raw, ",".join(f"'{sanitize_soql(s['Id'])}'" for s in sas))
    if parse_dt(wo['CreatedDate']) >= parse_dt(cfg['sms']['log_start_utc']):
        raw['sms_source'], raw['sms'] = 'send_log', kids['SMS_Send_Logs__r']
    else:
        _texts(p, raw, wo, cfg)                  # before 1 Sep 2026 the texts are in MessagingSession
    return raw


def _pull_sequential(p: Puller, q: str, kind: str, value: str, cfg: dict, now: datetime) -> dict:
    """The slow path, 9-10 calls: one query per step. Used when the composite request is refused."""
    wo = resolve(p, kind, value)
    wo_id = sanitize_soql(wo['Id'])
    if parse_dt(wo['CreatedDate']) < now - timedelta(days=cfg['max_history_days']):
        raise NotSupported(f"Older than {cfg['max_history_days']} days: Salesforce history is gone")
    sas = p.all(f"SELECT {SA_FIELDS} FROM ServiceAppointment WHERE ERS_Work_Order__c = '{wo_id}' ORDER BY CreatedDate")
    _checked(wo, sas, now, cfg)
    ids = ",".join(f"'{sanitize_soql(s['Id'])}'" for s in sas)
    raw = _new_raw(q, kind, wo, sas)
    raw['history'] = p.all(_hist_q(ids))
    _verify_history(p, raw, ids)
    raw['assigned'] = p.all(f"SELECT {AR_FIELDS} FROM AssignedResource WHERE ServiceAppointmentId IN ({ids})")
    _texts(p, raw, wo, cfg)
    raw['survey'] = p.all(f"SELECT {SURVEY_FIELDS} FROM Survey_Result__c WHERE ERS_Work_Order__c = '{wo_id}'")
    return raw


def _optional(raw, key, fn, label):
    try:
        raw[key] = fn()
    except CallCapReached:
        raw[key] = None
        raw['data_notes'].append({'code': 'CALL_CAP', 'text': f'{label}: Salesforce call cap reached.'})
    except Exception as e:                       # optional detail must never break the story
        log.warning('call story optional step %s failed: %s', key, e)
        raw[key] = None
        raw['data_notes'].append({'code': 'OPTIONAL_STEP_FAILED', 'text': f'{label}.'})


def _texts(p: Puller, raw: dict, wo: dict, cfg: dict):
    wo_id = sanitize_soql(wo['Id'])
    if parse_dt(wo['CreatedDate']) >= parse_dt(cfg['sms']['log_start_utc']):
        raw['sms_source'] = 'send_log'
        raw['sms'] = p.all(f"SELECT {SMS_FIELDS} FROM SMS_Send_Log__c WHERE Work_Order__c = '{wo_id}' ORDER BY CreatedDate")
        return
    raw['sms_source'] = 'messaging_session'

    def sessions():
        phone = p.all(f"SELECT Mobile_Phone__c FROM WorkOrder WHERE Id = '{wo_id}'")   # UNVERIFIED field
        digits = re.sub(r'\D', '', (phone[0].get('Mobile_Phone__c') or '') if phone else '')[-10:]
        if len(digits) != 10:
            return []
        start = parse_dt(wo['CreatedDate']).strftime('%Y-%m-%dT%H:%M:%SZ')
        end = (parse_dt(wo['CreatedDate']) + timedelta(hours=26)).strftime('%Y-%m-%dT%H:%M:%SZ')
        return p.all(f"""SELECT CreatedDate FROM MessagingSession WHERE Origin = 'TriggeredOutbound'
            AND MessagingEndUserId IN (SELECT Id FROM MessagingEndUser WHERE MessagingPlatformKey = '+1{digits}')
            AND CreatedDate >= {start} AND CreatedDate < {end} ORDER BY CreatedDate""")
    _optional(raw, 'sms', sessions, 'Texts before 1 Sep 2026 not read')
    raw['sms'] = raw['sms'] or []


def _matrix(p: Puller, sas: list) -> dict | None:
    """Q6: the grid's priority matrix (current values). UNVERIFIED field names (spec section 3 Q6)."""
    grid = next((s.get('ERS_Parent_Territory__c') for s in sas if s.get('ERS_Parent_Territory__c')), None)
    if not grid:
        return None
    import cache
    key = f'cs_matrix:{grid}'
    hit = cache.get(key)
    if hit is not None:
        return hit
    rows = p.all(f"""SELECT ERS_Spotted_Territory__r.Name, ERS_Priority__c, ERS_Worktype__c, ERS_Operating_Hours__c,
        ERS_Operating_Hours__r.Name FROM ERS_Territory_Priority_Matrix__c
        WHERE ERS_Parent_Service_Territory__c = '{sanitize_soql(grid)}'""")
    hours_ids = sorted({r['ERS_Operating_Hours__c'] for r in rows if r.get('ERS_Operating_Hours__c')})
    slots = {}
    if hours_ids:
        for s in p.all("SELECT OperatingHoursId, DayOfWeek, StartTime, EndTime FROM TimeSlot WHERE OperatingHoursId IN ("
                       + ",".join(f"'{sanitize_soql(h)}'" for h in hours_ids) + ")"):
            slots.setdefault(s['OperatingHoursId'], []).append(
                {'day': s['DayOfWeek'], 'start': (s.get('StartTime') or '')[:5], 'end': (s.get('EndTime') or '')[:5]})
    out = {'rows': [{'rank': r.get('ERS_Priority__c'), 'garage': (r.get('ERS_Spotted_Territory__r') or {}).get('Name'),
                     'worktype': r.get('ERS_Worktype__c'), 'hours': (r.get('ERS_Operating_Hours__r') or {}).get('Name'),
                     'slots': slots.get(r.get('ERS_Operating_Hours__c'))} for r in rows]}
    cache.put(key, out, ttl=86400)
    return out


def _optimizer(p: Puller, raw: dict) -> dict | None:
    """Q7, only when the FSL optimizer touched the call: requests in [first engine pick - 2 min, last + 1 min]."""
    picks = [parse_dt(h['CreatedDate']) for h in raw['history'] if h['Field'] == 'ERS_Assigned_Resource__c'
             and (h.get('CreatedBy') or {}).get('Name') in ('Platform Integration User', 'FSL System User')]
    if not picks:
        return None
    lo = (min(picks) - timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
    hi = (max(picks) + timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    rows = p.all(f"""SELECT Id, CreatedDate, FSL__Type__c, FSL__Status__c, FSL__Scheduling_Policy__c
        FROM FSL__Optimization_Request__c WHERE CreatedDate >= {lo} AND CreatedDate <= {hi}""")
    return {'requests': [{'ts': r['CreatedDate'], 'type': r.get('FSL__Type__c'), 'status': r.get('FSL__Status__c'),
                          'policy_id': r.get('FSL__Scheduling_Policy__c')} for r in rows]}


def _closed(sas: list, now: datetime, cfg: dict) -> bool:
    """All legs terminal and over closed_grace_hours past their end: cache 24 h (architecture 3.4)."""
    terminal = ('Completed', 'Unable to Complete', 'Canceled', 'No-Show')
    for s in sas:
        if not (s.get('Status') in terminal or (s.get('Status') or '').startswith('Cancel')):
            return False
        end = parse_dt(s.get('ActualEndTime')) or parse_dt(s.get('CreatedDate'))
        if end and now - end < timedelta(hours=cfg['closed_grace_hours']):
            return False
    return True
