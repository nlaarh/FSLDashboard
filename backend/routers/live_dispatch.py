"""Live Dispatch Board -- real-time driver progress for active Service Appointments."""

from fastapi import APIRouter
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sf_client import sf_query_all, sf_parallel
from utils import _ET, parse_dt as _parse_dt
from sf_batch import batch_soql_parallel
import cache
import logging

router = APIRouter()
log = logging.getLogger('live_dispatch')

# ── Constants ───────────────────────────────────────────────────────────────

CACHE_KEY = 'live_dispatch'
CACHE_TTL = 60  # seconds — real-time board needs fresh data

# Ordered phases for the timeline
_PHASES = ['Dispatched', 'Accepted', 'En Route', 'On Location', 'In Progress', 'Completed']
_PHASE_SET = set(_PHASES)

# Pre-dispatch statuses to skip in timeline
_PRE_DISPATCH = {'None', 'Spotted', 'Scheduled', 'Assigned'}

# Active status categories (not completed/canceled)
_ACTIVE_CATEGORIES = ('None', 'Scheduled', 'Dispatched', 'InProgress', 'CheckedIn')

# Channel mapping from ERS_Driver_Type__c
_CHANNEL_MAP = {
    'Fleet Driver': 'Fleet',
    'On-Platform Contractor Driver': 'On-Platform',
    'Off-Platform Contractor Driver': 'Off-Platform',
}

# Flag thresholds (minutes)
_STUCK_THRESHOLD = 0       # PTA breached (pta_delta > 0)
_LATE_EN_ROUTE_MIN = 30    # En Route > 30 min
_NO_ACK_MIN = 5            # Dispatched > 5 min without Accept
_AGING_MIN = 20            # Any phase > 20 min

# Flag sort priority (lower = higher risk = sorts first)
_FLAG_PRIORITY = {'stuck': 0, 'aging': 1, 'no_ack': 2, 'late': 3}


# ── Endpoint ────────────────────────────────────────────────────────────────

@router.get("/api/live-dispatch")
def api_live_dispatch():
    """Live dispatch board: active SAs with driver progress and phase timeline."""
    cached = cache.get(CACHE_KEY)
    if cached:
        return cached
    # L2 disk
    cached = cache.disk_get(CACHE_KEY, CACHE_TTL)
    if cached:
        cache.put(CACHE_KEY, cached, CACHE_TTL)
        return cached
    try:
        result = _build_live_dispatch()
    except Exception as e:
        # Graceful degradation — serve stale cache if SF fails
        stale = cache.get_stale(CACHE_KEY) or cache.disk_get_stale(CACHE_KEY)
        if stale:
            log.warning(f"SF error: {e}. Serving stale live-dispatch cache.")
            return stale
        log.error(f"SF error: {e}. No cached data available for live-dispatch.")
        raise
    cache.put(CACHE_KEY, result, CACHE_TTL)
    cache.disk_put(CACHE_KEY, result, CACHE_TTL)
    return result


# ── Builder ─────────────────────────────────────────────────────────────────

