"""Shared Salesforce reads for the dashboards: one copy, many screens.

Command Center, Ops Brief, Scheduler Insights, the PTA advisor and the driver map each used to pull their own variant of
the same data (drivers on shift, trucks, territory members, today's appointments, today's assigned drivers). Each variant
differed only in which columns it selected and which rows it filtered, so here one read selects the UNION of the columns
and every screen filters the rows in Python with exactly the conditions its own query had. Results are identical; the
Salesforce requests are not repeated.

  trucks / members     10 min   (who is logged into which truck, territory membership: slow-changing)
  drivers              2 min    (carry live GPS, so they must stay as fresh as the map, which was cached 2 min)
  appointments         60 s     (rolling last 24 h, every record type; screens cut out their own window)
  assigned drivers     60 s     (assignments of those appointments)
  hourly baseline      6 h      (8-week average per hour for one weekday; changes once a day)

Every read is single-flight (concurrent callers wait for one request), is never remembered when it fails, and falls back to
the last good copy if Salesforce errors. Callers get private copies: a screen can never alter what another screen reads.
"""

import copy
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import sf_client
from utils import parse_dt as _parse_dt

log = logging.getLogger('ref_data')

TTL_REFERENCE = 600        # trucks, territory members
TTL_DRIVERS = 120          # drivers carry GPS
TTL_LIVE = 60              # today's appointments and assignments
TTL_BASELINE = 6 * 3600

ERS_RECORD_TYPE = 'ers service appointment'

_guard = threading.Lock()
_entries: dict = {}        # key -> {'rows': ..., 'at': monotonic seconds}
_locks: dict = {}
stats = {'pulls': 0, 'hits': 0, 'stale_served': 0}


def _read(key: str, ttl: float, fetch):
    """Rows for `key`: the saved copy if younger than `ttl`, else ONE shared read (others wait for it)."""
    with _guard:
        hit = _entries.get(key)
        if hit and time.monotonic() - hit['at'] < ttl:
            stats['hits'] += 1
            return copy.deepcopy(hit['rows'])
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        with _guard:
            hit = _entries.get(key)
            if hit and time.monotonic() - hit['at'] < ttl:       # the thread we waited for just read it
                stats['hits'] += 1
                return copy.deepcopy(hit['rows'])
        try:
            rows = fetch()
        except Exception:
            with _guard:
                hit = _entries.get(key)
            if hit:                                              # Salesforce failed: the last good copy beats an error
                stats['stale_served'] += 1
                log.warning('ref_data %s: read failed, serving the previous copy', key, exc_info=True)
                return copy.deepcopy(hit['rows'])
            raise
        with _guard:
            _entries[key] = {'rows': rows, 'at': time.monotonic()}
            stats['pulls'] += 1
        return copy.deepcopy(rows)


def reset() -> None:
    """Forget every copy (tests)."""
    with _guard:
        _entries.clear()
        _locks.clear()
        stats.update(pulls=0, hits=0, stale_served=0)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def like(value: str, pattern: str) -> bool:
    """SOQL LIKE: case-insensitive, % = any run of characters, _ = one character."""
    rx = ''.join('.*' if c == '%' else '.' if c == '_' else re.escape(c) for c in pattern)
    return re.fullmatch(rx, value or '', re.IGNORECASE | re.DOTALL) is not None


# ── Trucks: who is logged into a vehicle ─────────────────────────────────────

def trucks(active_only: bool = True) -> list[dict]:
    """ERS trucks with a driver logged in. active_only: only drivers whose resource is active (the dashboards' filter;
    the driver map and Scheduler Insights never had it)."""
    rows = _read('trucks', TTL_REFERENCE, lambda: sf_client.sf_query_all("""
        SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c, ERS_LegacyTruckID__c, ERS_Driver__r.IsActive
        FROM Asset
        WHERE RecordType.Name = 'ERS Truck'
          AND ERS_Driver__c != null
    """))
    if active_only:
        rows = [r for r in rows if (r.get('ERS_Driver__r') or {}).get('IsActive') is True]
    return rows


# ── Drivers with live GPS ────────────────────────────────────────────────────

def drivers(require_gps: bool = True, exclude_names: tuple = (), exclude_exact: tuple = ()) -> list[dict]:
    """Active Fleet and On-Platform driver resources. require_gps: only those with a last known latitude.
    exclude_names: SOQL LIKE patterns to leave out, exclude_exact: names to leave out (both case-insensitive, as the
    screens' `NOT Name LIKE` / `Name !=` lines were)."""
    rows = _read('drivers', TTL_DRIVERS, lambda: sf_client.sf_query_all("""
        SELECT Id, Name, LastKnownLatitude, LastKnownLongitude, LastKnownLocationDate,
               ERS_Driver_Type__c, ERS_Tech_ID__c, RelatedRecord.Phone
        FROM ServiceResource
        WHERE IsActive = true AND ResourceType = 'T'
          AND ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
    """))
    if require_gps:
        rows = [r for r in rows if r.get('LastKnownLatitude') is not None]
    if exclude_names:
        rows = [r for r in rows if not any(like(r.get('Name'), p) for p in exclude_names)]
    if exclude_exact:
        skip = {n.lower() for n in exclude_exact}
        rows = [r for r in rows if (r.get('Name') or '').lower() not in skip]
    return rows


