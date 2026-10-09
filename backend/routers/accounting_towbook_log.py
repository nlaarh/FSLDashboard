"""Accounting audit: the Towbook update logs (driver GPS at each status tap) for one work order."""

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from sf_client import sanitize_soql
from utils import parse_dt

_ET = ZoneInfo('America/New_York')
_DAYS_BEFORE, _DAYS_AFTER = 1, 3


def towbook_log_soql(wo_number: str, wo_created) -> str | None:
    """Towbook update logs for one work order, read inside a CreatedDate window (the log table has 367k rows and no
    index on ReferenceId__c: without the window it is a 6 s full scan). Towbook writes the reference as
    '084-<YYYYMMDD>-<work order number>' (the plain number is kept for older logs); the date is the call's, so the
    Eastern and UTC dates of the work order's creation are both tried. None when the creation date is unknown."""
    created = parse_dt(wo_created)
    if created is None or not wo_number:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    num = sanitize_soql(wo_number)
    dates = {created.astimezone(_ET).strftime('%Y%m%d'), created.astimezone(timezone.utc).strftime('%Y%m%d')}
    refs = ", ".join(f"'{r}'" for r in [num] + [f'084-{d}-{num}' for d in sorted(dates)])
    start = (created - timedelta(days=_DAYS_BEFORE)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    end = (created + timedelta(days=_DAYS_AFTER)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return (f"SELECT ERS_Request__c, CreatedDate FROM rflib_Log__c "
            f"WHERE CreatedDate >= {start} AND CreatedDate < {end} "
            f"AND Type__c = 'Integration Towbook Inbound' AND Context__c = 'Appointment Update from Towbook' "
            f"AND ReferenceId__c IN ({refs}) ORDER BY CreatedDate ASC LIMIT 50")
