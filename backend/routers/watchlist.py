"""Dispatch Watchlist — SAs requiring dispatcher attention.

Auto-includes SAs that were manually reassigned by a human dispatcher,
had driver rejections, or experienced dispatch thrash (3+ driver assignments).
Auto-drops SAs completed/canceled for more than 5 minutes.
Only shows SAs from the last 24 hours.
"""

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

import cache
from sf_client import sf_query_all, sf_parallel
from utils import parse_dt as _parse_dt, _ET
from sf_batch import batch_soql_parallel

router = APIRouter()
log = logging.getLogger('watchlist')

CACHE_KEY = 'dispatch_watchlist'
CACHE_TTL = 60

# ── Constants ────────────────────────────────────────────────────────────────

# SA lifecycle phases in order
_PHASE_ORDER = ['Dispatched', 'Accepted', 'En Route', 'On Location', 'In Progress', 'Completed']

# Terminal statuses — SA is done
_TERMINAL_STATUSES = {'Completed', 'Canceled', 'Cancelled', 'Cannot Complete'}

# Human dispatchers have this profile
_HUMAN_PROFILE = 'Membership User'

# System user profiles — NOT human dispatchers
_SYSTEM_PROFILES = {
    'System Administrator', 'Contact Center', 'FSL System User',
    'Platform Integration User', 'IT System User', 'Mulesoft Integration',
}

# Channel mapping from ERS_Driver_Type__c
_CHANNEL_MAP = {
    'Fleet Driver': 'Fleet',
    'On-Platform Contractor Driver': 'On-Platform',
    'Off-Platform Contractor Driver': 'Off-Platform',
}

# SF IDs pattern — used to skip duplicate SAHistory rows
_SF_ID = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')

# Thrash threshold — 3+ distinct driver assignments
_THRASH_THRESHOLD = 3


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.get("/api/watchlist")
def api_watchlist():
    """SAs that dispatchers should be closely following.

    Auto-follow: manual reassignment, driver rejection, or dispatch thrash.
    Auto-drop: completed/canceled > 5 minutes ago.
    """
    cached = cache.get(CACHE_KEY)
    if cached:
        return cached
    cached = cache.disk_get(CACHE_KEY, CACHE_TTL)
    if cached:
        cache.put(CACHE_KEY, cached, CACHE_TTL)
        return cached
    try:
        result = _build_watchlist()
    except Exception as e:
        log.error(f"Watchlist build failed: {e}", exc_info=True)
        # Fall back to stale cache on failure
        stale = cache.get_stale(CACHE_KEY) or cache.disk_get_stale(CACHE_KEY)
        if stale:
            return stale
        return {'watchlist': [], 'total': 0, 'last_updated': None, 'error': str(e)}
    cache.put(CACHE_KEY, result, CACHE_TTL)
    cache.disk_put(CACHE_KEY, result, CACHE_TTL)
    return result


@router.post("/api/watchlist/follow")
def api_watchlist_follow(body: dict):
    """Manually add an SA to the shared watchlist."""
    sa_number = body.get('sa_number', '').strip()
    sa_id = body.get('sa_id', '')
    added_by = body.get('added_by', '')
    if not sa_number:
        return {'error': 'sa_number required'}
    import database
    database.watchlist_add(sa_number, sa_id, added_by)
    cache.invalidate(CACHE_KEY)
    cache.disk_invalidate(CACHE_KEY)
    log.info(f"Manual watchlist follow: {sa_number} by {added_by}")
    return {'ok': True, 'sa_number': sa_number}


@router.delete("/api/watchlist/follow/{sa_number}")
def api_watchlist_unfollow(sa_number: str):
    """Remove an SA from the manual watchlist."""
    import database
    database.watchlist_remove(sa_number)
    cache.invalidate(CACHE_KEY)
    cache.disk_invalidate(CACHE_KEY)
    log.info(f"Manual watchlist unfollow: {sa_number}")
    return {'ok': True, 'sa_number': sa_number}


@router.get("/api/watchlist/manual")
def api_watchlist_manual():
    """Get all manually-followed SA numbers (for star icon state)."""
    import database
    items = database.watchlist_list()
    return {'followed': [i['sa_number'] for i in items]}


# ── Build watchlist ──────────────────────────────────────────────────────────

