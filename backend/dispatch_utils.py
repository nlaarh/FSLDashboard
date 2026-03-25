"""dispatch_utils.py — Shared dispatch analysis utilities.

Use these everywhere driver GPS positions or SA history are needed so the
logic is identical across the map, the Closest Available Driver metric, and
any future feature.

  GPS:
    fetch_gps_history()      — bulk-fetch ServiceResourceHistory for a time window
    gps_at_time()            — point-in-time position lookup (no SF call)

  Truck login (on-shift gate):
    build_truck_login_hist() — parse AssetHistory ERS_Driver__c rows into a lookup dict
    is_on_truck()            — check if a driver was logged into a truck at time T

  Assignment events:
    parse_assign_events()    — process raw SAHistory rows into ordered events
    classify_dispatch()      — determine auto vs manual per SA from parsed events

  SA timeline:
    fetch_sa_timeline()      — full lifecycle: Received → Assigned → On Location

  Assign-step snapshots:
    build_assign_steps()     — per-assignment snapshot of all on-truck driver positions
"""

import re
import math
from datetime import timedelta
from collections import defaultdict

from utils import parse_dt as _parse_dt, to_eastern as _to_eastern, haversine
from sf_client import sf_query_all, sf_parallel

# ── Constants ─────────────────────────────────────────────────────────────────

# Matches both 15- and 18-char Salesforce record IDs
_SF_ID_RE = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')

# Integration/system accounts that are NOT human dispatchers even if their
# profile says Membership User
_SYSTEM_USERS = frozenset({
    'IT System User',
    'Mulesoft Integration',
    'Replicant Integration User',
    'Platform Integration User',
})

_STATUS_LABEL = {
    'Received':                          'Received',
    'Spotted':                           'Spotted',
    'Assigned':                          'Assigned',
    'Dispatched':                        'Dispatched',
    'Accepted':                          'En Route',
    'En Route':                          'En Route',
    'On Location':                       'On Location',
    'Completed':                         'Completed',
    'Canceled':                          'Canceled',
    'No-Show':                           'No-Show',
    'Unable to Complete':                'Unable to Complete',
    'Cancel Call - Service Not En Route': 'Canceled',
    'Cancel Call - Service En Route':    'Canceled',
}


# ── Truck login utilities ─────────────────────────────────────────────────────

def build_truck_login_hist(asset_history_rows: list) -> dict:
    """Parse AssetHistory ERS_Driver__c rows into a per-driver event list.

    Each row from AssetHistory WHERE Field = 'ERS_Driver__c' is either:
      Login:  OldValue=null, NewValue starts with '0Hn' (SR Id)
      Logout: OldValue starts with '0Hn', NewValue=null

    Returns:
        {driver_sr_id: [(datetime, 'login'|'logout'), ...]} sorted ascending.
        Use with is_on_truck() to gate by actual shift status.
    """
    hist: dict = defaultdict(list)
    for row in asset_history_rows:
        new_val = (row.get('NewValue') or '').strip()
        old_val = (row.get('OldValue') or '').strip()
        ts = _parse_dt(row.get('CreatedDate'))
        if not ts:
            continue
        if new_val.startswith('0Hn') and not old_val:
            hist[new_val].append((ts, 'login'))
        elif old_val.startswith('0Hn') and not new_val:
            hist[old_val].append((ts, 'logout'))
    for d_id in hist:
        hist[d_id].sort(key=lambda x: x[0])
    return dict(hist)


def is_on_truck(driver_id: str, ts, truck_login_hist: dict) -> bool:
    """Return True if the driver was logged into a truck at time ts.

    Finds the most recent AssetHistory ERS_Driver__c event for this driver
    at or before ts.  If it's a login with no subsequent logout before ts,
    the driver was on-truck.  If no record exists, returns False.
    """
    if ts is None:
        return False
    events = truck_login_hist.get(driver_id, [])
    if not events:
        return False
    last_event = None
    for ev_ts, ev_type in events:
        if ev_ts <= ts:
            last_event = ev_type
        else:
            break
    return last_event == 'login'


# ── GPS utilities ─────────────────────────────────────────────────────────────

