"""Dispatch simulation engine — historical GPS version.

For each SA on a given day, determines:
  - Which driver was actually assigned
  - Which driver was closest at dispatch time (historical GPS)
  - Whether the closest driver was picked

Driver GPS positions: ServiceResourceHistory (where they WERE at dispatch time)
  - Assigned driver: ERS_Dispatched_Geolocation__Latitude__s preferred (exact snapshot)
  - All others: most recent ServiceResourceHistory record ≤ dispatch time + 5 min
  - Drivers with no historical GPS are excluded (never show stale current position)
"""

from datetime import datetime, date, timedelta, timezone
from collections import defaultdict

from utils import _ET, parse_dt as _parse_dt, to_eastern as _to_eastern, haversine
from sf_client import sf_query_all, sf_parallel, sanitize_soql
from dispatch_utils import (
    fetch_gps_history, gps_at_time,
    parse_assign_events, build_assign_steps,
)
import cache


# _build_assign_steps removed — use build_assign_steps() from dispatch_utils

# Status values that indicate why a reassignment happened
# {prev_driver} is replaced with the actual driver name
_REASON_MAP = {
    'Spotted':                           '{prev_driver} declined / bounced back to queue',
    'Dispatched':                        'Re-dispatched by system after {prev_driver}',
    'Cancel Call - Service Not En Route': 'Canceled before {prev_driver} en route',
    'Cancel Call - Service En Route':    'Canceled while {prev_driver} en route',
    'Unable to Complete':                '{prev_driver} unable to complete',
    'No-Show':                           '{prev_driver} no-show',
}


def _build_reassign_reasons(sa_assign_events: dict, status_rows: list, sa_id_set: set) -> dict:
    """For each reassignment, find the status change that happened between assignments.

    Returns {(sa_id, reassign_index): reason_string}
    """
    # Build per-SA status timeline: [(ts, status), ...]
    sa_statuses = defaultdict(list)
    for r in status_rows:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id or (sa_id_set and sa_id not in sa_id_set):
            continue
        ts = _parse_dt(r.get('CreatedDate'))
        new_val = (r.get('NewValue') or '').strip()
        if ts and new_val:
            sa_statuses[sa_id].append((ts, new_val))
    for sa_id in sa_statuses:
        sa_statuses[sa_id].sort(key=lambda x: x[0])

    reasons = {}
    for sa_id, evs in sa_assign_events.items():
        for i, ev in enumerate(evs):
            if not ev.get('is_reassignment'):
                continue
            prev_driver = evs[i - 1].get('driver', 'Previous driver') if i > 0 else 'Previous driver'
            prev_ts = evs[i - 1].get('ts') if i > 0 else None
            curr_ts = ev.get('ts')
            if not prev_ts or not curr_ts:
                continue
            # Find status changes between previous assignment and this reassignment
            # Exclude 'Assigned' itself — we want the CAUSE, not the reassignment event
            between = [s for ts, s in sa_statuses.get(sa_id, [])
                       if prev_ts < ts < curr_ts and s != 'Assigned']
            reason = None
            for status in reversed(between):
                if status in _REASON_MAP:
                    reason = _REASON_MAP[status].format(prev_driver=prev_driver)
                    break
            if not reason and ev.get('is_human'):
                reason = f'Manually reassigned by {ev.get("by_name", "dispatcher")}'
            reasons[(sa_id, i)] = reason or 'Reassigned'
    return reasons


