"""Cancellations tab: GET /api/cancellations?date=YYYY-MM-DD (default today, Eastern day; up to 31 days back): every ERS call
cancelled that day, newest first.

A cancellation is a ServiceAppointment whose Status is one of CANCEL_STATUSES. Salesforce itself says whether the truck was
already on the way ('Cancel Call - Service En Route'), so nothing here is inferred.
The cancel time is the time the Status history changed to a cancel status (not LastModifiedDate, which later edits move).

Salesforce cost per refresh, whatever the number of viewers: one appointment read + one count (each shared 30 s for today,
10 min for a past day, which cannot change much; a past day's history older than the shared copy is read in a few batches);
status and driver history come from the shared sa_history copy, driver names and phones from ref_data (already cached). The finished answer is kept 30 s, so every viewer shares one build.
A contractor only sees the garages assigned to them.
"""

import logging
from collections import Counter
from datetime import date as _date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request

import re

import cache
import ref_data
import sa_history
import users as _users
from routers.auth import get_request_username
from sf_client import sf_query_all_shared
from utils import parse_dt, to_eastern

router = APIRouter()
log = logging.getLogger('cancellations')

CANCEL_STATUSES = ('Canceled', 'Cancel Call - Service Not En Route', 'Cancel Call - Service En Route')
_TYPE = {
    'Cancel Call - Service En Route': 'After truck en route',
    'Cancel Call - Service Not En Route': 'Before truck en route',
    'Canceled': 'Canceled',
}
_RESOURCE_ID = re.compile(r'^0Hn[A-Za-z0-9]{12,15}$')
_CACHE_S = 30       # below the 60 s screen refresh, so every refresh gets a fresh build
_SHARED_S = 30
_PAST_S = 600       # a past day barely changes: share its reads and its answer for 10 min
_MAX_DAYS_BACK = 31


def _et_today() -> _date:
    return to_eastern(datetime.now(timezone.utc)).date()


