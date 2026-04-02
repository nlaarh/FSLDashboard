"""Shared utilities — single source of truth for helpers used across backend modules."""

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo('America/New_York')

# ── ERS filter — single source of truth ──────────────────────────────────────
# Use in every SOQL query that fetches ServiceAppointments to exclude
# non-ERS records (travel, insurance, lobby appointments).
# RecordType is the definitive flag — always populated, can be used in GROUP BY.
ERS_RECORD_TYPE = "ERS Service Appointment"
ERS_SA_FILTER = f"RecordType.Name = '{ERS_RECORD_TYPE}'"

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


def totally_satisfied_pct(rows, field):
    """Calculate Totally Satisfied % from a list of survey rows.

    Single source of truth — use this everywhere instead of inline
    ``round(100 * ts_count / total_count)`` patterns.
    """
    total = sum(1 for r in rows if r.get(field))
    if total == 0:
        return None
    ts = sum(1 for r in rows if (r.get(field) or '').lower() == 'totally satisfied')
    return round(100 * ts / total)


def soql_date_range(start_date: str, end_date: str = None):
    """Return (start_utc, end_utc) for SOQL WHERE clauses.

    start_date / end_date: 'YYYY-MM-DD'.
    end_utc uses T23:59:59Z when end_date is provided,
    or T00:00:00Z of the next day when end_date is None (exclusive upper bound).
    """
    from datetime import timedelta as _td
    start_utc = f"{start_date}T00:00:00Z"
    if end_date:
        end_utc = f"{end_date}T23:59:59Z"
    else:
        d = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_utc = f"{(d + _td(days=1)).isoformat()}T00:00:00Z"
    return start_utc, end_utc
