"""SA History Report endpoint.

GET /api/sa/{number}/report

Optimized for minimum SF round trips:
  Round trip 1  — SA lookup
  Round trip 2  — SAHistory + AssignedResource + territory members  (parallel)
  Round trip 2b — cascade fallback territory (only when SA cascaded to Towbook)
  Round trip 3  — skills + GPS lat + GPS lon + AssetHistory truck logins  (parallel)

Total: 3 round trips for a normal SA, 4-5 if a cascade fallback is needed.
Result is cached for 2 minutes.
"""

from datetime import timedelta
from collections import defaultdict as _dd
from fastapi import APIRouter, HTTPException

import cache
from sf_client import sf_query_all, sf_parallel, sanitize_soql
from utils import parse_dt as _parse_dt, to_eastern as _to_eastern
from dispatch_utils import (
    parse_assign_events, build_assign_steps,
    build_truck_login_hist,
    _SF_ID_RE, _STATUS_LABEL, _SYSTEM_USERS,
)
from routers.misc import _SKILL_MAP

router = APIRouter()

_SA_FIELDS = """
    SELECT Id, AppointmentNumber, Status, CreatedDate,
           ActualStartTime, ActualEndTime,
           Latitude, Longitude, Street, City, State, PostalCode,
           WorkType.Name, ServiceTerritoryId, ServiceTerritory.Name,
           Off_Platform_Truck_Id__c, ERS_PTA__c,
           ERS_Dispatch_Method__c,
           ERS_Dispatched_Geolocation__Latitude__s,
           ERS_Dispatched_Geolocation__Longitude__s
    FROM ServiceAppointment
    WHERE AppointmentNumber = '{number}'
    LIMIT 1
"""


# ── Garage type classification ────────────────────────────────────────────────

def _garage_type(territory: str, dispatch_method: str) -> str:
    """Classify garage as Fleet / On-Platform Contractor / Towbook.

    Rules:
      Towbook           — dispatch_method == 'Towbook'
      Fleet             — territory name contains 'FLEET' (WNY Fleet territories)
      On-Platform Contractor — everything else with Field Services dispatch
    """
    if dispatch_method == 'Towbook':
        return 'Towbook'
    if 'FLEET' in (territory or '').upper():
        return 'Fleet'
    return 'On-Platform Contractor'


# ── SA summary (frontend-ready shape) ────────────────────────────────────────

def _build_sa_summary(sa: dict) -> dict:
    et       = _to_eastern(sa.get('CreatedDate'))
    start_et = _to_eastern(sa.get('ActualStartTime'))
    end_et   = _to_eastern(sa.get('ActualEndTime'))
    cd, ast  = _parse_dt(sa.get('CreatedDate')), _parse_dt(sa.get('ActualStartTime'))
    response_min = None
    if cd and ast:
        diff = (ast - cd).total_seconds() / 60
        if 0 < diff < 1440:
            response_min = round(diff)
    return {
        'id':             sa['Id'],
        'number':         sa.get('AppointmentNumber'),
        'status':         sa.get('Status'),
        'work_type':      (sa.get('WorkType') or {}).get('Name', '?'),
        'address':        f"{sa.get('Street') or ''} {sa.get('City') or ''} {sa.get('State') or ''}".strip(),
        'zip':            sa.get('PostalCode') or '',
        'lat':            sa.get('Latitude'),
        'lon':            sa.get('Longitude'),
        'territory':      (sa.get('ServiceTerritory') or {}).get('Name', '?'),
        'territory_id':   sa.get('ServiceTerritoryId'),
        'truck_id':       sa.get('Off_Platform_Truck_Id__c') or '',
        'pta':            sa.get('ERS_PTA__c'),
        'created':        et.strftime('%b %d, %I:%M %p') if et else '?',
        '_created_iso':   sa.get('CreatedDate'),  # raw ISO for calculations
        'started':        start_et.strftime('%b %d, %I:%M %p') if start_et else None,
        'completed':      end_et.strftime('%b %d, %I:%M %p') if end_et else None,
        'response_min':   response_min,
        'dispatch_method': sa.get('ERS_Dispatch_Method__c') or '',
        'dispatched_lat': sa.get('ERS_Dispatched_Geolocation__Latitude__s'),
        'dispatched_lon': sa.get('ERS_Dispatched_Geolocation__Longitude__s'),
        'garage_type':    _garage_type(
                              (sa.get('ServiceTerritory') or {}).get('Name', ''),
                              sa.get('ERS_Dispatch_Method__c') or '',
                          ),
    }


