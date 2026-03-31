"""Shared utilities for dispatch router modules."""

from datetime import datetime
from zoneinfo import ZoneInfo

from utils import parse_dt as _parse_dt
import cache

_ET = ZoneInfo('America/New_York')


def _today_start_utc():
    """Return today midnight ET as UTC ISO string for SOQL filters."""
    now = datetime.now(_ET)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%SZ')


def _fmt_et(iso_str):
    """Format an ISO datetime string to 'H:MM AM/PM' in Eastern."""
    dt = _parse_dt(iso_str)
    if not dt:
        return ''
    return dt.astimezone(_ET).strftime('%-I:%M %p')


def _sa_row(sa, ata=None, minutes_lost=None):
    """Build a standard SA detail dict from a ServiceAppointment record."""
    return {
        'sa_id': sa.get('Id', ''),
        'number': sa.get('AppointmentNumber', ''),
        'customer': (sa.get('Account') or {}).get('Name', ''),
        'work_type': (sa.get('WorkType') or {}).get('Name', ''),
        'territory': (sa.get('ServiceTerritory') or {}).get('Name', ''),
        'status': sa.get('Status', ''),
        'created_time': _fmt_et(sa.get('CreatedDate')),
        'cancel_reason': sa.get('ERS_Cancellation_Reason__c') or '',
        'reject_reason': sa.get('ERS_Facility_Decline_Reason__c') or '',
        'dispatch_method': sa.get('ERS_Dispatch_Method__c') or '',
        'ata_min': ata,
        'minutes_lost': minutes_lost,
    }


def _is_real_garage(name):
    """Filter out non-garage territories (offices, grid zones, fleet aggregates, spot)."""
    if not name:
        return False
    nl = name.lower()
    if any(x in nl for x in ('office', 'spot', 'fleet', 'region')):
        return False
    if len(name) <= 6 and name[:2].isalpha() and name[2:].isdigit():
        return False
    return True
