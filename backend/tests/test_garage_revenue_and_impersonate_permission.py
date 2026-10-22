"""ERS managers see the garage Performance and Revenue tabs; only one account may log in as another user."""

from permissions import IMPERSONATOR_USERNAME, can_access


def test_ers_manager_sees_garage_revenue_performance():
    assert can_access('ers-manager', 'garage.revenue_performance')
    assert not can_access('ers-supervisor', 'garage.revenue_performance')


def test_only_owner_can_log_in_as():
    assert IMPERSONATOR_USERNAME == 'nlaaroubi@nyaaa.com'
    assert can_access('superadmin', 'admin.impersonate') and not can_access('admin', 'admin.impersonate')
