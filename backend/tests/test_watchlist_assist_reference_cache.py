"""Dispatch Assist: truck logins and today's absences are read once per 10 minutes, not on every click (both modes)."""

import sf_client
from routers import watchlist_assist as wa


def _fake(log):
    def fake_all(soql, **kw):
        log.append(' '.join(soql.split()))
        if 'FROM Asset' in soql:
            return [{'ERS_Driver__c': 'SR1'}]
        if 'FROM ResourceAbsence' in soql:
            return [{'ResourceId': 'SR2'}]
        if 'FROM ServiceResource' in soql and 'ServiceResourceSkills' in soql:
            return [{'Id': 'SR1', 'Name': 'Driver One', 'LastKnownLatitude': 42.0, 'LastKnownLongitude': -78.0,
                     'LastKnownLocationDate': '2026-10-09T12:00:00.000+0000', 'ERS_Driver_Type__c': 'Fleet Driver',
                     'ServiceResourceSkills': None}]
        return []
    return fake_all


def test_logins_and_absences_are_one_shared_read_for_both_modes_and_every_click(monkeypatch):
    log = []
    monkeypatch.setattr(wa, 'sf_query_all', _fake(log))
    monkeypatch.setattr(sf_client, 'sf_query_all', _fake(log))      # what sf_query_all_shared reads through
    sf_client._shared.clear()

    wa._fetch_territory_drivers('0Hh000000000001', 42.0, -78.0)      # click 1, normal mode
    wa._fetch_territory_drivers('0Hh000000000001', 42.0, -78.0)      # click 2
    wa._fetch_000_resources(42.0, -78.0, '0Hh000000000002')          # click 3, 000 mode

    assert sum('FROM Asset' in q for q in log) == 1
    assert sum('FROM ResourceAbsence' in q for q in log) == 1
    assert sum('FROM AssignedResource' in q for q in log) == 3       # the busy query is still read live on every click


def test_cached_reference_data_still_filters_the_drivers(monkeypatch):
    log = []
    monkeypatch.setattr(wa, 'sf_query_all', _fake(log))
    monkeypatch.setattr(sf_client, 'sf_query_all', _fake(log))
    sf_client._shared.clear()
    for _ in range(2):
        out = wa._fetch_territory_drivers('0Hh000000000001', 42.0, -78.0)
        assert out['total_in_territory'] == 1                       # SR1 is on a truck and not absent


def test_reference_reads_are_cached_for_ten_minutes():
    assert wa._REFERENCE_TTL == 600
