"""Potential Duplicate flag: RAP calls share one sponsor account, so RAP Information > Customer Name decides."""
from routers.watchlist_alerts import _is_duplicate_pair, _rap_customer

# The false alarm from 2026-10-09: two Hyundai RAP pick-ups 0.3 mi apart, different customers and streets.
WO_05200081 = {'Street': '77 Dorset Dr', 'Latitude': 42.970807, 'Longitude': -78.855467}
WO_05200190 = {'Street': '1235 Colvin Blvd', 'Latitude': 42.97468, 'Longitude': -78.85806}
DEAN = _rap_customer({'Type__c': 'RAP', 'Customer_Name__c': 'Dean  Gionis'})
UNKNOWN = _rap_customer({'Type__c': 'RAP', 'Customer_Name__c': 'NA  NA'})
NOT_RAP = _rap_customer({'Type__c': 'Standard', 'Customer_Name__c': None})


def test_customer_name_is_normalised_and_placeholders_are_unknown():
    assert DEAN == (True, 'DEAN GIONIS')
    assert UNKNOWN == (True, None)
    assert NOT_RAP == (False, None)
    assert _rap_customer(None) == (False, None)


def test_the_reported_false_alarm_is_not_a_duplicate():
    assert not _is_duplicate_pair(WO_05200081, WO_05200190, DEAN, UNKNOWN)


def test_rap_different_customers_same_spot_are_not_duplicates():
    other = _rap_customer({'Type__c': 'RAP', 'Customer_Name__c': 'Jane Doe'})
    assert not _is_duplicate_pair(WO_05200081, dict(WO_05200081), DEAN, other)


def test_rap_same_customer_nearby_is_a_duplicate():
    assert _is_duplicate_pair(WO_05200081, WO_05200190, DEAN, DEAN)


def test_rap_unknown_name_counts_only_on_the_same_street():
    assert _is_duplicate_pair(WO_05200081, {**WO_05200190, 'Street': '77 DORSET DR '}, UNKNOWN, UNKNOWN)
    assert not _is_duplicate_pair(WO_05200081, WO_05200190, UNKNOWN, UNKNOWN)


def test_regular_member_calls_unchanged():
    assert _is_duplicate_pair(WO_05200081, WO_05200190)          # 0.3 mi apart, same account
    far = {'Street': '1 Main St', 'Latitude': 43.16, 'Longitude': -77.61}
    assert not _is_duplicate_pair(WO_05200081, far)
    assert _is_duplicate_pair({'Street': '1 Main St'}, {'Street': '1 main st'})   # no GPS, same street
