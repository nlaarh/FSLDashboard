"""Cancellations tab: GET /api/cancellations/today: every ERS call cancelled today (Eastern day), newest first.

A cancellation is a ServiceAppointment whose Status is one of CANCEL_STATUSES. Salesforce itself says whether the truck was
already on the way ('Cancel Call - Service En Route'), so nothing here is inferred.
The cancel time is the time the Status history changed to a cancel status (not LastModifiedDate, which later edits move).

Salesforce cost per refresh, whatever the number of viewers: one appointment read + one count (each shared 30 s);
status history comes from the shared sa_history copy. The finished answer is kept 30 s, so every viewer shares one build.
A contractor only sees the garages assigned to them.
"""

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

import cache
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
_CACHE_S = 30       # below the 60 s screen refresh, so every refresh gets a fresh build
_SHARED_S = 30


def _et_day_start_utc(now_utc: datetime) -> datetime:
    et = to_eastern(now_utc)
    return et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _build() -> dict:
    now = datetime.now(timezone.utc)
    start = _et_day_start_utc(now)
    status_list = ', '.join(f"'{s}'" for s in CANCEL_STATUSES)

    # Rows modified today in a cancel status; the history below decides which were really cancelled today.
    rows = sf_query_all_shared(f"""
        SELECT Id, AppointmentNumber, CreatedDate, Status, ERS_Cancellation_Reason__c, ERS_PTA__c,
               ERS_Dispatch_Method__c, WorkType.Name, ServiceTerritory.Name
        FROM ServiceAppointment
        WHERE LastModifiedDate >= {_iso(start)} AND Status IN ({status_list})
          AND ServiceTerritoryId != null AND RecordType.Name = 'ERS Service Appointment'
    """, ttl=_SHARED_S)
    total_rows = sf_query_all_shared(f"""
        SELECT COUNT(Id) cnt FROM ServiceAppointment
        WHERE CreatedDate >= {_iso(start)} AND ServiceTerritoryId != null AND RecordType.Name = 'ERS Service Appointment'
    """, ttl=_SHARED_S)
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

    items = []
    for r in rows:
        when = cancel_at.get(r['Id'])
        if not when or when < start:
            continue
        made = parse_dt(r.get('CreatedDate'))
        et_when, et_made = to_eastern(when), to_eastern(made)
        wait = round((when - made).total_seconds() / 60) if made else None
        method = r.get('ERS_Dispatch_Method__c') or ''
        items.append({
            'id': r['Id'],
            'number': r.get('AppointmentNumber'),
            'garage': (r.get('ServiceTerritory') or {}).get('Name'),
            'status': r['Status'],
            'type': _TYPE[r['Status']],
            'en_route': r['Status'] == 'Cancel Call - Service En Route',
            'reason': r.get('ERS_Cancellation_Reason__c') or 'No reason recorded',
            'work_type': (r.get('WorkType') or {}).get('Name'),
            'dispatch_method': method,
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
        'date': to_eastern(now).strftime('%Y-%m-%d'),
        'generated': now.isoformat(),
        'calls_today': calls_today,
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


@router.get('/api/cancellations/today')
def api_cancellations_today(request: Request):
    """Today's cancelled ERS calls with a summary. Contractors only see their own garages."""
    username = get_request_username(request)
    user = _users.get_user(username) if username else None
    territories = (user.get('territories') or []) if user and user.get('role') == 'contractor' else []

    data = cache.get('cancellations_today')
    if data is None:
        data = _build()
        cache.put('cancellations_today', data, _CACHE_S)

    items = [i for i in data['items'] if i['garage'] in territories] if territories else data['items']
    # A contractor's rate would mix their cancels with all calls, so no rate for them.
    return {
        'date': data['date'], 'generated': data['generated'],
        'summary': _summary(items, 0 if territories else data['calls_today']),
        'items': items,
    }