# ── Timeline builder (uses pre-fetched rows — avoids a dedicated SF call) ────

def _build_timeline(hist_rows: list, sa_id: str) -> list:
    """Build ordered timeline from SAHistory rows (Field=Status or ERS_Assigned_Resource__c)."""
    tl: list = []
    for r in hist_rows:
        if r.get('ServiceAppointmentId') != sa_id:
            continue
        field   = r.get('Field', '')
        new_val = str(r.get('NewValue') or '').strip()
        if not new_val:
            continue
        ts     = _parse_dt(r.get('CreatedDate'))
        et_ts  = _to_eastern(r.get('CreatedDate'))
        cb     = r.get('CreatedBy') or {}
        by_name    = cb.get('Name', '')
        by_profile = (cb.get('Profile') or {}).get('Name', '')
        is_human   = by_name not in _SYSTEM_USERS and by_profile == 'Membership User'
        time_str   = et_ts.strftime('%b %d, %I:%M %p') if et_ts else '?'

        if field == 'Status':
            tl.append({
                'event': _STATUS_LABEL.get(new_val, new_val),
                'ts': ts, 'time': time_str,
                'by_name': by_name, 'is_human': is_human,
            })
        elif field == 'ERS_Assigned_Resource__c':
            if _SF_ID_RE.match(new_val):
                continue
            prior_drivers = [e for e in tl if 'driver' in e]
            tl.append({
                'event':  'Reassigned' if prior_drivers else 'Assigned',
                'driver': new_val,
                'ts': ts, 'time': time_str,
                'by_name': by_name, 'is_human': is_human,
            })

    sorted_tl = sorted(tl, key=lambda e: e['ts'] or 0)

    # Remove bare Status='Assigned'/'Reassigned' entries that duplicate an
    # ERS_Assigned_Resource__c event at the same timestamp (within 60 sec).
    # SF writes both rows when a driver is assigned; only the one with 'driver'
    # key is useful. A bare 'Assigned' is also suppressed when a 'Reassigned'
    # with a driver exists at the same time (SF writes 'Assigned' status even
    # on reassignments).
    driver_ts_list = [e['ts'] for e in sorted_tl if 'driver' in e and e['ts'] is not None]
    def _is_dupe_status(e):
        if 'driver' in e or e['event'] not in ('Assigned', 'Reassigned'):
            return False
        if e['ts'] is None:
            return False
        return any(abs((e['ts'] - dt).total_seconds()) <= 60 for dt in driver_ts_list)

    filtered = [e for e in sorted_tl if not _is_dupe_status(e)]

    # Remove back-to-back identical status events (e.g. two "En Route" within 5 min)
    deduped = []
    for e in filtered:
        if deduped and e['event'] == deduped[-1]['event'] and 'driver' not in e and 'driver' not in deduped[-1]:
            if e.get('ts') and deduped[-1].get('ts') and abs((e['ts'] - deduped[-1]['ts']).total_seconds()) < 300:
                continue  # skip duplicate
        deduped.append(e)
    return deduped


# ── Narrative ─────────────────────────────────────────────────────────────────

def _who_phrase(by_name: str) -> str:
    low = (by_name or '').lower()
    if not by_name or low in ('mulesoft integration', 'automated process',
                               'it system user', 'system', 'replicant integration user',
                               'platform integration user'):
        return 'by auto-dispatch'
    return f'by dispatcher {by_name}'


