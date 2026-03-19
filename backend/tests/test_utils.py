"""Unit tests for backend/utils.py — shared helpers."""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from utils import parse_dt, to_eastern, is_fleet_territory, haversine, minutes_since, _ET


# ── parse_dt ─────────────────────────────────────────────────────────────────

class TestParseDt:
    def test_none_returns_none(self):
        assert parse_dt(None) is None

    def test_empty_string_returns_none(self):
        assert parse_dt("") is None

    def test_datetime_passthrough(self):
        dt = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)
        assert parse_dt(dt) is dt

    def test_iso_with_z(self):
        result = parse_dt("2026-03-16T14:30:00Z")
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.hour == 14

    def test_iso_with_plus0000(self):
        result = parse_dt("2026-03-16T14:30:00+0000")
        assert result is not None
        assert result.tzinfo is not None

    def test_iso_with_offset(self):
        result = parse_dt("2026-03-16T14:30:00+00:00")
        assert result is not None

    def test_garbage_returns_none(self):
        assert parse_dt("not-a-date") is None

    def test_integer_returns_none(self):
        assert parse_dt(12345) is None


# ── to_eastern ───────────────────────────────────────────────────────────────

class TestToEastern:
    def test_none_returns_none(self):
        assert to_eastern(None) is None

    def test_utc_to_eastern_winter(self):
        # Jan = EST = UTC-5
        result = to_eastern("2026-01-15T17:00:00Z")
        assert result is not None
        assert result.hour == 12  # 17 UTC = 12 EST

    def test_utc_to_eastern_summer(self):
        # Jul = EDT = UTC-4
        result = to_eastern("2026-07-15T17:00:00Z")
        assert result is not None
        assert result.hour == 13  # 17 UTC = 13 EDT

    def test_datetime_object_input(self):
        dt = datetime(2026, 3, 16, 20, 0, tzinfo=timezone.utc)
        result = to_eastern(dt)
        assert result is not None
        assert result.tzinfo is not None

    def test_naive_datetime_assumed_utc(self):
        # Naive datetime should be treated as UTC
        result = to_eastern("2026-01-15T17:00:00")
        assert result is not None


# ── is_fleet_territory ───────────────────────────────────────────────────────

class TestIsFleetTerritory:
    def test_100_prefix_is_fleet(self):
        assert is_fleet_territory("100 - WESTERN NEW YORK FLEET") is True

    def test_800_prefix_is_fleet(self):
        assert is_fleet_territory("800 - CENTRAL REGION ERS FLEET SERVICES") is True

    def test_100a_subzone_is_fleet(self):
        assert is_fleet_territory("100A - WNY Sub-Zone") is True

    def test_contractor_not_fleet(self):
        assert is_fleet_territory("201 - J'S AUTO") is False

    def test_076d_on_platform_not_fleet(self):
        assert is_fleet_territory("076DO - TRANSIT AUTO DETAIL") is False

    def test_empty_string(self):
        assert is_fleet_territory("") is False

    def test_none(self):
        assert is_fleet_territory(None) is False

    def test_000_spot_not_fleet(self):
        assert is_fleet_territory("000 - SPOT TEST") is False


# ── haversine ────────────────────────────────────────────────────────────────

class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine(42.8864, -78.8784, 42.8864, -78.8784) == 0.0

    def test_buffalo_to_rochester(self):
        # ~73 miles
        dist = haversine(42.8864, -78.8784, 43.1566, -77.6088)
        assert dist is not None
        assert 65 < dist < 80

    def test_none_lat_returns_none(self):
        assert haversine(None, -78.0, 43.0, -77.0) is None

    def test_none_lon_returns_none(self):
        assert haversine(42.0, None, 43.0, -77.0) is None


# ── minutes_since ────────────────────────────────────────────────────────────

class TestMinutesSince:
    def test_60_minutes_ago(self):
        now = datetime(2026, 3, 16, 13, 0, tzinfo=timezone.utc)
        result = minutes_since("2026-03-16T12:00:00Z", now)
        assert result == 60

    def test_none_input(self):
        now = datetime(2026, 3, 16, 13, 0, tzinfo=timezone.utc)
        assert minutes_since(None, now) is None

    def test_empty_string(self):
        now = datetime(2026, 3, 16, 13, 0, tzinfo=timezone.utc)
        assert minutes_since("", now) is None


# ── _ET constant ─────────────────────────────────────────────────────────────

def test_et_is_eastern():
    assert _ET == ZoneInfo('America/New_York')
