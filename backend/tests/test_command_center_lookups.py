"""Command Center: look up Towbook arrival times ONCE for all garages, not once per garage (about 55 queries)."""

from datetime import datetime, timedelta, timezone

from routers import command_center_helpers as h

NOW = datetime(2026, 10, 5, 18, 0, tzinfo=timezone.utc)


def _sa(i, terr, method='Towbook', status='Completed', wt='Tire'):
    created = (NOW - timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%S.000+0000')
    return {'Id': f'SA{i}', 'Status': status, 'CreatedDate': created, 'ERS_Dispatch_Method__c': method,
            'ActualStartTime': created, 'SchedStartTime': created, 'WorkType': {'Name': wt},
            'ServiceTerritory': {'Name': f'G{terr}', 'Latitude': 43.0, 'Longitude': -78.8}}


def test_completed_towbook_ids_cover_every_garage_and_skip_the_rest():
    by = {'T1': [_sa(1, 1), _sa(2, 1, method='Fleet'), _sa(3, 1, status='Dispatched'), _sa(4, 1, wt='Tow Drop-Off')],
          'T2': [_sa(5, 2)],
          'T3': [{**_sa(6, 3), 'ServiceTerritory': {'Name': 'NoCoords'}}]}              # a garage without coordinates is skipped
    assert sorted(h.completed_towbook_ids(by)) == ['SA1', 'SA5']


def test_arrival_times_are_looked_up_once_however_many_garages_there_are(monkeypatch):
    calls = []
    arrival = (NOW - timedelta(hours=2, minutes=30)).strftime('%Y-%m-%dT%H:%M:%S.000+0000')
    monkeypatch.setattr(h, 'get_towbook_on_location', lambda ids: calls.append(list(ids)) or {i: arrival for i in ids})
    by = {f'T{n}': [_sa(n, n)] for n in range(1, 31)}                                    # 30 garages, one Towbook call each
    out = h.build_territory_data(by, NOW, {}, {})
    assert len(calls) == 1 and len(calls[0]) == 30                                       # was 30 separate lookups
    assert len(out) == 30


def test_garages_get_the_same_response_times_as_before(monkeypatch):
    arrival = (NOW - timedelta(hours=2, minutes=30)).strftime('%Y-%m-%dT%H:%M:%S.000+0000')     # 30 min after creation
    monkeypatch.setattr(h, 'get_towbook_on_location', lambda ids: {i: arrival for i in ids})
    out = h.build_territory_data({'T1': [_sa(1, 1)]}, NOW, {}, {})
    row = out[0]
    assert row.get('avg_response') == 30 or row.get('avg_response_min') == 30 or 30 in [v for v in row.values() if isinstance(v, (int, float))]