def _build_watchlist() -> dict:
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = (now_utc - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
    # Keep terminal calls only if they changed very recently (UI only needs a short
    # grace window to show "Completed Xm ago" before auto-drop).
    cutoff_recent_terminal = (now_utc - timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # ── Load manually-followed SAs ──
    import database
    manual_items = database.watchlist_list()
    manual_sa_numbers = {item['sa_number'] for item in manual_items}

    # ── Query 1: Active + recently completed SAs (last 24h) ──
    sas = sf_query_all(f"""
        SELECT Id, AppointmentNumber, Status, StatusCategory,
               ServiceTerritoryId, ServiceTerritory.Name,
               WorkType.Name, ERS_PTA__c, Description,
               ERS_Tow_Pick_Up_Drop_off__c,
               CreatedDate, SchedStartTime, ActualStartTime, ActualEndTime,
               LastModifiedDate, Street, City, Latitude, Longitude
        FROM ServiceAppointment
        WHERE RecordType.Name = 'ERS Service Appointment'
          AND ServiceTerritoryId != null
          AND CreatedDate >= {cutoff_24h}
          AND (
                StatusCategory IN ('None', 'Scheduled', 'Dispatched', 'InProgress', 'CheckedIn')
                OR (
                    StatusCategory IN ('Completed', 'Canceled')
                    AND LastModifiedDate >= {cutoff_recent_terminal}
                )
          )
        ORDER BY CreatedDate ASC
    """)

    if not sas:
        return {'watchlist': [], 'total': 0, 'last_updated': now_utc.isoformat()}

    sa_map = {s['Id']: s for s in sas}
    sa_ids = list(sa_map.keys())

    # ── Queries 2 & 3: AssignedResource + SAHistory in parallel ──
    def _q_assigned():
        return batch_soql_parallel("""
            SELECT Id, ServiceAppointmentId,
                   ServiceResource.Name, ServiceResource.Id,
                   ServiceResource.ERS_Tech_ID__c,
                   ServiceResource.ERS_Driver_Type__c,
                   ServiceResource.LastKnownLatitude,
                   ServiceResource.LastKnownLongitude,
                   CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name
            FROM AssignedResource
            WHERE ServiceAppointmentId IN ('{id_list}')
            ORDER BY CreatedDate ASC
        """, sa_ids, chunk_size=200)

    def _q_history():
        return batch_soql_parallel("""
            SELECT ServiceAppointmentId, Field, OldValue, NewValue,
                   CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointmentId IN ('{id_list}')
              AND Field IN ('Status', 'ERS_Assigned_Resource__c')
            ORDER BY CreatedDate ASC
        """, sa_ids, chunk_size=200)

    data = sf_parallel(assigned=_q_assigned, history=_q_history)
    ar_rows = data['assigned']
    hist_rows = data['history']

    # ── Index data by SA ──
    ar_by_sa = defaultdict(list)       # sa_id -> [AssignedResource records]
    hist_by_sa = defaultdict(list)     # sa_id -> [SAHistory records]

    for r in ar_rows:
        sa_id = r.get('ServiceAppointmentId')
        if sa_id:
            ar_by_sa[sa_id].append(r)

    for r in hist_rows:
        sa_id = r.get('ServiceAppointmentId')
        if sa_id:
            hist_by_sa[sa_id].append(r)

    # ── Evaluate each SA against watchlist criteria ──
    watchlist = []
    for sa_id, sa in sa_map.items():
        # Auto-drop: terminal status AND ActualEndTime > 5 min ago
        status = sa.get('Status', '')
        if status in _TERMINAL_STATUSES:
            end_dt = _parse_dt(sa.get('ActualEndTime'))
            if end_dt:
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                if (now_utc - end_dt).total_seconds() > 300:
                    continue
            else:
                # No ActualEndTime but terminal — use LastModifiedDate as fallback
                mod_dt = _parse_dt(sa.get('LastModifiedDate'))
                if mod_dt:
                    if mod_dt.tzinfo is None:
                        mod_dt = mod_dt.replace(tzinfo=timezone.utc)
                    if (now_utc - mod_dt).total_seconds() > 300:
                        continue

        ar_list = ar_by_sa.get(sa_id, [])
        hist_list = hist_by_sa.get(sa_id, [])

        reasons, flags = _evaluate_criteria(ar_list, hist_list)

        # Also include if manually followed by a dispatcher
        sa_num = sa.get('AppointmentNumber', '')
        if not reasons and sa_num in manual_sa_numbers:
            reasons = ['Manually followed']
            flags = {'reassignment_count': 0}

        if not reasons:
            continue

        entry = _build_entry(sa, ar_list, hist_list, reasons, flags, now_utc, sa_map)
        entry['manual_follow'] = sa_num in manual_sa_numbers
        watchlist.append(entry)

    # ── Auto-cleanup: remove manual follows for completed SAs ──
    completed_sa_numbers = set()
    for entry in watchlist:
        if entry.get('current_status') in ('Completed', 'Canceled', 'Unable to Complete',
                                            'Cancel Call - Service Not En Route',
                                            'Cancel Call - Service En Route', 'No-Show'):
            if entry.get('manual_follow'):
                completed_sa_numbers.add(entry['sa_number'])
    for sa_num in completed_sa_numbers:
        try:
            database.watchlist_remove(sa_num)
            log.info(f"Auto-removed completed SA from manual watchlist: {sa_num}")
        except Exception:
            pass

    # ── Sort: active flagged first, then by reassignment count, completed last ──
    watchlist.sort(key=_sort_key)

    return {
        'watchlist': watchlist,
        'total': len(watchlist),
        'manual_followed': list(manual_sa_numbers),
        'last_updated': now_utc.isoformat(),
    }


# ── Criteria evaluation ─────────────────────────────────────────────────────

def _evaluate_criteria(ar_list: list, hist_list: list) -> tuple[list, dict]:
    """Check if an SA meets any watchlist criteria.

    Returns (reasons: list[str], flags: dict) or ([], {}) if not watchlisted.
    """
    reasons = []
    flags = {
        'thrash': False,
        'rejected': False,
        'human_intervention': False,
        'reassignment_count': 0,
        'human_dispatchers': [],
    }

    # ── Criterion 1: 3+ distinct AssignedResource records (dispatch thrash) ──
    distinct_drivers = set()
    for ar in ar_list:
        sr = ar.get('ServiceResource') or {}
        name = sr.get('Name')
        if name:
            distinct_drivers.add(name)

    if len(distinct_drivers) >= _THRASH_THRESHOLD:
        flags['thrash'] = True
        reasons.append(f"{len(distinct_drivers)} driver changes")

    # ── Criterion 2: Driver rejection (Status -> 'Rejected') ──
    for h in hist_list:
        if h.get('Field') == 'Status' and h.get('NewValue') == 'Rejected':
            flags['rejected'] = True
            if 'driver rejected' not in reasons:
                reasons.append('driver rejected')
            break

    # ── Criterion 3: Human dispatcher manually reassigned ──
    # Count resource changes and identify human dispatchers
    resource_changes = 0
    human_names = []
    for h in hist_list:
        if h.get('Field') != 'ERS_Assigned_Resource__c':
            continue
        new_val = (h.get('NewValue') or '').strip()
        # Skip SF ID duplicate rows
        if new_val and _SF_ID.match(new_val):
            continue
        if not new_val:
            old_val = (h.get('OldValue') or '').strip()
            if old_val and _SF_ID.match(old_val):
                continue

        resource_changes += 1
        cb = h.get('CreatedBy') or {}
        profile = (cb.get('Profile') or {}).get('Name', '')
        if profile == _HUMAN_PROFILE:
            flags['human_intervention'] = True
            name = cb.get('Name', '?')
            if name not in human_names:
                human_names.append(name)

    flags['reassignment_count'] = resource_changes
    flags['human_dispatchers'] = human_names

    if flags['human_intervention'] and resource_changes > 0:
        primary = human_names[0] if human_names else '?'
        if resource_changes > 1:
            reasons.insert(0, f"{resource_changes} reassignments")
        else:
            reasons.append(f"Manual dispatch by {primary}")

    if not reasons:
        return [], {}

    return reasons, flags


# ── Build a single watchlist entry ───────────────────────────────────────────

def _build_entry(sa: dict, ar_list: list, hist_list: list,
                 reasons: list, flags: dict, now_utc: datetime, sa_map: dict = None) -> dict:
    """Build the full watchlist entry dict for one SA."""
    status = sa.get('Status', '')
    territory_name = (sa.get('ServiceTerritory') or {}).get('Name', '')
    territory_short = territory_name.split(' - ')[0].strip() if ' - ' in territory_name else territory_name

    # Driver info from most recent AssignedResource
    driver_name = ''
    driver_initials = ''
    channel = ''
    driver_lat = None
    driver_lon = None
    if ar_list:
        latest_ar = ar_list[-1]
        sr = latest_ar.get('ServiceResource') or {}
        driver_name = sr.get('Name', '')
        driver_initials = _initials(driver_name)
        driver_type = sr.get('ERS_Driver_Type__c', '')
        channel = _CHANNEL_MAP.get(driver_type, '')
        driver_lat = sr.get('LastKnownLatitude')
        driver_lon = sr.get('LastKnownLongitude')

    # Time in current status
    time_in_status = _time_in_status(hist_list, status, now_utc)

    # PTA delta
    pta_delta = _pta_delta(sa, now_utc)

    # Flag: stuck or aging
    flag = _compute_flag(status, time_in_status)

    # Reason string
    reason_str = ', '.join(reasons)

    # Reassigned-by list (all who touched it)
    reassigned_by = []
    for h in hist_list:
        if h.get('Field') != 'ERS_Assigned_Resource__c':
            continue
        new_val = (h.get('NewValue') or '').strip()
        if new_val and _SF_ID.match(new_val):
            continue
        cb = h.get('CreatedBy') or {}
        name = cb.get('Name', '')
        if name and name not in reassigned_by:
            reassigned_by.append(name)

    # Human dispatcher — the human who intervened most
    human_dispatcher = _primary_human(flags.get('human_dispatchers', []), hist_list)

    # Phase timeline
    phases = _build_phases(hist_list, status, now_utc)

    # Linked SA (tow drop-off) — resolve SF ID to AppointmentNumber
    linked_raw = sa.get('ERS_Tow_Pick_Up_Drop_off__c') or ''
    linked_sa = None
    if linked_raw and sa_map:
        linked_record = sa_map.get(linked_raw)
        if linked_record:
            linked_sa = linked_record.get('AppointmentNumber')

    return {
        'sa_number': sa.get('AppointmentNumber', ''),
        'sa_id': sa.get('Id', ''),
        'driver_name': driver_name,
        'driver_initials': driver_initials,
        'territory': territory_name,
        'territory_short': territory_short,
        'channel': channel,
        'current_status': status,
        'status': status,  # compatibility for existing UI consumers
        'time_in_status_min': time_in_status,
        'flag': flag,
        'pta_delta_min': pta_delta,
        'reason': reason_str,
        'reassignment_count': flags.get('reassignment_count', 0),
        'reassigned_by': reassigned_by,
        'human_dispatcher': human_dispatcher,
        'phases': phases,
        'work_type': (sa.get('WorkType') or {}).get('Name', ''),
        'description': sa.get('Description') or '',
        'address': f"{sa.get('Street') or ''}, {sa.get('City') or ''}".strip(', '),
        'created_at': sa.get('CreatedDate') or '',
        'completed_at': sa.get('ActualEndTime') or '',
        'linked_sa': linked_sa,
        'linked_sa_number': linked_sa,  # compatibility for existing UI consumers
        'customer_lat': sa.get('Latitude'),
        'customer_lon': sa.get('Longitude'),
        'driver_lat': driver_lat,
        'driver_lon': driver_lon,
    }


# ── Phase timeline builder ───────────────────────────────────────────────────

def _build_phases(hist_list: list, current_status: str, now_utc: datetime) -> list:
    """Build the 6-phase timeline from SAHistory status transitions.

    Each phase: {name, duration_min, state, started_at, actor}.
    """
    transitions = []
    for h in hist_list:
        if h.get('Field') != 'Status':
            continue
        ts = _parse_dt(h.get('CreatedDate'))
        new_val = h.get('NewValue', '')
        actor = (h.get('CreatedBy') or {}).get('Name') if isinstance(h.get('CreatedBy'), dict) else None
        if ts and new_val:
            transitions.append((ts, new_val, actor))
    transitions.sort(key=lambda t: t[0])

    phase_starts = {}   # phase_name -> datetime
    phase_actors = {}   # phase_name -> actor name
    for ts, status_val, actor in transitions:
        if status_val in _PHASE_ORDER and status_val not in phase_starts:
            phase_starts[status_val] = ts
            if actor:
                phase_actors[status_val] = actor

    def _fmt_utc(dt):
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None

    phases = []
    current_idx = _PHASE_ORDER.index(current_status) if current_status in _PHASE_ORDER else -1

    for i, phase_name in enumerate(_PHASE_ORDER):
        start = phase_starts.get(phase_name)
        actor = phase_actors.get(phase_name)
        base = {'name': phase_name, 'started_at': _fmt_utc(start), 'actor': actor}

        if i < current_idx:
            next_phase = _PHASE_ORDER[i + 1] if i + 1 < len(_PHASE_ORDER) else None
            end = phase_starts.get(next_phase) if next_phase else None
            duration = None
            if start and end:
                duration = round((end - start).total_seconds() / 60)
                if duration < 0 or duration > 1440:
                    duration = None
            phases.append({**base, 'duration_min': duration, 'state': 'done'})
        elif i == current_idx:
            duration = None
            if start:
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                duration = round((now_utc - start).total_seconds() / 60)
                if duration < 0 or duration > 1440:
                    duration = None
            phases.append({**base, 'duration_min': duration, 'state': 'current'})
        else:
            phases.append({**base, 'duration_min': None, 'state': 'future'})

    return phases


# ── Helpers ──────────────────────────────────────────────────────────────────
def _initials(name: str) -> str:
    """'Austin Samit' -> 'AS'."""
    if not name:
        return ''
    parts = name.split()
    return ''.join(p[0].upper() for p in parts if p)[:2]


def _time_in_status(hist_list: list, current_status: str, now_utc: datetime) -> int | None:
    """Minutes since the SA entered its current status."""
    # Walk history in reverse to find the most recent transition to current_status
    status_transitions = [
        h for h in hist_list
        if h.get('Field') == 'Status' and h.get('NewValue') == current_status
    ]
    if not status_transitions:
        return None
    # Use the last transition to this status
    last = status_transitions[-1]
    ts = _parse_dt(last.get('CreatedDate'))
    if not ts:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = round((now_utc - ts).total_seconds() / 60)
    return delta if 0 <= delta < 1440 else None


def _pta_delta(sa: dict, now_utc: datetime) -> int | None:
    """PTA delta in minutes. Negative = ahead, positive = behind.

    For active SAs: delta = elapsed - PTA.
    For completed: delta = ATA - PTA.
    """
    pta_raw = sa.get('ERS_PTA__c')
    if not pta_raw:
        return None
    try:
        pta_min = float(pta_raw)
        if pta_min <= 0 or pta_min > 999:
            return None
    except (TypeError, ValueError):
        return None

    created = _parse_dt(sa.get('CreatedDate'))
    if not created:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    actual_start = _parse_dt(sa.get('ActualStartTime'))
    if actual_start:
        # Completed: ATA - PTA
        if actual_start.tzinfo is None:
            actual_start = actual_start.replace(tzinfo=timezone.utc)
        ata = (actual_start - created).total_seconds() / 60
        return round(ata - pta_min)

    # Active: elapsed - PTA
    elapsed = (now_utc - created).total_seconds() / 60
    return round(elapsed - pta_min)


def _compute_flag(status: str, time_in_status: int | None) -> str | None:
    """Flag SAs that are stuck or aging.

    - 'stuck': Dispatched > 15 min or Accepted > 10 min (driver not moving)
    - 'aging': En Route > 60 min or On Location > 90 min
    """
    if time_in_status is None:
        return None
    if status == 'Dispatched' and time_in_status > 15:
        return 'stuck'
    if status == 'Accepted' and time_in_status > 10:
        return 'stuck'
    if status == 'En Route' and time_in_status > 60:
        return 'aging'
    if status == 'On Location' and time_in_status > 90:
        return 'aging'
    return None


def _primary_human(human_names: list, hist_list: list) -> str | None:
    """Return the human dispatcher who intervened most (by frequency)."""
    if not human_names:
        return None
    if len(human_names) == 1:
        return human_names[0]
    # Count how many resource changes each human made
    counter = Counter()
    for h in hist_list:
        if h.get('Field') != 'ERS_Assigned_Resource__c':
            continue
        new_val = (h.get('NewValue') or '').strip()
        if new_val and _SF_ID.match(new_val):
            continue
        cb = h.get('CreatedBy') or {}
        profile = (cb.get('Profile') or {}).get('Name', '')
        if profile == _HUMAN_PROFILE:
            counter[cb.get('Name', '?')] += 1
    if counter:
        return counter.most_common(1)[0][0]
    return human_names[0]


def _sort_key(entry: dict) -> tuple:
    """Sort watchlist: active flagged first, then reassignment count desc, completed last."""
    status = entry.get('current_status', '')
    is_terminal = status in _TERMINAL_STATUSES
    has_flag = entry.get('flag') is not None
    reassignment_count = entry.get('reassignment_count', 0)

    # Sort tuple: (terminal ASC, no-flag ASC, -reassignment_count)
    # So active+flagged comes first, terminal comes last
    return (is_terminal, not has_flag, -reassignment_count)