def fetch_gps_history(driver_ids: list, start_iso: str, end_iso: str) -> tuple:
    """Bulk-fetch GPS history for a set of drivers over a time window.

    Queries ServiceResourceHistory for LastKnownLatitude and LastKnownLongitude
    in parallel, batching driver IDs in groups of 200 to respect SOQL limits.

    Args:
        driver_ids: ServiceResource IDs to fetch
        start_iso:  UTC ISO-8601 string, e.g. '2026-03-17T04:00:00Z'
        end_iso:    UTC ISO-8601 string

    Returns:
        (lat_hist, lon_hist) — each is {driver_id: [(datetime, float), ...]}
        sorted ascending by timestamp.  Drivers with no history are absent.
    """
    lat_hist: dict = defaultdict(list)
    lon_hist: dict = defaultdict(list)

    if not driver_ids:
        return lat_hist, lon_hist

    for i in range(0, len(driver_ids), 200):
        batch = driver_ids[i:i + 200]
        id_list = ','.join(f"'{d}'" for d in batch)

        hist = sf_parallel(
            lat=lambda il=id_list: sf_query_all(f"""
                SELECT ServiceResourceId, NewValue, CreatedDate
                FROM ServiceResourceHistory
                WHERE Field = 'LastKnownLatitude'
                  AND ServiceResourceId IN ({il})
                  AND CreatedDate >= {start_iso}
                  AND CreatedDate <= {end_iso}
                ORDER BY CreatedDate ASC
            """),
            lon=lambda il=id_list: sf_query_all(f"""
                SELECT ServiceResourceId, NewValue, CreatedDate
                FROM ServiceResourceHistory
                WHERE Field = 'LastKnownLongitude'
                  AND ServiceResourceId IN ({il})
                  AND CreatedDate >= {start_iso}
                  AND CreatedDate <= {end_iso}
                ORDER BY CreatedDate ASC
            """),
        )

        for row in hist['lat']:
            d_id = row.get('ServiceResourceId')
            ts = _parse_dt(row.get('CreatedDate'))
            if not d_id or not ts:
                continue
            try:
                lat_hist[d_id].append((ts, float(row['NewValue'])))
            except (TypeError, ValueError):
                pass

        for row in hist['lon']:
            d_id = row.get('ServiceResourceId')
            ts = _parse_dt(row.get('CreatedDate'))
            if not d_id or not ts:
                continue
            try:
                lon_hist[d_id].append((ts, float(row['NewValue'])))
            except (TypeError, ValueError):
                pass

    # Ensure ascending order (ORDER BY handles single-batch; guards multi-batch merges)
    for d_id in lat_hist:
        lat_hist[d_id].sort(key=lambda x: x[0])
    for d_id in lon_hist:
        lon_hist[d_id].sort(key=lambda x: x[0])

    return lat_hist, lon_hist


def gps_at_time(driver_id: str, ts, lat_hist: dict, lon_hist: dict,
                window_minutes: int = 5) -> tuple:
    """Return (lat, lon) for a driver at or just before ts + window_minutes.

    Finds the most recent GPS record in the history that falls within the
    allowed window.  Returns (None, None) when the driver has no record in
    range — meaning they were not on Track at that moment.

    Args:
        driver_id:      ServiceResource ID
        ts:             datetime of the dispatch event (timezone-aware or naive)
        lat_hist:       output of fetch_gps_history()
        lon_hist:       output of fetch_gps_history()
        window_minutes: allow GPS records up to this many minutes *after* ts
                        to account for slight clock skew in the Track app

    Returns:
        (lat, lon) as floats, or (None, None)
    """
    if ts is None:
        return None, None

    cutoff = ts + timedelta(minutes=window_minutes)

    lat = None
    for rec_ts, val in reversed(lat_hist.get(driver_id, [])):
        if rec_ts <= cutoff:
            lat = val
            break

    lon = None
    for rec_ts, val in reversed(lon_hist.get(driver_id, [])):
        if rec_ts <= cutoff:
            lon = val
            break

    return lat, lon


# ── Assignment event utilities ────────────────────────────────────────────────