def _day_window(day: _date) -> tuple[datetime, datetime]:
    """[start, end) of an Eastern calendar day, in UTC (DST-aware: 23 or 25 hours on the change days)."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo('America/New_York')
    lo = datetime(day.year, day.month, day.day, tzinfo=et)
    nxt = day + timedelta(days=1)
    hi = datetime(nxt.year, nxt.month, nxt.day, tzinfo=et)
    return lo.astimezone(timezone.utc), hi.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _driver(held: tuple | None, people: dict) -> tuple:
    """(name, phone) for (resource id, name) held at the cancel. A Fleet / On-Platform driver has a phone; a Towbook driver is a
    plain name with no phone in Salesforce."""
    rid, name = held or (None, None)
    d = people.get(rid) if rid else None
    if d:
        return d.get('Name'), (d.get('RelatedRecord') or {}).get('Phone')
    return name, None


def _build(day: _date) -> dict:
    now = datetime.now(timezone.utc)
    start, end = _day_window(day)
    shared_s = _SHARED_S if day == _et_today() else _PAST_S
    status_list = ', '.join(f"'{s}'" for s in CANCEL_STATUSES)

    # Cancel-status calls created in the 3 days up to the day's end and touched since its start; the history below decides
    # which were really cancelled that day.
    rows = sf_query_all_shared(f"""
        SELECT Id, AppointmentNumber, CreatedDate, Status, ERS_Cancellation_Reason__c, ERS_PTA__c,
               ERS_Dispatch_Method__c, WorkType.Name, ServiceTerritory.Name, AAA_ERS_Account_Facility__r.Phone,
               TYPEOF ParentRecord WHEN WorkOrderLineItem THEN WorkOrderId, WorkOrder.WorkOrderNumber END
        FROM ServiceAppointment
        WHERE LastModifiedDate >= {_iso(start)} AND CreatedDate >= {_iso(start - timedelta(days=3))} AND CreatedDate < {_iso(end)}
          AND Status IN ({status_list})
          AND ServiceTerritoryId != null AND RecordType.Name = 'ERS Service Appointment'
    """, ttl=shared_s)
    total_rows = sf_query_all_shared(f"""
        SELECT COUNT(Id) cnt FROM ServiceAppointment
        WHERE CreatedDate >= {_iso(start)} AND CreatedDate < {_iso(end)} AND ServiceTerritoryId != null AND RecordType.Name = 'ERS Service Appointment'
    """, ttl=shared_s)
    calls_today = int((total_rows[0].get('cnt') if total_rows else 0) or 0)

    created = {r['Id']: r.get('CreatedDate') for r in rows}
    history = sa_history.rows_for('Status', list(created), created)
    cancel_at: dict[str, datetime] = {}
    cancel_by: dict[str, tuple] = {}
    for h in history:                                   # oldest first, so the latest cancel wins
        if h.get('NewValue') in CANCEL_STATUSES:
            ts = parse_dt(h.get('CreatedDate'))
            if ts:
                cancel_at[h['ServiceAppointmentId']] = ts
                who = h.get('CreatedBy') or {}
                cancel_by[h['ServiceAppointmentId']] = (who.get('Name'), (who.get('Profile') or {}).get('Name'))

    # Driver who held the call at the cancel. Cancelling clears the assigned resource in the same second, so a clearing
    # row at (or just before) the cancel keeps the holder; an earlier clearing means nobody held it. Each assignment is two
    # rows: a resource id (Fleet / On-Platform) and a plain name (Towbook has only the name / truck label).
    holder: dict[str, list] = {}                          # sa -> [resource id, name]
    for h in sa_history.rows_for('ERS_Assigned_Resource__c', list(created), created):
        sa, ts = h.get('ServiceAppointmentId'), parse_dt(h.get('CreatedDate'))
        if sa not in cancel_at or not ts or ts > cancel_at[sa] + timedelta(seconds=5):
            continue
        cur, v = holder.setdefault(sa, [None, None]), h.get('NewValue')
        if v:
            cur[0 if _RESOURCE_ID.match(v) else 1] = v
        elif ts < cancel_at[sa] - timedelta(seconds=5):
            cur[0] = cur[1] = None
    assigned = {sa: tuple(v) for sa, v in holder.items()}
    try:
        people = {d['Id']: d for d in ref_data.drivers(require_gps=False)}
    except Exception:
        log.warning('driver list unavailable, driver names left out', exc_info=True)
        people = {}

    items = []
    for r in rows:
        when = cancel_at.get(r['Id'])
        if not when or when < start or when >= end:
            continue
        made = parse_dt(r.get('CreatedDate'))
        et_when, et_made = to_eastern(when), to_eastern(made)
        wait = round((when - made).total_seconds() / 60) if made else None
        method = r.get('ERS_Dispatch_Method__c') or ''
        items.append({
            'id': r['Id'],
            'number': r.get('AppointmentNumber'),
            'work_order': ((r.get('ParentRecord') or {}).get('WorkOrder') or {}).get('WorkOrderNumber'),
            'garage': (r.get('ServiceTerritory') or {}).get('Name'),
            'status': r['Status'],
            'type': _TYPE[r['Status']],
            'en_route': r['Status'] == 'Cancel Call - Service En Route',
            'reason': r.get('ERS_Cancellation_Reason__c') or 'No reason recorded',
            'work_type': (r.get('WorkType') or {}).get('Name'),
            'dispatch_method': method,
            'driver': _driver(assigned.get(r['Id']), people)[0],
            'driver_phone': _driver(assigned.get(r['Id']), people)[1],
            'garage_phone': (r.get('AAA_ERS_Account_Facility__r') or {}).get('Phone'),
            'cancelled_by': cancel_by.get(r['Id'], (None, None))[0],
            'cancelled_by_profile': cancel_by.get(r['Id'], (None, None))[1],
            'pta_min': r.get('ERS_PTA__c'),
            'created_et': et_made.isoformat() if et_made else None,
            'cancelled_et': et_when.isoformat() if et_when else None,
            'minutes_before_cancel': wait,
            '_when': when,
        })
    items.sort(key=lambda i: i['_when'], reverse=True)
    for i in items:
        del i['_when']

    return {
        'date': day.isoformat(),
        'generated': now.isoformat(),
        'calls_today': calls_today,        # calls created that day (the name is from when the tab only knew today)
        'is_today': day == _et_today(),
        'items': items,
    }


def _summary(items: list[dict], calls_today: int) -> dict:
    n = len(items)
    waited = [i['minutes_before_cancel'] for i in items if i['minutes_before_cancel'] is not None]
    return {
        'total': n,
        'after_en_route': sum(1 for i in items if i['en_route']),
        'before_en_route': sum(1 for i in items if i['type'] == 'Before truck en route'),
        'unspecified': sum(1 for i in items if i['type'] == 'Canceled'),
        'calls_today': calls_today,
        'rate_pct': round(100 * n / calls_today, 1) if calls_today else None,
        'avg_minutes_before_cancel': round(sum(waited) / len(waited)) if waited else None,
        'by_reason': [{'reason': k, 'count': v} for k, v in Counter(i['reason'] for i in items).most_common()],
    }


@router.get('/api/cancellations')
@router.get('/api/cancellations/today')
def api_cancellations(request: Request, date: str | None = Query(None, description='YYYY-MM-DD, Eastern day; default today')):
    """One day's cancelled ERS calls with a summary. Contractors only see their own garages."""
    today = _et_today()
    try:
        day = _date.fromisoformat(date) if date else today
    except ValueError:
        raise HTTPException(400, 'date must be YYYY-MM-DD')
    if day > today:
        raise HTTPException(400, 'Cannot look at a future day')
    if (today - day).days > _MAX_DAYS_BACK:
        raise HTTPException(400, f'Only the last {_MAX_DAYS_BACK} days are available')

    username = get_request_username(request)
    user = _users.get_user(username) if username else None
    territories = (user.get('territories') or []) if user and user.get('role') == 'contractor' else []

    key = f'cancellations_{day.isoformat()}'
    data = cache.get(key)
    if data is None:
        data = _build(day)
        cache.put(key, data, _CACHE_S if day == today else _PAST_S)

    items = [i for i in data['items'] if i['garage'] in territories] if territories else data['items']
    # A contractor's rate would mix their cancels with all calls, so no rate for them.
    return {
        'date': data['date'], 'is_today': data['is_today'], 'generated': data['generated'],
        'summary': _summary(items, 0 if territories else data['calls_today']),
        'items': items,
    }
