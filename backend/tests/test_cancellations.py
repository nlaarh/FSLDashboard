"""Cancellations tab: today's cancelled calls come from status history, not LastModifiedDate."""
from datetime import datetime, timedelta, timezone

from routers import cancellations as c


def _fake(monkeypatch, rows, count, history):
    def shared(soql, ttl=0):
        return count if 'COUNT(Id)' in soql else rows
    monkeypatch.setattr(c, 'sf_query_all_shared', shared)
    monkeypatch.setattr(c.sa_history, 'rows_for', lambda field, ids, created: history)


def _sa(i, status, made):
    return {'Id': i, 'AppointmentNumber': f'SA-{i}', 'CreatedDate': made.isoformat(), 'Status': status,
            'ERS_Cancellation_Reason__c': None, 'ERS_PTA__c': 45, 'ERS_Dispatch_Method__c': 'Field Services',
            'WorkType': {'Name': 'Tow'}, 'ServiceTerritory': {'Name': '076DO'}}


def test_only_cancels_made_today_are_listed_and_typed(monkeypatch):
    now = datetime.now(timezone.utc)
    start = c._et_day_start_utc(now)
    made = start + timedelta(minutes=1)
    rows = [_sa('a', 'Cancel Call - Service En Route', made), _sa('b', 'Canceled', made), _sa('old', 'Canceled', made)]
    hist = [
        {'ServiceAppointmentId': 'a', 'NewValue': 'Cancel Call - Service En Route', 'CreatedDate': (start + timedelta(minutes=31)).isoformat()},
        {'ServiceAppointmentId': 'b', 'NewValue': 'Canceled', 'CreatedDate': (start + timedelta(minutes=11)).isoformat(), 'CreatedBy': {'Name': 'Pat Dispatcher', 'Profile': {'Name': 'Membership User'}}},
        {'ServiceAppointmentId': 'old', 'NewValue': 'Canceled', 'CreatedDate': (start - timedelta(hours=3)).isoformat()},
    ]
    _fake(monkeypatch, rows, [{'cnt': 10}], hist)
    d = c._build()
    assert [i['number'] for i in d['items']] == ['SA-a', 'SA-b']          # newest first, yesterday's cancel dropped
    assert d['items'][0]['en_route'] and d['items'][0]['minutes_before_cancel'] == 30
    assert d['items'][1]['cancelled_by'] == 'Pat Dispatcher'
    s = c._summary(d['items'], d['calls_today'])
    assert (s['total'], s['after_en_route'], s['rate_pct'], s['unspecified']) == (2, 1, 20.0, 1)