def simulate_day(territory_id: str, date_str: str) -> list[dict]:
    """Simulation: SA list + driver distances using historical GPS at dispatch time."""
    territory_id = sanitize_soql(territory_id)
    date_str = sanitize_soql(date_str)
    next_day = (date.fromisoformat(date_str) + timedelta(days=1)).isoformat()

    # 1. SAs, territory, members, AND assignment history — all parallel.
    #    SAHistory fetched by date range here (before we know SA IDs) so it runs
    #    in parallel with the SA query rather than sequentially in a batch loop.
    data = sf_parallel(
        sas=lambda: sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, CreatedDate,
                   SchedStartTime, ActualStartTime, ActualEndTime,
                   Street, City, State, Latitude, Longitude,
                   ServiceTerritoryId, ServiceTerritory.Name,
                   WorkType.Name, Off_Platform_Truck_Id__c,
                   ERS_PTA__c, ERS_Dispatch_Method__c, ERS_Auto_Assign__c,
                   ERS_Dispatched_Geolocation__Latitude__s,
                   ERS_Dispatched_Geolocation__Longitude__s,
                   ERS_Cancellation_Reason__c, FSL__Duration_In_Minutes__c
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {date_str}T00:00:00Z
              AND CreatedDate < {next_day}T00:00:00Z
              AND Status IN ('Dispatched','Completed','Canceled',
                             'Cancel Call - Service Not En Route',
                             'Cancel Call - Service En Route',
                             'Unable to Complete','Assigned','No-Show')
            ORDER BY CreatedDate ASC
        """),
        territory=lambda: sf_query_all(f"""
            SELECT Id, Name, Latitude, Longitude
            FROM ServiceTerritory
            WHERE Id = '{territory_id}'
        """),
        members=lambda: sf_query_all(f"""
            SELECT ServiceResourceId, ServiceResource.Name,
                   ServiceResource.LastKnownLatitude, ServiceResource.LastKnownLongitude,
                   TerritoryType
            FROM ServiceTerritoryMember
            WHERE ServiceTerritoryId = '{territory_id}'
              AND ServiceResource.IsActive = true
        """),
        assign_hist=lambda: sf_query_all(f"""
            SELECT ServiceAppointmentId, Field, CreatedDate, NewValue,
                   CreatedBy.Name, CreatedBy.Profile.Name
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointment.ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {date_str}T00:00:00Z
              AND CreatedDate < {next_day}T00:00:00Z
              AND Field IN ('ERS_Assigned_Resource__c', 'Status')
            ORDER BY CreatedDate ASC
        """),
    )

    sas = data['sas']
    if not sas:
        return []

    t_row = data['territory'][0] if data['territory'] else {}
    territory = {
        'id': territory_id,
        'name': t_row.get('Name', '?'),
        'lat': t_row.get('Latitude'),
        'lon': t_row.get('Longitude'),
    }

    members = data['members']
    driver_ids = list(set(m['ServiceResourceId'] for m in members))

    # 2. Build assign events + first-dispatch-time lookup from SAHistory.
    #    AR.CreatedDate is wrong for reassigned SAs — SF deletes old ARs on reassignment.
    #    True dispatch time = earliest ERS_Assigned_Resource__c SAHistory row per SA.
    sa_ids = [sa['Id'] for sa in sas]
    sa_id_set = set(sa_ids)

    # Split history rows: assignment events vs status changes
    assign_rows = [r for r in data['assign_hist'] if r.get('Field') == 'ERS_Assigned_Resource__c']
    status_rows = [r for r in data['assign_hist'] if r.get('Field') == 'Status']

    # parse_assign_events() filters SF-ID rows, detects human dispatchers, marks reassignments
    sa_assign_events = parse_assign_events(assign_rows, sa_id_set)

    # Build reassignment reason: what status happened between two assignments
    # e.g. Spotted = driver declined, Canceled = call canceled
    _reassign_reasons = _build_reassign_reasons(sa_assign_events, status_rows, sa_id_set)

    # Inject reassignment reasons into assign events
    for sa_id, evs in sa_assign_events.items():
        for i, ev in enumerate(evs):
            ev['reason'] = _reassign_reasons.get((sa_id, i))

    # First dispatch time = ts of first event per SA (rows are ORDER BY ASC)
    first_dispatch_dt = {
        sa_id: evs[0]['ts']
        for sa_id, evs in sa_assign_events.items()
        if evs and evs[0]['ts']
    }

    # Last assigned driver name per SA (for Towbook display where no AR exists)
    last_driver_name = {
        sa_id: evs[-1]['driver']
        for sa_id, evs in sa_assign_events.items()
        if evs
    }

    # AssignedResource: current driver identity (name + ID)
    ar_map = {}  # sa_id -> {resource_id, resource_name, dispatch_dt}
    for i in range(0, len(sa_ids), 200):
        batch = sa_ids[i:i+200]
        id_list = ",".join(f"'{s}'" for s in batch)
        ars = sf_query_all(f"""
            SELECT ServiceAppointmentId, ServiceResourceId,
                   ServiceResource.Name, ServiceResource.ERS_Driver_Type__c
            FROM AssignedResource
            WHERE ServiceAppointmentId IN ({id_list})
        """)
        for ar in ars:
            sa_ref = ar.get('ServiceAppointmentId')
            sr = ar.get('ServiceResource') or {}
            if sa_ref:
                ar_map[sa_ref] = {
                    'resource_id': ar.get('ServiceResourceId'),
                    'resource_name': sr.get('Name', '?'),
                    'driver_type': sr.get('ERS_Driver_Type__c') or '',
                    'dispatch_dt': first_dispatch_dt.get(sa_ref),
                }

    # 3. Historical GPS for all drivers across the full day
    #    Buffer: 2h before start of day, 1h after end to catch early/late shifts
    hist_start = (date.fromisoformat(date_str) - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
    hist_end   = (date.fromisoformat(date_str) + timedelta(days=1, hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    lat_hist, lon_hist = fetch_gps_history(driver_ids, hist_start, hist_end)

    # 4. Driver skills + work type skills — parallel, cached 1hr
    def _get_skills():
        if not driver_ids:
            return {'driver_skills': [], 'wt_skills': []}
        id_list = ",".join(f"'{d}'" for d in driver_ids)
        sk = sf_parallel(
            driver_skills=lambda: sf_query_all(f"""
                SELECT ServiceResourceId, Skill.MasterLabel
                FROM ServiceResourceSkill
                WHERE ServiceResourceId IN ({id_list})
            """),
            wt_rows=lambda: sf_query_all("SELECT Id, Name FROM WorkType"),
        )
        # Get skill requirements for work types
        wt_ids = [w['Id'] for w in sk['wt_rows']]
        wt_sk = []
        if wt_ids:
            wt_id_list = ",".join(f"'{w}'" for w in wt_ids)
            wt_sk = sf_query_all(f"""
                SELECT RelatedRecordId, Skill.MasterLabel
                FROM SkillRequirement
                WHERE RelatedRecordId IN ({wt_id_list})
            """)
        return {
            'driver_skills': sk['driver_skills'],
            'wt_rows': sk['wt_rows'],
            'wt_skill_reqs': wt_sk,
        }

    skills_data = cache.cached_query(f'skills_{territory_id}', _get_skills, ttl=3600)

    # Build skill maps
    driver_skills = defaultdict(set)
    for r in skills_data['driver_skills']:
        sk = (r.get('Skill') or {}).get('MasterLabel')
        if sk:
            driver_skills[r['ServiceResourceId']].add(sk)

    wt_skills = {}
    wt_id_to_name = {w['Id']: w.get('Name', '') for w in skills_data.get('wt_rows', [])}
    wt_id_skills = defaultdict(list)
    for s in skills_data.get('wt_skill_reqs', []):
        sk = (s.get('Skill') or {}).get('MasterLabel')
        if sk:
            wt_id_skills[s['RelatedRecordId']].append(sk)
    for wid, name in wt_id_to_name.items():
        wt_skills[name] = wt_id_skills.get(wid, [])

    # 5. Simulate each SA
    results = []
    for sa in sas:
        sa_lat = sa.get('Latitude')
        sa_lon = sa.get('Longitude')
        if not sa_lat or not sa_lon:
            continue
        sa_lat, sa_lon = float(sa_lat), float(sa_lon)

        wt_name = (sa.get('WorkType') or {}).get('Name') or ''
        required_skills = set(wt_skills.get(wt_name, []))
        dispatch_method = sa.get('ERS_Dispatch_Method__c') or 'Unknown'

        truck_id = sa.get('Off_Platform_Truck_Id__c') or ''
        ar_info = ar_map.get(sa['Id'])
        sa_id = sa['Id']
        hist_driver = last_driver_name.get(sa_id)  # real name from SAHistory
        if ar_info:
            actual_driver_id = ar_info['resource_id']
            # For Towbook, AR resource name is a placeholder (e.g. "Towbook-4652D").
            # Use SAHistory display name instead when available.
            actual_driver_name = hist_driver or ar_info['resource_name']
            # Use SAHistory first-dispatch time; fall back to SA.CreatedDate
            dispatch_dt = ar_info['dispatch_dt'] or _parse_dt(sa.get('CreatedDate'))
        elif truck_id:
            actual_driver_id = None
            actual_driver_name = hist_driver or f"Truck {truck_id.split('-')[-1]}"
            dispatch_dt = first_dispatch_dt.get(sa_id) or _parse_dt(sa.get('CreatedDate'))
        else:
            actual_driver_id = None
            actual_driver_name = hist_driver or 'Unassigned'
            dispatch_dt = first_dispatch_dt.get(sa_id) or _parse_dt(sa.get('CreatedDate'))

        # Dispatched GPS snapshot on the SA itself (most accurate for assigned driver)
        disp_lat = sa.get('ERS_Dispatched_Geolocation__Latitude__s')
        disp_lon = sa.get('ERS_Dispatched_Geolocation__Longitude__s')
        if disp_lat:
            disp_lat = float(disp_lat)
        if disp_lon:
            disp_lon = float(disp_lon)

        evaluations = []
        for member in members:
            d_id = member['ServiceResourceId']
            sr = member.get('ServiceResource') or {}
            d_name = sr.get('Name', '?')

            d_skills = set(driver_skills.get(d_id, []))
            has_skills = required_skills.issubset(d_skills) if required_skills else True

            # Historical GPS position at dispatch time
            is_actual = (d_id == actual_driver_id)
            if is_actual and disp_lat and disp_lon:
                # Exact dispatch-time snapshot from SA field
                d_lat, d_lon = disp_lat, disp_lon
                has_gps = True
            else:
                d_lat, d_lon = gps_at_time(d_id, dispatch_dt, lat_hist, lon_hist)
                has_gps = d_lat is not None and d_lon is not None

            if not has_gps:
                continue

            dist = haversine(d_lat, d_lon, sa_lat, sa_lon)
            eligible = has_skills

            evaluations.append({
                'driver_id': d_id,
                'name': d_name,
                'eff_lat': d_lat,
                'eff_lon': d_lon,
                'distance': dist,
                'has_gps': True,
                'has_skills': has_skills,
                'skills': list(d_skills),
                'eligible': eligible,
                'is_actual': is_actual,
                'territory_type': member.get('TerritoryType', '?'),
            })

        eligible_list = [e for e in evaluations if e['eligible'] and e['distance'] is not None]
        closest = min(eligible_list, key=lambda e: e['distance']) if eligible_list else None
        closest_id = closest['driver_id'] if closest else None

        for e in evaluations:
            e['is_closest'] = (e['driver_id'] == closest_id) if closest_id else False

        actual_eval = next((e for e in evaluations if e['is_actual']), None)
        actual_dist = actual_eval['distance'] if actual_eval else None
        closest_dist = closest['distance'] if closest else None
        if actual_driver_id and closest_id:
            closest_picked = actual_driver_id == closest_id
            extra_miles = round(actual_dist - closest_dist, 1) if actual_dist and closest_dist else None
        else:
            closest_picked = None
            extra_miles = None

        cd = _parse_dt(sa.get('CreatedDate'))
        et = _to_eastern(sa.get('CreatedDate'))
        ss = _parse_dt(sa.get('SchedStartTime'))
        sched_et = _to_eastern(sa.get('SchedStartTime'))
        ast = _parse_dt(sa.get('ActualStartTime'))
        start_et = _to_eastern(sa.get('ActualStartTime'))
        aet = _parse_dt(sa.get('ActualEndTime'))
        end_et = _to_eastern(sa.get('ActualEndTime'))

        response_min = None
        if cd and ast:
            diff = (ast - cd).total_seconds() / 60
            if 0 < diff < 1440:
                response_min = round(diff)

        dispatch_min = None
        if cd and ss:
            diff = (ss - cd).total_seconds() / 60
            if 0 <= diff < 1440:
                dispatch_min = round(diff)

        service_min = None
        if ast and aet:
            diff = (aet - ast).total_seconds() / 60
            if 0 < diff < 1440:
                service_min = round(diff)

        total_min = None
        if cd and aet:
            diff = (aet - cd).total_seconds() / 60
            if 0 < diff < 1440:
                total_min = round(diff)

        disp_to_sa_dist = haversine(disp_lat, disp_lon, sa_lat, sa_lon) if disp_lat and disp_lon else None

        pta = sa.get('ERS_PTA__c')
        sla_met = response_min is not None and response_min <= 45
        pta_met = pta is not None and response_min is not None and response_min <= float(pta)

        # Channel badge: Towbook | Fleet | Contractor
        driver_type = (ar_info or {}).get('driver_type', '')
        if dispatch_method == 'Towbook':
            channel = 'Towbook'
        elif 'Contractor' in driver_type:
            channel = 'Contractor'
        else:
            channel = 'Fleet'

        results.append({
            'sa_id': sa['Id'],
            'appointment_number': sa.get('AppointmentNumber', '?'),
            'status': sa.get('Status'),
            'work_type': wt_name,
            'channel': channel,
            'created_time': et.strftime('%b %d, %I:%M %p') if et else '?',
            'created_dt': cd.isoformat() if cd else None,
            'address': f"{sa.get('Street') or ''} {sa.get('City') or ''}".strip(),
            'sa_lat': sa_lat,
            'sa_lon': sa_lon,
            'actual_driver': actual_driver_name,
            'actual_driver_id': actual_driver_id,
            'actual_distance': actual_dist,
            'truck_id': truck_id,
            'closest_driver': None if dispatch_method == 'Towbook' else (closest['name'] if closest else '?'),
            'closest_driver_id': None if dispatch_method == 'Towbook' else closest_id,
            'closest_distance': None if dispatch_method == 'Towbook' else closest_dist,
            'closest_picked': None if dispatch_method == 'Towbook' else closest_picked,
            'extra_miles': None if dispatch_method == 'Towbook' else extra_miles,
            'facility_distance': haversine(
                territory.get('lat'), territory.get('lon'), sa_lat, sa_lon),
            'facility_lat': territory.get('lat'),
            'facility_lon': territory.get('lon'),
            'drivers': [] if dispatch_method == 'Towbook' else evaluations,
            'eligible_count': 0 if dispatch_method == 'Towbook' else len(eligible_list),
            'total_drivers': 0 if dispatch_method == 'Towbook' else len(evaluations),
            'timeline': {
                'created': et.strftime('%b %d, %I:%M %p') if et else None,
                'scheduled': sched_et.strftime('%I:%M %p') if sched_et else None,
                'on_location': start_et.strftime('%I:%M %p') if start_et else None,
                'completed': end_et.strftime('%I:%M %p') if end_et else None,
                'dispatch_min': dispatch_min,
                'response_min': response_min,
                'service_min': service_min,
                'total_min': total_min,
                'pta_promised': float(pta) if pta else None,
                'sla_met': sla_met,
                'pta_met': pta_met,
                'dispatch_method': dispatch_method,
                'auto_assign': sa.get('ERS_Auto_Assign__c'),
                'schedule_mode': 'Unknown',
                'cancel_reason': sa.get('ERS_Cancellation_Reason__c'),
                'duration_planned': sa.get('FSL__Duration_In_Minutes__c'),
                'dispatched_lat': disp_lat,
                'dispatched_lon': disp_lon,
                'dispatched_distance': disp_to_sa_dist,
            },
            'required_skills': list(required_skills),
            'assign_events': sa_assign_events.get(sa['Id'], []),
            'assign_steps': (
                build_assign_steps(
                    sa_assign_events.get(sa['Id'], []),
                    members, driver_skills, required_skills,
                    sa_lat, sa_lon, lat_hist, lon_hist,
                ) if dispatch_method != 'Towbook' else []
            ),
        })

    return results