def parse_assign_events(assign_hist_rows: list, sa_id_set=None) -> dict:
    """Process raw SAHistory rows (Field=ERS_Assigned_Resource__c) into ordered events.

    SF writes two rows per assignment: one with the display name and one with
    the raw Salesforce ID.  This function keeps only display-name rows so each
    assignment appears exactly once.

    Human dispatch detection: CreatedBy must be a Membership User profile AND
    not a known system integration account.

    Args:
        assign_hist_rows: raw ServiceAppointmentHistory rows, ORDER BY CreatedDate ASC
        sa_id_set:        optional set of SA IDs to filter to (None = accept all)

    Returns:
        {sa_id: [{'time', 'driver', 'ts', 'by_name', 'is_human',
                  'is_reassignment'}, ...]}
        Each list is chronologically ordered; is_reassignment=True for index > 0.
    """
    raw: dict = defaultdict(list)

    for r in assign_hist_rows:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id:
            continue
        if sa_id_set is not None and sa_id not in sa_id_set:
            continue

        new_val = (r.get('NewValue') or '').strip()
        # Skip blank values and raw Salesforce ID rows
        if not new_val or _SF_ID_RE.match(new_val):
            continue

        ts = _parse_dt(r.get('CreatedDate'))
        et_ts = _to_eastern(r.get('CreatedDate'))
        cb = r.get('CreatedBy') or {}
        by_name = cb.get('Name', '')
        by_profile = (cb.get('Profile') or {}).get('Name', '')
        is_human = by_name not in _SYSTEM_USERS and by_profile == 'Membership User'

        raw[sa_id].append({
            'time': et_ts.strftime('%b %d, %I:%M %p') if et_ts else '?',
            'driver': new_val,
            'ts': ts,
            'by_name': by_name,
            'is_human': is_human,
        })

    result = {}
    for sa_id, evs in raw.items():
        for i, ev in enumerate(evs):
            ev['is_reassignment'] = i > 0
        result[sa_id] = evs

    return result


def classify_dispatch(assign_events: dict) -> dict:
    """Determine auto vs manual dispatch for each SA.

    Manual = more than one assignment event AND at least one was made by a
    human dispatcher (Membership User profile).  A single assignment by a
    human still counts as auto — the system proposed the driver; the human
    confirmed.

    Args:
        assign_events: output of parse_assign_events()

    Returns:
        {sa_id: {'is_manual': bool, 'dispatcher_name': str}}
    """
    result = {}
    for sa_id, evs in assign_events.items():
        human_ev = next((e for e in evs if e['is_human']), None)
        is_manual = len(evs) > 1 and human_ev is not None
        result[sa_id] = {
            'is_manual': is_manual,
            'dispatcher_name': human_ev['by_name'] if human_ev else 'System',
        }
    return result


# ── SA timeline utilities ─────────────────────────────────────────────────────

def fetch_sa_timeline(sa_ids: list) -> dict:
    """Fetch the full SA lifecycle from Received to Completed for a list of SAs.

    Queries both Status and ERS_Assigned_Resource__c history, merges them into
    a single ordered timeline per SA.  Filters out raw SF-ID rows for
    assignment events.  Marks Reassigned vs Assigned based on prior events.

    Args:
        sa_ids: list of ServiceAppointment IDs

    Returns:
        {sa_id: [{'event', 'ts', 'time', 'driver'?, 'by_name', 'is_human'}, ...]}
        sorted ascending by ts.
    """
    if not sa_ids:
        return {}

    timeline: dict = defaultdict(list)

    for i in range(0, len(sa_ids), 200):
        batch = sa_ids[i:i + 200]
        id_list = ','.join(f"'{s}'" for s in batch)

        rows = sf_query_all(f"""
            SELECT ServiceAppointmentId, Field, NewValue, CreatedDate,
                   CreatedBy.Name, CreatedBy.Profile.Name
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointmentId IN ({id_list})
              AND Field IN ('Status', 'ERS_Assigned_Resource__c')
            ORDER BY CreatedDate ASC
        """)

        for r in rows:
            sa_id = r.get('ServiceAppointmentId')
            if not sa_id:
                continue
            field = r.get('Field', '')
            new_val = (r.get('NewValue') or '').strip()
            if not new_val:
                continue

            ts = _parse_dt(r.get('CreatedDate'))
            et_ts = _to_eastern(r.get('CreatedDate'))
            cb = r.get('CreatedBy') or {}
            by_name = cb.get('Name', '')
            by_profile = (cb.get('Profile') or {}).get('Name', '')
            is_human = by_name not in _SYSTEM_USERS and by_profile == 'Membership User'
            time_str = et_ts.strftime('%b %d, %I:%M %p') if et_ts else '?'

            if field == 'Status':
                label = _STATUS_LABEL.get(new_val, new_val)
                timeline[sa_id].append({
                    'event': label,
                    'ts': ts,
                    'time': time_str,
                    'by_name': by_name,
                    'is_human': is_human,
                })

            elif field == 'ERS_Assigned_Resource__c':
                if _SF_ID_RE.match(new_val):
                    continue  # skip raw SF ID rows

                prior_assigns = [e for e in timeline[sa_id]
                                 if e['event'] in ('Assigned', 'Reassigned')]
                label = 'Reassigned' if prior_assigns else 'Assigned'
                timeline[sa_id].append({
                    'event': label,
                    'driver': new_val,
                    'ts': ts,
                    'time': time_str,
                    'by_name': by_name,
                    'is_human': is_human,
                })

    return {
        sa_id: sorted(evs, key=lambda e: e['ts'] or 0)
        for sa_id, evs in timeline.items()
    }