# ── Territory members ────────────────────────────────────────────────────────

def members() -> list[dict]:
    """Primary and secondary territory memberships of active truck resources: {ServiceResourceId, ServiceTerritoryId}."""
    return _read('members', TTL_REFERENCE, lambda: sf_client.sf_query_all("""
        SELECT ServiceResourceId, ServiceTerritoryId, TerritoryType
        FROM ServiceTerritoryMember
        WHERE TerritoryType IN ('P','S')
          AND ServiceResource.IsActive = true
          AND ServiceResource.ResourceType = 'T'
    """))


# ── Appointments and assignments of the last 24 hours ────────────────────────

def _fetch_appointments() -> list:
    cutoff = _iso(datetime.now(timezone.utc) - timedelta(hours=24))
    return sf_client.sf_query_all(f"""
        SELECT Id, AppointmentNumber, Status, CreatedDate,
               ActualStartTime, SchedStartTime,
               ERS_Dispatch_Method__c, ERS_PTA__c,
               ERS_Parent_Territory__c, ERS_Parent_Territory__r.Name,
               Latitude, Longitude, PostalCode, Street, City,
               ServiceTerritoryId, ServiceTerritory.Name,
               ServiceTerritory.Latitude, ServiceTerritory.Longitude,
               WorkType.Name, RecordType.Name,
               ERS_Cancellation_Reason__c, ERS_Facility_Decline_Reason__c,
               ERS_Dispatched_Geolocation__Latitude__s, ERS_Dispatched_Geolocation__Longitude__s,
               CreatedBy.Profile.Name,
               Off_Platform_Driver__r.Name, Off_Platform_Truck_Id__c
        FROM ServiceAppointment
        WHERE CreatedDate >= {cutoff}
          AND ServiceTerritoryId != null
        ORDER BY CreatedDate ASC
    """)


def _is_ers(row: dict) -> bool:
    return ((row.get('RecordType') or {}).get('Name') or '').lower() == ERS_RECORD_TYPE


def appointments(since: datetime, *, ers_only: bool = True, statuses=None) -> list[dict]:
    """Appointments with a territory created at/after `since` (must be within the last 24 h), oldest first."""
    rows = _read('appointments', TTL_LIVE, _fetch_appointments)
    out = []
    for r in rows:
        created = _parse_dt(r.get('CreatedDate'))
        if not created or created < since:
            continue
        if ers_only and not _is_ers(r):
            continue
        if statuses is not None and r.get('Status') not in statuses:
            continue
        out.append(r)
    return out


def _fetch_assigned() -> list:
    cutoff = _iso(datetime.now(timezone.utc) - timedelta(hours=24))
    return sf_client.sf_query_all(f"""
        SELECT ServiceResourceId, ServiceAppointmentId, ServiceResource.Name,
               ServiceResource.LastKnownLatitude, ServiceResource.LastKnownLongitude,
               ServiceResource.ERS_Driver_Type__c,
               ServiceAppointment.Status, ServiceAppointment.CreatedDate,
               ServiceAppointment.RecordType.Name, ServiceAppointment.ERS_Dispatch_Method__c
        FROM AssignedResource
        WHERE ServiceAppointment.CreatedDate >= {cutoff}
        ORDER BY CreatedDate ASC
    """)


def assigned(since: datetime, *, ers_only: bool = False, sa_statuses=None, dispatch_method: str | None = None) -> list[dict]:
    """Assigned drivers of appointments created at/after `since` (within the last 24 h)."""
    rows = _read('assigned', TTL_LIVE, _fetch_assigned)
    out = []
    for r in rows:
        sa = r.get('ServiceAppointment') or {}
        created = _parse_dt(sa.get('CreatedDate'))
        if not created or created < since:
            continue
        if ers_only and not _is_ers(sa):
            continue
        if sa_statuses is not None and sa.get('Status') not in sa_statuses:
            continue
        if dispatch_method is not None and (sa.get('ERS_Dispatch_Method__c') or '').lower() != dispatch_method.lower():
            continue
        out.append(r)
    return out


# ── Hourly baseline (8 weeks, one weekday) ───────────────────────────────────

def hourly_baseline(sf_dow: int, now_utc: datetime) -> list[dict]:
    """Appointments per hour (UTC hour) for one weekday over the last 8 weeks. Cached 6 h per weekday."""
    since = _iso((now_utc - timedelta(weeks=8)).replace(hour=0, minute=0, second=0, microsecond=0))
    return _read(f'baseline:{sf_dow}:{since[:10]}', TTL_BASELINE, lambda: sf_client.sf_query_all(f"""
        SELECT HOUR_IN_DAY(CreatedDate) hr, COUNT(Id) cnt
        FROM ServiceAppointment
        WHERE CreatedDate >= {since}
          AND DAY_IN_WEEK(CreatedDate) = {sf_dow}
          AND ServiceTerritoryId != null
          AND RecordType.Name = 'ERS Service Appointment'
          AND Status != 'Canceled'
        GROUP BY HOUR_IN_DAY(CreatedDate)
        ORDER BY HOUR_IN_DAY(CreatedDate)
    """))
