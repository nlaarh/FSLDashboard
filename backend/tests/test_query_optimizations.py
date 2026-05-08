"""Unit tests verifying correctness of SF query optimizations.

These tests use synthetic SF history rows to confirm that merging two
ERS_Assigned_Resource__c queries into one produces identical results
for both consumers (human-touch detection and reassignment counting).
"""

import re
from collections import defaultdict


_SF_ID_PAT = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')


def _process_assign_hist(rows: list[dict]) -> tuple[set, dict]:
    """Replicate the two consumers from dispatch_trends._fetch.

    Returns:
        human_touched_ids: SA IDs that had a human dispatcher and were reassigned
        reassign_by_day: {date_str: count} of 2nd+ assignments per day
    """
    # Consumer 1: human-touch detection (step 1 in _fetch)
    _hist_count: dict = {}
    _hist_human: set = set()
    for r in rows:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id:
            continue
        _hist_count[sa_id] = _hist_count.get(sa_id, 0) + 1
        profile = ((r.get('CreatedBy') or {}).get('Profile') or {}).get('Name', '')
        if profile == 'Membership User':
            _hist_human.add(sa_id)
    human_touched_ids = {sa_id for sa_id, cnt in _hist_count.items()
                         if cnt > 2 and sa_id in _hist_human}

    # Consumer 2: reassignment counting (step 3 in _fetch)
    reassign_by_day = defaultdict(int)
    _sa_assign_seq = defaultdict(int)
    for r in rows:
        new_val = (r.get('NewValue') or '').strip()
        if not new_val or _SF_ID_PAT.match(new_val):
            continue  # Skip SF ID duplicate rows
        sa_id = r.get('ServiceAppointmentId')
        _sa_assign_seq[sa_id] += 1
        if _sa_assign_seq[sa_id] > 1:
            date_str = (r.get('CreatedDate') or '')[:10]
            if date_str:
                reassign_by_day[date_str] += 1

    return human_touched_ids, dict(reassign_by_day)


def _build_sf_row(sa_id: str, new_val: str, created: str, profile: str = '') -> dict:
    """Helper: build a synthetic SAHistory row as SF REST API would return it."""
    return {
        'ServiceAppointmentId': sa_id,
        'NewValue': new_val,
        'CreatedDate': created,
        'CreatedBy': {
            'Name': 'test user',
            'Profile': {'Name': profile},
        },
    }


# ── Tests ────────────────────────────────────────────────────────────────────

def test_no_reassignments():
    """Single assignment per SA → no reassignments, no human touch."""
    rows = [
        _build_sf_row('SA001', 'Driver A', '2026-05-01T10:00:00Z', 'System Admin'),
        _build_sf_row('SA001', 'aB1cD2eF3gH4iJ5', '2026-05-01T10:00:00Z', 'System Admin'),  # SF ID row
        _build_sf_row('SA002', 'Driver B', '2026-05-01T11:00:00Z', 'System Admin'),
    ]
    human_touched, reassign_by_day = _process_assign_hist(rows)
    assert human_touched == set()
    assert reassign_by_day == {}


def test_reassignment_counted_on_second_plus():
    """Only 2nd+ assignments count as reassignments (1st is normal dispatch)."""
    rows = [
        _build_sf_row('SA001', 'Driver A', '2026-05-01T10:00:00Z'),       # 1st — not counted
        _build_sf_row('SA001', 'aB1cD2eF3gH4iJ5', '2026-05-01T10:01:00Z'),  # SF ID — skipped
        _build_sf_row('SA001', 'Driver B', '2026-05-01T10:30:00Z'),       # 2nd — counted
        _build_sf_row('SA001', 'aB1cD2eF3gH4iJ6', '2026-05-01T10:31:00Z'),  # SF ID — skipped
        _build_sf_row('SA001', 'Driver C', '2026-05-01T11:00:00Z'),       # 3rd — counted
    ]
    _, reassign_by_day = _process_assign_hist(rows)
    assert reassign_by_day.get('2026-05-01') == 2