# ── Assign-step driver snapshots ──────────────────────────────────────────────

def build_assign_steps(events: list, members: list, driver_skills: dict,
                       required_skills: set, sa_lat: float, sa_lon: float,
                       lat_hist: dict, lon_hist: dict,
                       truck_login_hist: dict | None = None) -> list:
    """For each assignment event, snapshot where on-truck Fleet drivers were.

    A driver is included only if they pass all three gates at time T:
      1. On truck  — logged into a truck via FSL Track (AssetHistory gate).
                     If truck_login_hist is None, this gate is skipped (GPS-only mode).
      2. Has skills — has at least one skill entry (excludes supervisors/admins).
      3. Has GPS   — has a GPS record near time T (provides map position).

    The actually-assigned driver always passes gate 1 (in case their login event
    is outside the lookback window).

    Args:
        events:            output of parse_assign_events()[sa_id]
        members:           ServiceTerritoryMember rows for the territory
        driver_skills:     {driver_id: set of skill MasterLabels}
        required_skills:   skills required by the SA's work type (empty set = any)
        sa_lat, sa_lon:    SA member location
        lat_hist:          output of fetch_gps_history()
        lon_hist:          output of fetch_gps_history()
        truck_login_hist:  output of build_truck_login_hist(); None = skip gate
    Returns:
        list of step dicts — one per assignment event — each containing:
          'time', 'driver', 'is_reassignment', 'by_name', 'is_human',
          'step_drivers' (list sorted by distance asc, each with
           'driver_id', 'name', 'lat', 'lon', 'distance', 'has_skills',
           'is_assigned', 'is_closest', 'assigned_closest')
    """
    steps = []

    for ev in events:
        step_ts = ev.get('ts')
        if not step_ts:
            continue

        step_drivers = []
        for member in members:
            d_id = member.get('ServiceResourceId')
            if not d_id:
                continue
            sr_info = member.get('ServiceResource') or {}
            d_name = sr_info.get('Name', '?')

            is_step_assigned = d_name == ev.get('driver', '')

            d_skills = driver_skills.get(d_id, set())
            if not d_skills and not is_step_assigned:
                continue  # no skills = supervisor/admin, exclude (bypass for assigned driver)

            # Gate 1: on-truck check.
            # Bypass for the step's assigned driver (in case their login is outside
            # the lookback window — they were clearly on truck if they were dispatched).
            if truck_login_hist is not None and not is_step_assigned:
                if not is_on_truck(d_id, step_ts, truck_login_hist):
                    continue  # not logged into a truck at this moment

            has_skills = required_skills.issubset(d_skills) if required_skills else True
            d_lat, d_lon = gps_at_time(d_id, step_ts, lat_hist, lon_hist)
            if d_lat is None or d_lon is None:
                if is_step_assigned:
                    # Assigned driver with no GPS — include with no position/distance
                    step_drivers.append({
                        'driver_id': d_id,
                        'name': d_name,
                        'lat': None,
                        'lon': None,
                        'distance': None,
                        'no_gps': True,
                        'has_skills': has_skills,
                        'is_assigned': True,
                        'is_closest': False,
                    })
                continue

            dist = round(haversine(d_lat, d_lon, sa_lat, sa_lon), 1)
            step_drivers.append({
                'driver_id': d_id,
                'name': d_name,
                'lat': d_lat,
                'lon': d_lon,
                'distance': dist,
                'no_gps': False,
                'has_skills': has_skills,
                'is_assigned': d_name == ev['driver'],
                'is_closest': False,
            })

        # Mark closest among skill-eligible drivers (must have GPS distance)
        eligible = [d for d in step_drivers if d['has_skills'] and d.get('distance') is not None]
        if eligible:
            closest = min(eligible, key=lambda d: d['distance'])
            for d in step_drivers:
                d['is_closest'] = d['driver_id'] == closest['driver_id']

        # Convenience flag for map rendering (gold icon when assigned == closest)
        for d in step_drivers:
            d['assigned_closest'] = d['is_assigned'] and d['is_closest']

        step_drivers.sort(key=lambda d: d['distance'] if d['distance'] is not None else 9999)

        steps.append({
            'time': ev['time'],
            'ts': ev.get('ts'),  # raw datetime for calculations
            'driver': ev['driver'],
            'is_reassignment': ev['is_reassignment'],
            'by_name': ev.get('by_name', ''),
            'is_human': ev.get('is_human', False),
            'reason': ev.get('reason'),
            'step_drivers': step_drivers,
        })

    return steps