def _build_narrative(sa_summary: dict, timeline: list, assign_steps: list) -> list[str]:
    lines: list[str] = []
    wt        = sa_summary.get('work_type', '?')
    terr      = sa_summary.get('territory', '?')
    num       = sa_summary.get('number', '?')
    gtype     = sa_summary.get('garage_type', '')
    is_towbook = sa_summary.get('dispatch_method') == 'Towbook'

    # Garage label: "421 - ACTION TOWING [On-Platform Contractor]"
    garage_label = f"{terr} [{gtype}]" if gtype else terr

    created_time = sa_summary.get('created', '?')
    received = next((e for e in timeline if e['event'] in ('Received', 'Spotted')), None)
    lines.append(
        f"{num} — {wt} call created at {created_time}, dispatched to {garage_label}."
    )

    first_assign = next((e for e in timeline if e['event'] == 'Assigned' and 'driver' in e), None)
    if first_assign:
        lines.append(
            f"First assigned to {first_assign['driver']} ({garage_label}) "
            f"at {first_assign['time']} {_who_phrase(first_assign.get('by_name', ''))}."
        )

    for i, step in enumerate(assign_steps):
        drivers  = step.get('step_drivers', [])
        assigned = next((d for d in drivers if d['is_assigned']), None)
        closest  = next((d for d in drivers if d['is_closest']), None)
        prefix   = 'At dispatch' if i == 0 else 'At reassignment'
        if assigned and not assigned.get('no_gps'):
            dist_str = f"{assigned['distance']} mi" if assigned.get('distance') is not None else 'unknown distance'
            if assigned.get('is_closest'):
                lines.append(f"{prefix}, {assigned['name']} ({garage_label}) was {dist_str} away — closest driver with matching skills. ✓ Optimal.")
            elif closest:
                lines.append(f"{prefix}, {assigned['name']} ({garage_label}) was {dist_str} away — not closest. {closest['name']} was only {closest['distance']} mi away.")
            else:
                lines.append(f"{prefix}, {assigned['name']} ({garage_label}) was {dist_str} away.")
        elif assigned and assigned.get('no_gps'):
            lines.append(f"{prefix}, {assigned['name']} ({garage_label}) was assigned — no GPS location at dispatch time.")
        if step.get('is_human'):
            action = 'reassigned' if step.get('is_reassignment') else 'assigned'
            lines.append(f"Dispatcher {step['by_name']} manually {action} this call.")
        eligible = sum(1 for d in drivers if d.get('has_skills'))
        if eligible > 1:
            lines.append(f"{eligible} drivers logged into trucks with matching skills were on Track at this moment.")

    for r in (e for e in timeline if e['event'] == 'Reassigned' and 'driver' in e):
        reason_str = f" Reason: {r['reason']}." if r.get('reason') else ''
        lines.append(
            f"Reassigned to {r['driver']} ({garage_label}) "
            f"at {r['time']} {_who_phrase(r.get('by_name', ''))}.{reason_str}"
        )

    on_loc = next((e for e in timeline if e['event'] == 'On Location'), None)
    if on_loc:
        lines.append(f"Driver arrived on location at {on_loc['time']}.")

    resp = sa_summary.get('response_min')
    if resp:
        pta = sa_summary.get('pta')
        if pta and 0 < pta < 999:
            diff = resp - pta
            lines.append(f"Response time: {resp} min. PTA {pta} min — {'on time ✓' if diff <= 0 else f'{diff} min late ✗'}.")
        else:
            lines.append(f"Response time: {resp} min.")

    if is_towbook and not assign_steps:
        lines.append(f"Dispatched via Towbook ({terr}) — off-platform contractor. Driver location not tracked in FSL.")

    end = next((e for e in timeline if e['event'] in ('Completed', 'Canceled')), None)
    if end:
        lines.append(f"Call {end['event'].lower()} at {end['time']}.")

    return lines


