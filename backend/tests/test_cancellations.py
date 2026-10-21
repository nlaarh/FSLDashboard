"""Cancellations tab: today's cancelled calls come from status history, not LastModifiedDate."""
from datetime import datetime, timedelta, timezone

from routers import cancellations as c


def _fake(monkeypatch, rows, count, history):
    def shared(soql, ttl=0):
        return count if 'COUNT(Id)' in soql else rows
    monkeypatch.setattr(c, 'sf_query_all_shared', shared)
    monkeypatch.setattr(c.sa_history, 'rows_for', lambda field, ids, created: [h for h in history if h.get('Field', 'Status') == field])
    monkeypatch.setattr(c.ref_data, 'drivers', lambda **k: [{'Id': '0HnAAAAAAAAAAAA', 'Name': 'Sam Driver', 'RelatedRecord': {'Phone': '555-0101'}}])


def _sa(i, status, made):
    return {'Id': i, 'AppointmentNumber': f'SA-{i}', 'CreatedDate': made.isoformat(), 'Status': status,
            'ERS_Cancellation_Reason__c': None, 'ERS_PTA__c': 45, 'ERS_Dispatch_Method__c': 'Field Services',
            'WorkType': {'Name': 'Tow'}, 'ServiceTerritory': {'Name': '076DO'}, 'AAA_ERS_Account_Facility__r': {'Phone': '555-0199'}}


def test_only_cancels_made_today_are_listed_and_typed(monkeypatch):
    day = c._et_today()
    start, _end = c._day_window(day)
    made = start + timedelta(minutes=1)
    rows = [_sa('a', 'Cancel Call - Service En Route', made), _sa('b', 'Canceled', made), _sa('old', 'Canceled', made)]
    hist = [
        {'ServiceAppointmentId': 'a', 'NewValue': 'Cancel Call - Service En Route', 'CreatedDate': (start + timedelta(minutes=31)).isoformat()},
        {'ServiceAppointmentId': 'b', 'NewValue': 'Canceled', 'CreatedDate': (start + timedelta(minutes=11)).isoformat(), 'CreatedBy': {'Name': 'Pat Dispatcher', 'Profile': {'Name': 'Membership User'}}},
        {'ServiceAppointmentId': 'old', 'NewValue': 'Canceled', 'CreatedDate': (start - timedelta(hours=3)).isoformat()},
        {'Field': 'ERS_Assigned_Resource__c', 'ServiceAppointmentId': 'a', 'NewValue': '0HnAAAAAAAAAAAA', 'CreatedDate': (start + timedelta(minutes=5)).isoformat()},
        {'Field': 'ERS_Assigned_Resource__c', 'ServiceAppointmentId': 'a', 'NewValue': None, 'OldValue': '0HnAAAAAAAAAAAA', 'CreatedDate': (start + timedelta(minutes=31)).isoformat()},   # cleared by the cancel itself
    ]
    _fake(monkeypatch, rows, [{'cnt': 10}], hist)
    d = c._build(day)
    assert [i['number'] for i in d['items']] == ['SA-a', 'SA-b']          # newest first, yesterday's cancel dropped
    assert d['items'][0]['en_route'] and d['items'][0]['minutes_before_cancel'] == 30
    assert (d['items'][0]['driver'], d['items'][0]['driver_phone'], d['items'][0]['garage_phone']) == ('Sam Driver', '555-0101', '555-0199')
    assert d['items'][1]['driver'] is None                      # no driver was assigned to b
    assert c._driver((None, 'Joe Towbook'), {}) == ('Joe Towbook', None)  # Towbook: a plain name, no phone
    assert d['items'][1]['cancelled_by'] == 'Pat Dispatcher'
    s = c._summary(d['items'], d['calls_today'])
    assert (s['total'], s['after_en_route'], s['rate_pct'], s['unspecified']) == (2, 1, 20.0, 1)


def test_day_window_follows_eastern_midnight_and_dst():
    from datetime import date
    lo, hi = c._day_window(date(2026, 10, 20))            # EDT: midnight ET = 04:00 UTC
    assert (lo.hour, (hi - lo).total_seconds()) == (4, 86400)
    lo, hi = c._day_window(date(2026, 11, 1))             # clocks go back that night: a 25-hour day
    assert (hi - lo).total_seconds() == 90000