def _build_live_dispatch() -> dict:
    """Fetch active SAs, drivers, history, and assemble the board payload."""
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = (now_utc - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
    cutoff_1h = (now_utc - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # ── Query 1: Active SAs ─────────────────────────────────────────────────
    def _get_active_sas():
        return sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, StatusCategory,
                   ServiceTerritoryId, ServiceTerritory.Name,
                   WorkType.Name, ERS_PTA__c, ERS_Dispatch_Method__c,
                   CreatedDate, SchedStartTime, ActualStartTime, ActualEndTime,
                   LastModifiedDate, Street, City, Description,
                   Latitude, Longitude
            FROM ServiceAppointment
            WHERE StatusCategory IN {str(tuple(_ACTIVE_CATEGORIES))}
              AND RecordType.Name = 'ERS Service Appointment'
              AND ServiceTerritoryId != null
              AND CreatedDate >= {cutoff_24h}
            ORDER BY CreatedDate ASC
        """)

    # ── Query 4: Completed in last 1h ──────────────────────────────────────
    def _get_completed_1h():
        return sf_query_all(f"""
            SELECT Id
            FROM ServiceAppointment
            WHERE StatusCategory IN ('Completed')
              AND RecordType.Name = 'ERS Service Appointment'
              AND ActualEndTime >= {cutoff_1h}
        """)

    # Phase 1: fetch SAs + completed count in parallel
    phase1 = sf_parallel(active=_get_active_sas, completed_1h=_get_completed_1h)
    active_sas = phase1['active']
    completed_1h_count = len(phase1['completed_1h'])

    if not active_sas:
        return _empty_response(completed_1h_count, now_utc)

    # Collect SA IDs for dependent queries
    sa_ids = [sa['Id'] for sa in active_sas]
    # ── Queries 2+3: AssignedResource + SAHistory (parallelized batch helpers) ─
    all_ar = batch_soql_parallel("""
        SELECT Id, ServiceAppointmentId,
               ServiceResource.Name, ServiceResource.Id,
               ServiceResource.ERS_Tech_ID__c,
               ServiceResource.ERS_Driver_Type__c,
               ServiceResource.LastKnownLatitude,
               ServiceResource.LastKnownLongitude,
               CreatedDate, CreatedBy.Name
        FROM AssignedResource
        WHERE ServiceAppointmentId IN ('{id_list}')
        ORDER BY CreatedDate ASC
    """, sa_ids, chunk_size=200)

    all_history = batch_soql_parallel("""
        SELECT ServiceAppointmentId, Field, OldValue, NewValue, CreatedDate, CreatedBy.Name
        FROM ServiceAppointmentHistory
        WHERE ServiceAppointmentId IN ('{id_list}')
          AND Field = 'Status'
        ORDER BY CreatedDate ASC
    """, sa_ids, chunk_size=200)

    # ── Index data by SA ID ─────────────────────────────────────────────────
    ar_by_sa = defaultdict(list)
    for ar in all_ar:
        ar_by_sa[ar['ServiceAppointmentId']].append(ar)

    history_by_sa = defaultdict(list)
    for h in all_history:
        history_by_sa[h['ServiceAppointmentId']].append(h)

    # ── Build driver rows ───────────────────────────────────────────────────
    drivers = []
    phase_counter = defaultdict(int)
    on_track_count = 0
    aging_count = 0
    stuck_count = 0
    accept_to_onloc_times = []

    for sa in active_sas:
        sa_id = sa['Id']
        status = sa.get('Status') or ''
        status_cat = sa.get('StatusCategory') or ''

        # Skip pre-dispatch statuses (not yet dispatched)
        if status in _PRE_DISPATCH:
            continue

        # Get most recent assigned resource (last = current driver)
        ar_list = ar_by_sa.get(sa_id, [])
        if not ar_list:
            continue  # no driver assigned — skip

        current_ar = ar_list[-1]
        sr = current_ar.get('ServiceResource') or {}
        driver_name = sr.get('Name') or 'Unknown'
        driver_id = sr.get('Id') or ''
        tech_id = sr.get('ERS_Tech_ID__c') or ''
        driver_type = sr.get('ERS_Driver_Type__c') or ''

        # Territory
        territory = (sa.get('ServiceTerritory') or {}).get('Name') or ''
        territory_short = territory.split(' - ')[0].strip() if ' - ' in territory else territory

        # Channel
        channel = _CHANNEL_MAP.get(driver_type, 'Unknown')

        # Driver initials
        initials = _make_initials(driver_name)

        # Phase timeline from history
        history = history_by_sa.get(sa_id, [])
        phases, time_in_status, current_phase = _build_phases(history, status, now_utc)

        # PTA delta
        pta_str = sa.get('ERS_PTA__c')
        pta_delta = _calc_pta_delta(pta_str, now_utc)

        # Flag calculation
        flag = _calc_flag(phases, pta_delta, current_phase, time_in_status)

        # Count phases for summary
        phase_key = _status_to_phase_key(status)
        if phase_key:
            phase_counter[phase_key] += 1

        # KPI tracking
        if flag == 'stuck':
            stuck_count += 1
        elif flag == 'aging':
            aging_count += 1
        elif flag is None:
            on_track_count += 1

        # Accept-to-OnLocation metric
        ato = _calc_accept_to_onloc(phases)
        if ato is not None:
            accept_to_onloc_times.append(ato)

        drivers.append({
            'driver_name': driver_name,
            'driver_initials': initials,
            'driver_id': driver_id,
            'territory': territory,
            'territory_short': territory_short,
            'channel': channel,
            'tech_id': tech_id,
            'sa_number': sa.get('AppointmentNumber') or '',
            'sa_id': sa_id,
            'current_status': status,
            'status_category': status_cat,
            'time_in_status_min': time_in_status,
            'flag': flag,
            'pta_delta_min': pta_delta,
            'phases': phases,
            'work_type': (sa.get('WorkType') or {}).get('Name') or '',
            'address': f"{sa.get('Street') or ''}, {sa.get('City') or ''}".strip(', '),
            'description': sa.get('Description') or '',
            'created_time': sa.get('CreatedDate'),
            'customer_lat': sa.get('Latitude'),
            'customer_lon': sa.get('Longitude'),
            'driver_lat': sr.get('LastKnownLatitude'),
            'driver_lon': sr.get('LastKnownLongitude'),
        })

    # Sort: stuck first, then aging, no_ack, late, then by time_in_status desc
    drivers.sort(key=_driver_sort_key)

    total_active = len(drivers)
    avg_ato = round(sum(accept_to_onloc_times) / len(accept_to_onloc_times)) if accept_to_onloc_times else None

    result = {
        'kpis': {
            'active': total_active,
            'on_track': on_track_count,
            'aging': aging_count,
            'stuck': stuck_count,
            'avg_accept_to_onloc_min': avg_ato,
        },
        'phase_counts': {
            'dispatched': phase_counter.get('dispatched', 0),
            'accepted': phase_counter.get('accepted', 0),
            'en_route': phase_counter.get('en_route', 0),
            'on_location': phase_counter.get('on_location', 0),
            'in_progress': phase_counter.get('in_progress', 0),
            'completed_1h': completed_1h_count,
        },
        'drivers': drivers,
        'last_updated': now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    return result


# ── Helper functions ────────────────────────────────────────────────────────

def _empty_response(completed_1h: int, now_utc: datetime) -> dict:
    """Return empty board when no active SAs exist."""
    return {
        'kpis': {
            'active': 0, 'on_track': 0, 'aging': 0, 'stuck': 0,
            'avg_accept_to_onloc_min': None,
        },
        'phase_counts': {
            'dispatched': 0, 'accepted': 0, 'en_route': 0,
            'on_location': 0, 'in_progress': 0, 'completed_1h': completed_1h,
        },
        'drivers': [],
        'last_updated': now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def _make_initials(name: str) -> str:
    """Extract initials from a name: 'Austin Samit' -> 'AS'."""
    if not name:
        return '??'
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return parts[0][0].upper() if parts else '??'


def _build_phases(history: list, current_status: str, now_utc: datetime) -> tuple:
    """Build the 6-phase timeline from SAHistory status transitions.

    Returns:
        (phases_list, time_in_current_min, current_phase_name)
    """
    # Walk history to find when each phase started, ended, and who triggered it
    phase_starts = {}   # phase_name -> datetime
    phase_ends = {}     # phase_name -> datetime
    phase_actors = {}   # phase_name -> actor name (who triggered the transition)

    for h in history:
        new_val = h.get('NewValue') or ''
        created = _parse_dt(h.get('CreatedDate'))
        if not created or new_val not in _PHASE_SET:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        # This status started at this time
        if new_val not in phase_starts:
            phase_starts[new_val] = created
            # Capture who triggered this status change
            actor = (h.get('CreatedBy') or {}).get('Name') if isinstance(h.get('CreatedBy'), dict) else None
            if actor:
                phase_actors[new_val] = actor

        # The previous status ended at this time
        old_val = h.get('OldValue') or ''
        if old_val in _PHASE_SET and old_val not in phase_ends:
            phase_ends[old_val] = created

    def _fmt_utc(dt):
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None

    # Build the ordered phase list
    phases = []
    current_phase = None
    time_in_current = 0

    for phase_name in _PHASES:
        start = phase_starts.get(phase_name)
        end = phase_ends.get(phase_name)
        actor = phase_actors.get(phase_name)
        base = {'name': phase_name, 'started_at': _fmt_utc(start), 'actor': actor}

        if start and end:
            duration = round((end - start).total_seconds() / 60)
            phases.append({**base, 'duration_min': duration, 'state': 'done'})
        elif start and not end:
            if phase_name == current_status:
                duration = round((now_utc - start).total_seconds() / 60)
                phases.append({**base, 'duration_min': duration, 'state': 'current'})
                current_phase = phase_name
                time_in_current = duration
            else:
                idx = _PHASES.index(phase_name)
                cur_idx = _PHASES.index(current_status) if current_status in _PHASE_SET else -1
                if cur_idx > idx:
                    next_start = None
                    for later in _PHASES[idx + 1:]:
                        if later in phase_starts:
                            next_start = phase_starts[later]
                            break
                    duration = round((next_start - start).total_seconds() / 60) if next_start else 0
                    phases.append({**base, 'duration_min': duration, 'state': 'done'})
                else:
                    duration = round((now_utc - start).total_seconds() / 60)
                    phases.append({**base, 'duration_min': duration, 'state': 'current'})
                    current_phase = phase_name
                    time_in_current = duration
        else:
            phases.append({**base, 'duration_min': None, 'state': 'future'})

    # If current_status is a known phase but wasn't found via history,
    # mark it as current with time from LastModifiedDate fallback
    if current_phase is None and current_status in _PHASE_SET:
        for p in phases:
            if p['name'] == current_status and p['state'] == 'future':
                p['state'] = 'current'
                p['duration_min'] = 0
                current_phase = current_status
                time_in_current = 0
                break

    return phases, time_in_current, current_phase


def _calc_pta_delta(pta_str, now_utc: datetime) -> int | None:
    """Calculate PTA delta in minutes. Negative = ahead, positive = behind."""
    if not pta_str:
        return None
    pta_dt = _parse_dt(pta_str)
    if not pta_dt:
        return None
    if pta_dt.tzinfo is None:
        pta_dt = pta_dt.replace(tzinfo=timezone.utc)
    return round((now_utc - pta_dt).total_seconds() / 60)


def _calc_flag(phases: list, pta_delta: int | None, current_phase: str | None,
               time_in_status: int) -> str | None:
    """Determine the risk flag for a driver row.

    Priority: stuck > late > no_ack > aging
    """
    # Stuck: PTA breached
    if pta_delta is not None and pta_delta > _STUCK_THRESHOLD:
        return 'stuck'

    # Late: En Route > 30 min
    if current_phase == 'En Route' and time_in_status > _LATE_EN_ROUTE_MIN:
        return 'late'

    # No ack: Dispatched > 5 min without Accept
    if current_phase == 'Dispatched' and time_in_status > _NO_ACK_MIN:
        return 'no_ack'

    # Aging: any completed or current phase > 20 min
    for p in phases:
        if p['state'] in ('done', 'current') and p['duration_min'] is not None:
            if p['duration_min'] > _AGING_MIN:
                return 'aging'

    return None


def _calc_accept_to_onloc(phases: list) -> int | None:
    """Sum minutes from Accepted through On Location (inclusive) for completed phases."""
    total = 0
    counting = False
    for p in phases:
        if p['name'] == 'Accepted':
            counting = True
        if counting and p['duration_min'] is not None and p['state'] in ('done', 'current'):
            total += p['duration_min']
        if p['name'] == 'On Location':
            break
    return total if counting and total > 0 else None


def _status_to_phase_key(status: str) -> str | None:
    """Map SA Status to phase_counts key."""
    mapping = {
        'Dispatched': 'dispatched',
        'Accepted': 'accepted',
        'En Route': 'en_route',
        'On Location': 'on_location',
        'In Progress': 'in_progress',
    }
    return mapping.get(status)


def _driver_sort_key(driver: dict) -> tuple:
    """Sort drivers by risk: stuck first, then aging, no_ack, late, then time desc."""
    flag = driver.get('flag')
    priority = _FLAG_PRIORITY.get(flag, 99)
    # Negate time_in_status for descending sort within same flag group
    time_desc = -(driver.get('time_in_status_min') or 0)
    return (priority, time_desc)