def _build_reassignment_impact(sa_summary: dict, timeline: list, assign_steps: list, hist_rows: list) -> dict | None:
    """Calculate the impact of reassignment on member wait time.

    Returns None if no reassignment happened. Otherwise returns:
    {
        first_driver, first_driver_time, first_driver_sched_start,
        final_driver, on_location_time,
        pta_minutes, actual_ata_minutes,
        reassignment_count, time_lost_minutes,
        verdict — plain English assessment
    }
    """
    if len(assign_steps) < 2:
        return None  # No reassignment

    created_dt = _parse_dt(sa_summary.get('_created_iso'))
    if not created_dt:
        return None

    # PTA = the promise made to the member at creation.
    # Mulesoft sets a default (90), then Apex recalculates to the garage-specific
    # value (e.g., 60). Both happen at the same timestamp, and SOQL ordering is
    # unreliable within the same second. The SMALLEST PTA within the creation
    # window is the garage-specific Apex calculation — that's the real promise.
    # If PTA was later changed by Towbook (e.g., 60→120), we ignore that —
    # the member was told the original number.
    pta_at_creation = []
    pta_cutoff_ts = created_dt.timestamp() + 5 if created_dt else 0
    for h in hist_rows:
        if h.get('Field') != 'ERS_PTA__c' or h.get('NewValue') is None:
            continue
        h_ts = _parse_dt(h.get('CreatedDate'))
        if h_ts and h_ts.timestamp() <= pta_cutoff_ts:
            try:
                v = float(h['NewValue'])
                if 0 < v < 999:
                    pta_at_creation.append(v)
            except (TypeError, ValueError):
                pass
    # Smallest = garage-specific Apex calculation (most specific promise)
    pta = min(pta_at_creation) if pta_at_creation else None
    # Fallback to current SA value
    if pta is None:
        pta = sa_summary.get('pta')
        if pta and (pta <= 0 or pta >= 999):
            pta = None

    # First assignment
    first_step = assign_steps[0]
    first_driver = first_step.get('driver', '?')
    first_time = first_step.get('time', '?')

    # Estimate first driver's ETA from distance (if available in assign_steps)
    first_driver_distance = None
    first_step_drivers = first_step.get('step_drivers', [])
    assigned_in_first = next((d for d in first_step_drivers if d.get('is_assigned')), None)
    if assigned_in_first and assigned_in_first.get('distance') is not None:
        first_driver_distance = assigned_in_first['distance']

    # ETA = distance / 25 mph * 60 (convert to minutes) + dispatch overhead (~5 min)
    first_sched_start = None  # not used directly

    # On Location time ONLY — not Completed (which includes service time)
    on_loc_event = next((e for e in timeline if e['event'] == 'On Location'), None)
    on_loc_dt = on_loc_event.get('ts') if on_loc_event else None

    # Final driver
    last_step = assign_steps[-1]
    final_driver = last_step.get('driver', '?')

    # Calculate time lost: gap between driver REMOVAL (back to Spotted) and next ASSIGNMENT
    # Skip the initial Spotted event — only count Spotted events that happen AFTER a driver was assigned
    time_lost = 0.0
    saw_assignment = False
    removal_ts = None
    for ev in timeline:
        if ev['event'] in ('Reassigned',) and not saw_assignment:
            saw_assignment = True  # first assignment
            continue
        if saw_assignment and ev['event'] == 'Spotted' and ev.get('ts'):
            removal_ts = ev['ts']  # driver was removed
        if removal_ts and ev['event'] == 'Reassigned' and ev.get('ts'):
            gap = (ev['ts'] - removal_ts).total_seconds() / 60
            if gap > 1:
                time_lost += gap
            removal_ts = None

    # Actual ATA
    actual_ata = None
    if on_loc_dt and created_dt:
        actual_ata = round((on_loc_dt - created_dt).total_seconds() / 60)

    # First driver's estimated ATA: use distance if available, else PTA as proxy
    first_driver_eta = None
    if first_driver_distance is not None:
        first_driver_eta = round((first_driver_distance / 25) * 60 + 5)
    elif pta:
        first_driver_eta = round(pta)  # PTA was the promised time for the first driver

    # PTA vs Arrival — the only thing that matters
    pta_delta = round(actual_ata - pta) if actual_ata and pta else None

    return {
        'first_driver': first_driver,
        'first_driver_time': first_time,
        'final_driver': final_driver,
        'on_location_time': on_loc_event.get('time') if on_loc_event else None,
        'pta_minutes': round(pta) if pta else None,
        'actual_ata_minutes': actual_ata,
        'pta_delta_minutes': pta_delta,  # positive = late, negative = early
        'reassignment_count': len(assign_steps) - 1,
        'time_lost_minutes': round(time_lost) if time_lost > 0 else 0,
    }