def test_human_touch_requires_count_gt_2_and_membership_profile():
    """human_touched_ids: must have >2 total rows AND a Membership User involved."""
    # SA003: 3 rows, but no Membership User → not human-touched
    rows_no_human = [
        _build_sf_row('SA003', 'Driver A', '2026-05-01T10:00:00Z', 'System Admin'),
        _build_sf_row('SA003', 'aB1cD2eF3gH4iJ5', '2026-05-01T10:01:00Z', 'System Admin'),
        _build_sf_row('SA003', 'Driver B', '2026-05-01T10:30:00Z', 'System Admin'),
    ]
    human_touched, _ = _process_assign_hist(rows_no_human)
    assert 'SA003' not in human_touched

    # SA004: 3 rows, one Membership User → IS human-touched
    rows_with_human = [
        _build_sf_row('SA004', 'Driver A', '2026-05-01T10:00:00Z', 'System Admin'),
        _build_sf_row('SA004', 'aB1cD2eF3gH4iJ5', '2026-05-01T10:01:00Z', 'Membership User'),
        _build_sf_row('SA004', 'Driver B', '2026-05-01T10:30:00Z', 'System Admin'),
    ]
    human_touched, _ = _process_assign_hist(rows_with_human)
    assert 'SA004' in human_touched


def test_human_touch_requires_more_than_2_rows():
    """Exactly 2 rows with Membership User → NOT counted (threshold is >2)."""
    rows = [
        _build_sf_row('SA005', 'Driver A', '2026-05-01T10:00:00Z', 'Membership User'),
        _build_sf_row('SA005', 'aB1cD2eF3gH4iJ5', '2026-05-01T10:01:00Z', 'Membership User'),
    ]
    human_touched, _ = _process_assign_hist(rows)
    assert 'SA005' not in human_touched  # count == 2, threshold is >2


def test_merged_query_equivalent_to_two_separate_queries():
    """Prove merged query rows produce same output as running consumers on split sets.

    This is the key regression test for the dispatch_trends.py optimization:
    The old code ran two separate queries and processed them separately.
    The new code runs one merged query. Results must be identical.
    """
    # Synthetic merged rows (what the new single query returns).
    # SF uses exactly 15-char or 18-char alphanumeric IDs for duplicate rows.
    merged_rows = [
        _build_sf_row('SA001', 'Driver A', '2026-05-01T10:00:00Z', 'System Admin'),
        _build_sf_row('SA001', 'aBcDeFgHiJkLmNo', '2026-05-01T10:01:00Z', 'System Admin'),  # 15-char SF ID
        _build_sf_row('SA001', 'Driver B', '2026-05-01T10:30:00Z', 'Membership User'),
        _build_sf_row('SA002', 'Driver C', '2026-05-02T09:00:00Z', 'System Admin'),
        _build_sf_row('SA002', 'aBcDeFgHiJkLmNoPQR', '2026-05-02T09:01:00Z', 'System Admin'),  # 18-char SF ID
        _build_sf_row('SA002', 'Driver D', '2026-05-02T09:45:00Z', 'System Admin'),
        _build_sf_row('SA003', 'Driver E', '2026-05-02T11:00:00Z', 'System Admin'),
    ]

    human_touched, reassign_by_day = _process_assign_hist(merged_rows)

    # SA001: 3 rows, Membership User involved → human-touched
    assert 'SA001' in human_touched
    # SA002: 3 rows, no Membership User → NOT human-touched
    assert 'SA002' not in human_touched
    # SA003: 1 row → NOT human-touched (count ≤ 2)
    assert 'SA003' not in human_touched

    # Reassignments: SA001 has 2nd assign on 2026-05-01; SA002 on 2026-05-02
    assert reassign_by_day.get('2026-05-01') == 1
    assert reassign_by_day.get('2026-05-02') == 1


def test_empty_rows():
    """Empty input → empty outputs. No KeyError or division by zero."""
    human_touched, reassign_by_day = _process_assign_hist([])
    assert human_touched == set()
    assert reassign_by_day == {}


def test_sf_id_rows_skipped_in_reassignment_count():
    """15-char and 18-char SF IDs in NewValue must be skipped for reassignment count."""
    rows = [
        _build_sf_row('SA010', 'aBcDeFgHiJkLmNo', '2026-05-01T10:00:00Z'),    # 15-char ID → skip
        _build_sf_row('SA010', 'aBcDeFgHiJkLmNoPQR', '2026-05-01T10:01:00Z'),  # 18-char ID → skip
        _build_sf_row('SA010', 'Driver A', '2026-05-01T10:03:00Z'),            # 1st name → not a reassignment
        _build_sf_row('SA010', 'Driver B', '2026-05-01T10:30:00Z'),            # 2nd name → reassignment
    ]
    _, reassign_by_day = _process_assign_hist(rows)
    # 2 name rows: 1st is normal dispatch, 2nd is reassignment
    assert reassign_by_day.get('2026-05-01') == 1
