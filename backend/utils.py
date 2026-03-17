"""Shared utilities — single source of truth for helpers used across backend modules."""

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo('America/New_York')

# ── Dispatch constants ───────────────────────────────────────────────────────
TRAVEL_SPEED_MPH = 25
CYCLE_TIMES = {'tow': 115, 'battery': 38, 'light': 33}

TOW_SKILLS = {'tow', 'flat bed', 'wheel lift'}
LIGHT_SKILLS = {'tire', 'lockout', 'locksmith', 'winch out', 'fuel / miscellaneous', 'pvs'}
BATTERY_SKILLS = {'battery', 'jumpstart'}

SKILL_HIERARCHY = {
    'tow': ['tow', 'light', 'battery'],
    'light': ['light', 'battery'],
    'battery': ['battery'],
}


def parse_dt(dt_str):
    """Parse ISO datetime string (Salesforce format) to datetime object."""
    if not dt_str:
        return None
    if isinstance(dt_str, datetime):
        return dt_str
    try:
        return datetime.fromisoformat(
            str(dt_str).replace('+0000', '+00:00').replace('Z', '+00:00'))
    except Exception:
        return None


def to_eastern(dt_str):
    """Convert SF datetime string or datetime object to Eastern (DST-aware)."""
    dt = parse_dt(dt_str)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_ET)


def is_fleet_territory(name: str) -> bool:
    """Fleet garages have territory codes starting with 100 or 800.
    Everything else is a contractor (Towbook or On-Platform)."""
    if not name:
        return False
    return name.startswith('100') or name.startswith('800')


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles between two lat/lon points."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 3959
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lat2 - lat1)
    dn = math.radians(lon2 - lon1)
    a = math.sin(dl / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dn / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def minutes_since(dt_str, now_utc):
    """Minutes elapsed between a datetime string and now_utc."""
    dt = parse_dt(dt_str)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((now_utc - dt).total_seconds() / 60)