def _build_phases(timeline: list, sa_summary: dict) -> list:
    """Build phase durations from the timeline for a visual bar.

    Each phase = {label, minutes, color, start_time, end_time}
    Consecutive duplicate events are collapsed.
    """
    # Define the lifecycle phases we care about, in order
    _PHASE_ORDER = [
        'Spotted', 'Received', 'Assigned', 'Reassigned',
        'Dispatched', 'En Route', 'On Location', 'Completed', 'Canceled',
    ]
    _PHASE_COLORS = {
        'Spotted':      '#f59e0b',  # amber — waiting in queue
        'Received':     '#f59e0b',
        'Assigned':     '#3b82f6',  # blue — assigned to driver
        'Reassigned':   '#f97316',  # orange — reassigned
        'Dispatched':   '#6366f1',  # indigo — dispatched
        'En Route':     '#8b5cf6',  # violet — driving
        'On Location':  '#22c55e',  # green — on scene
    }
    _PHASE_LABELS = {
        'Spotted':      'In Queue',
        'Received':     'In Queue',
        'Assigned':     'Assigned',
        'Reassigned':   'Reassigned',
        'Dispatched':   'Dispatched',
        'En Route':     'En Route',
        'On Location':  'On Location',
    }

    # Walk the timeline and compute durations between events
    phases = []
    sorted_tl = [e for e in timeline if e.get('ts')]
    if not sorted_tl:
        return []

    for i in range(len(sorted_tl) - 1):
        curr = sorted_tl[i]
        nxt = sorted_tl[i + 1]
        event = curr['event']
        seconds = (nxt['ts'] - curr['ts']).total_seconds()
        if seconds < 0:
            continue
        minutes = round(seconds / 60, 1)  # keep 1 decimal for sub-minute phases

        label = _PHASE_LABELS.get(event, event)
        color = _PHASE_COLORS.get(event, '#475569')

        # If previous phase has same label, merge (e.g., two Spotted events)
        if phases and phases[-1]['label'] == label:
            phases[-1]['minutes'] += minutes
            phases[-1]['end_time'] = nxt.get('time', '?')
        else:
            phases.append({
                'label': label,
                'event': event,
                'minutes': minutes,
                'color': color,
                'start_time': curr.get('time', '?'),
                'end_time': nxt.get('time', '?'),
                'driver': curr.get('driver'),
                'reason': curr.get('reason'),
            })

    return phases


# ── Report endpoint ───────────────────────────────────────────────────────────

@router.get('/api/sa/{sa_number}/report')
def sa_report(sa_number: str):
    """Full SA lifecycle report — optimized for 3 SF round trips with caching."""
    sa_number = sanitize_soql(sa_number)
    if not sa_number.upper().startswith('SA-'):
        sa_number = f'SA-{sa_number}'

    def _fetch():
        # ── Single parallel round trip: SA + History + AR + Members ──────
        # Query history/AR by AppointmentNumber (cross-object filter) so we
        # don't need the SA Id first — saves a full SF round trip.
        p0 = sf_parallel(
            sa=lambda: sf_query_all(_SA_FIELDS.format(number=sa_number)),
            hist=lambda: sf_query_all(f"""
                SELECT ServiceAppointmentId, Field, NewValue, CreatedDate,
                       CreatedBy.Name, CreatedBy.Profile.Name
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointment.AppointmentNumber = '{sa_number}'
                  AND Field IN ('Status', 'ERS_Assigned_Resource__c', 'ERS_PTA__c')
                ORDER BY CreatedDate ASC
            """),
            ar=lambda: sf_query_all(f"""
                SELECT ServiceResourceId, ServiceResource.Name, CreatedDate
                FROM AssignedResource
                WHERE ServiceAppointment.AppointmentNumber = '{sa_number}'
                ORDER BY CreatedDate DESC LIMIT 1
            """),
        )

        sa_list = p0['sa']
        if not sa_list:
            return None
        sa     = sa_list[0]
        sa_id  = sa['Id']
        tid    = sa.get('ServiceTerritoryId')
        wt_name = (sa.get('WorkType') or {}).get('Name', '').lower()
        sa_lat  = float(sa['Latitude'])  if sa.get('Latitude')  else None
        sa_lon  = float(sa['Longitude']) if sa.get('Longitude') else None
        sa_summary = _build_sa_summary(sa)
        is_towbook = (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook'

        if not tid:
            return {'sa_summary': sa_summary, 'timeline': [], 'assign_steps': [],
                    'narrative': _build_narrative(sa_summary, [], []),
                    'phases': [], 'is_towbook': is_towbook}

        # Members query needs tid from SA lookup — cached per territory (members rarely change)
        def _fetch_members():
            return sf_query_all(f"""
                SELECT ServiceResourceId, ServiceResource.Name,
                       ServiceResource.LastKnownLatitude, ServiceResource.LastKnownLongitude,
                       ServiceResource.IsActive, TerritoryType
                FROM ServiceTerritoryMember
                WHERE ServiceTerritoryId = '{tid}'
                  AND TerritoryType IN ('P', 'S')
                  AND ServiceResource.IsActive = true
                  AND ServiceResource.ResourceType = 'T'
            """)
        members_raw = cache.cached_query(f'territory_members_{tid}', _fetch_members, ttl=600)

        # Build timeline from hist rows (already fetched in p0)
        timeline = _build_timeline(p0['hist'], sa_id)

        # Parse assign events from the same hist rows
        assign_rows = [r for r in p0['hist'] if r.get('Field') == 'ERS_Assigned_Resource__c']
        status_rows = [r for r in p0['hist'] if r.get('Field') == 'Status']
        assign_events_map = parse_assign_events(assign_rows, {sa_id})
        sa_events   = assign_events_map.get(sa_id, [])
        dispatch_dt = (sa_events[0]['ts'] if sa_events else None) or _parse_dt(sa.get('CreatedDate'))

        # Build reassignment reasons from status changes between assignments
        from simulator import _build_reassign_reasons
        _reasons = _build_reassign_reasons(assign_events_map, status_rows, {sa_id})
        for i, ev in enumerate(sa_events):
            ev['reason'] = _reasons.get((sa_id, i))

        # Inject reasons into timeline Reassigned events (match by driver + time)
        reassign_idx = 0
        for tl_ev in timeline:
            if tl_ev['event'] == 'Reassigned' and 'driver' in tl_ev:
                # Find matching sa_event
                match = next((ev for ev in sa_events
                              if ev.get('is_reassignment') and ev['driver'] == tl_ev['driver']), None)
                if match and match.get('reason'):
                    tl_ev['reason'] = match['reason']

        ar_row        = p0['ar'][0] if p0['ar'] else None
        assigned_sr_id = ar_row.get('ServiceResourceId') if ar_row else None

        members = [m for m in members_raw
                   if not ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]

        # ── Round trip 2b: cascade fallback (Towbook territory → find original fleet tid)
        if not members:
            tid_hist = sf_query_all(f"""
                SELECT OldValue FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId = '{sa_id}'
                  AND Field = 'ServiceTerritoryId'
                ORDER BY CreatedDate ASC LIMIT 1
            """)
            original_tid = tid_hist[0].get('OldValue') if tid_hist else None
            if original_tid and original_tid != tid:
                orig_raw = sf_query_all(f"""
                    SELECT ServiceResourceId, ServiceResource.Name,
                           ServiceResource.LastKnownLatitude, ServiceResource.LastKnownLongitude,
                           ServiceResource.IsActive, TerritoryType
                    FROM ServiceTerritoryMember
                    WHERE ServiceTerritoryId = '{original_tid}'
                      AND TerritoryType IN ('P', 'S')
                      AND ServiceResource.IsActive = true
                      AND ServiceResource.ResourceType = 'T'
                """)
                members = [m for m in orig_raw
                           if not ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]

        if not members:
            narrative = _build_narrative(sa_summary, timeline, [])
            return {'sa_summary': sa_summary, 'timeline': timeline, 'assign_steps': [],
                    'narrative': narrative, 'phases': _build_phases(timeline, sa_summary),
                    'is_towbook': is_towbook}

        all_sr_ids = list({m.get('ServiceResourceId') for m in members if m.get('ServiceResourceId')})
        if assigned_sr_id and assigned_sr_id not in all_sr_ids:
            all_sr_ids.append(assigned_sr_id)

        required_skills: list = []
        for kw, skills in _SKILL_MAP.items():
            if kw in wt_name:
                required_skills.extend(skills)

        ids_quoted = ', '.join(f"'{i}'" for i in all_sr_ids)

        # GPS window: 15 min before first assignment → 5 min after last assignment.
        # Covers all reassignment steps, not just the first dispatch.
        # GPS window: 15 min before to 5 min after. FSL app updates every ~5 min,
        # so this captures 2-3 GPS records per active driver. Wider window would
        # show stale positions where drivers no longer are.
        all_step_times = [ev['ts'] for ev in sa_events if ev.get('ts')]
        if all_step_times:
            gps_start = (min(all_step_times) - timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')
            gps_end   = (max(all_step_times) + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        elif dispatch_dt:
            gps_start = (dispatch_dt - timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')
            gps_end   = (dispatch_dt + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            gps_start = gps_end = None

        # ── Round trip 3: skills + GPS lat + GPS lon + truck logins (all parallel) ──
        def _get_skills():
            if not required_skills:
                return []
            cond = ' OR '.join(f"Skill.MasterLabel LIKE '%{s.title()}%'" for s in required_skills)
            return sf_query_all(f"""
                SELECT ServiceResourceId, Skill.MasterLabel
                FROM ServiceResourceSkill
                WHERE ServiceResourceId IN ({ids_quoted})
                  AND ({cond})
                  AND (EffectiveStartDate = null OR EffectiveStartDate <= TODAY)
                  AND (EffectiveEndDate = null OR EffectiveEndDate >= TODAY)
            """)

        def _get_gps_lat():
            if not gps_start:
                return []
            return sf_query_all(f"""
                SELECT ServiceResourceId, NewValue, CreatedDate
                FROM ServiceResourceHistory
                WHERE Field = 'LastKnownLatitude'
                  AND ServiceResourceId IN ({ids_quoted})
                  AND CreatedDate >= {gps_start} AND CreatedDate <= {gps_end}
                ORDER BY CreatedDate ASC
            """)

        def _get_gps_lon():
            if not gps_start:
                return []
            return sf_query_all(f"""
                SELECT ServiceResourceId, NewValue, CreatedDate
                FROM ServiceResourceHistory
                WHERE Field = 'LastKnownLongitude'
                  AND ServiceResourceId IN ({ids_quoted})
                  AND CreatedDate >= {gps_start} AND CreatedDate <= {gps_end}
                ORDER BY CreatedDate ASC
            """)

        def _get_truck_logins():
            if not all_step_times:
                return []
            # NewValue/OldValue can't be filtered in SOQL — fetch all ERS_Driver__c
            # changes in the time window and filter by driver SR Id in Python.
            # 2h lookback is enough to determine on-truck status at dispatch time.
            login_start = (min(all_step_times) - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
            login_end   = (max(all_step_times) + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
            rows = sf_query_all(f"""
                SELECT OldValue, NewValue, CreatedDate
                FROM AssetHistory
                WHERE Field = 'ERS_Driver__c'
                  AND CreatedDate >= {login_start}
                  AND CreatedDate <= {login_end}
                ORDER BY CreatedDate ASC
            """)
            sr_id_set = set(all_sr_ids)
            return [r for r in rows
                    if (r.get('NewValue') or '') in sr_id_set
                    or (r.get('OldValue') or '') in sr_id_set]

        p2 = sf_parallel(skills=_get_skills, gps_lat=_get_gps_lat, gps_lon=_get_gps_lon,
                         truck_logins=_get_truck_logins)

        # Build driver_skills + skilled_ids
        driver_skills: dict = _dd(set)
        for r in p2['skills']:
            sr_id = r.get('ServiceResourceId')
            lbl   = (r.get('Skill') or {}).get('MasterLabel', '')
            if sr_id and lbl:
                driver_skills[sr_id].add(lbl)

        if required_skills:
            skilled_ids = set(driver_skills.keys())
            if assigned_sr_id:
                skilled_ids.add(assigned_sr_id)
        else:
            skilled_ids = set(all_sr_ids)

        # Build GPS history from raw rows (already fetched for all members in parallel)
        lat_hist: dict = _dd(list)
        lon_hist: dict = _dd(list)
        for row in p2['gps_lat']:
            d_id, ts = row.get('ServiceResourceId'), _parse_dt(row.get('CreatedDate'))
            if d_id and ts and d_id in skilled_ids:
                try:
                    lat_hist[d_id].append((ts, float(row['NewValue'])))
                except (TypeError, ValueError):
                    pass
        for row in p2['gps_lon']:
            d_id, ts = row.get('ServiceResourceId'), _parse_dt(row.get('CreatedDate'))
            if d_id and ts and d_id in skilled_ids:
                try:
                    lon_hist[d_id].append((ts, float(row['NewValue'])))
                except (TypeError, ValueError):
                    pass
        for d_id in lat_hist:
            lat_hist[d_id].sort(key=lambda x: x[0])
        for d_id in lon_hist:
            lon_hist[d_id].sort(key=lambda x: x[0])

        # Name map (from members + AR)
        name_map = {m.get('ServiceResourceId'): (m.get('ServiceResource') or {}).get('Name', '?')
                    for m in members}
        if ar_row and assigned_sr_id:
            name_map[assigned_sr_id] = (ar_row.get('ServiceResource') or {}).get(
                'Name', name_map.get(assigned_sr_id, '?'))

        truck_login_hist = build_truck_login_hist(p2['truck_logins'])

        assign_steps = build_assign_steps(
            events           = sa_events,
            members          = members,
            driver_skills    = dict(driver_skills),
            required_skills  = set(required_skills),
            sa_lat           = sa_lat or 0.0,
            sa_lon           = sa_lon or 0.0,
            lat_hist         = lat_hist,
            lon_hist         = lon_hist,
            truck_login_hist = truck_login_hist,
        )

        narrative = _build_narrative(sa_summary, timeline, assign_steps)
        phases = _build_phases(timeline, sa_summary)
        reassignment_impact = _build_reassignment_impact(
            sa_summary, timeline, assign_steps, p0['hist'])

        return {
            'sa_summary':   sa_summary,
            'timeline':     timeline,
            'assign_steps': assign_steps,
            'narrative':    narrative,
            'phases':       phases,
            'reassignment_impact': reassignment_impact,
            'is_towbook':   is_towbook,
        }

    result = cache.cached_query(f'sa_report_{sa_number}', _fetch, ttl=3600)  # 1h — historical reports don't change
    if result is None:
        raise HTTPException(status_code=404, detail=f'SA {sa_number} not found')
    # Completed/Canceled SAs won't change — extend cache to 1 hour
    status = (result.get('sa_summary') or {}).get('status', '')
    if status in ('Completed', 'Canceled', 'Unable to Complete', 'No-Show'):
        cache.put(f'sa_report_{sa_number}', result, ttl=3600)
    return result
