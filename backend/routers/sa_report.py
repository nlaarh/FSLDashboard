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
from utils import parse_dt as _parse_dt, to_eastern as _to_eastern, haversine
from dispatch_utils import (
    parse_assign_events, build_assign_steps,
    build_truck_login_hist,
)
from routers.misc import _SKILL_MAP
from routers.sa_report_timeline import (
    _build_sa_summary, _build_timeline, _build_narrative,
    _build_reassignment_impact, _build_phases,
)

router = APIRouter()

_MAX_CANDIDATE_MEMBERS = 80
_PREFILTER_TRIGGER_SIZE = 120
_MAX_STEP_DRIVERS = 24
_MAX_TRUCK_GATE_IDS = 40

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


# ── Report endpoint ───────────────────────────────────────────────────────────

@router.get('/api/sa/{sa_number}/report')
def sa_report(sa_number: str):
    """Full SA lifecycle report — optimized for 3 SF round trips with caching."""
    sa_number = sanitize_soql(sa_number)
    if not sa_number.upper().startswith('SA-'):
        sa_number = f'SA-{sa_number}'

    def _fetch():
        # Round trip 1: direct SA lookup by AppointmentNumber.
        sa_list = sf_query_all(_SA_FIELDS.format(number=sa_number))
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

        member_tid = tid

        # Members query needs territory id from SA lookup/cascade resolution.
        def _fetch_members():
            return sf_query_all(f"""
                SELECT ServiceResourceId, ServiceResource.Name,
                       ServiceResource.LastKnownLatitude, ServiceResource.LastKnownLongitude,
                       ServiceResource.IsActive, TerritoryType
                FROM ServiceTerritoryMember
                WHERE ServiceTerritoryId = '{member_tid}'
                  AND TerritoryType IN ('P', 'S')
                  AND ServiceResource.IsActive = true
                  AND ServiceResource.ResourceType = 'T'
            """)

        # Round trip 2: fetch history + assigned resource by SA Id.
        p1 = sf_parallel(
            hist=lambda: sf_query_all(f"""
                SELECT ServiceAppointmentId, Field, NewValue, CreatedDate,
                       CreatedBy.Name, CreatedBy.Profile.Name
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId = '{sa_id}'
                  AND Field IN ('Status', 'ERS_Assigned_Resource__c', 'ERS_PTA__c', 'SchedStartTime', 'ServiceTerritory')
                ORDER BY CreatedDate ASC
            """),
            ar=lambda: sf_query_all(f"""
                SELECT ServiceResourceId, ServiceResource.Name, CreatedDate
                FROM AssignedResource
                WHERE ServiceAppointmentId = '{sa_id}'
                ORDER BY CreatedDate DESC LIMIT 1
            """),
        )
        hist_rows = p1['hist']

        # Build timeline from hist rows.
        timeline = _build_timeline(hist_rows, sa_id)

        # Parse assign events from the same hist rows
        assign_rows = [r for r in hist_rows if r.get('Field') == 'ERS_Assigned_Resource__c']
        status_rows = [r for r in hist_rows if r.get('Field') == 'Status']
        territory_rows = [r for r in hist_rows if r.get('Field') == 'ServiceTerritory']
        assign_events_map = parse_assign_events(assign_rows, {sa_id})
        sa_events   = assign_events_map.get(sa_id, [])
        dispatch_dt = (sa_events[0]['ts'] if sa_events else None) or _parse_dt(sa.get('CreatedDate'))

        if is_towbook:
            for h in territory_rows:
                if h.get('OldValue') is None:
                    nv = h.get('NewValue') or ''
                    if len(nv) >= 15 and nv.startswith('0H') and nv != tid:
                        member_tid = nv
                        break

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

        ar_row = p1['ar'][0] if p1['ar'] else None
        assigned_sr_id = ar_row.get('ServiceResourceId') if ar_row else None

        def _finalize(assign_steps: list):
            sched_rows = [(h, _parse_dt(h.get('CreatedDate')), h.get('NewValue'))
                          for h in hist_rows
                          if h.get('Field') == 'SchedStartTime' and h.get('NewValue')]
            for i, step in enumerate(assign_steps):
                step_ts = step.get('ts')
                next_ts = assign_steps[i + 1].get('ts') if i + 1 < len(assign_steps) else None
                if not step_ts:
                    continue
                step_scheds = []
                for _, h_ts, val in sched_rows:
                    if not h_ts:
                        continue
                    after_assign = (h_ts - step_ts).total_seconds() >= -2
                    before_next = ((next_ts - h_ts).total_seconds() > 2) if next_ts else True
                    if after_assign and before_next:
                        et = _to_eastern(val)
                        if et:
                            step_scheds.append(et.strftime('%-I:%M %p'))
                step['sched_start_initial'] = step_scheds[0] if step_scheds else None
                step['sched_start_final'] = step_scheds[-1] if len(step_scheds) > 1 else None

            actual_start = _to_eastern(sa.get('ActualStartTime'))
            actual_end = _to_eastern(sa.get('ActualEndTime'))
            if assign_steps:
                last_step = assign_steps[-1]
                last_step['actual_start'] = actual_start.strftime('%-I:%M %p') if actual_start else None
                last_step['actual_end'] = actual_end.strftime('%-I:%M %p') if actual_end else None

            narrative = _build_narrative(sa_summary, timeline, assign_steps)
            phases = _build_phases(timeline, sa_summary)
            reassignment_impact = _build_reassignment_impact(
                sa_summary, timeline, assign_steps, hist_rows)
            return {
                'sa_summary':   sa_summary,
                'timeline':     timeline,
                'assign_steps': assign_steps,
                'narrative':    narrative,
                'phases':       phases,
                'reassignment_impact': reassignment_impact,
                'is_towbook':   is_towbook,
            }

        towbook_only_steps = bool(sa_events) and all(
            (ev.get('driver') or '').lower().startswith('towbook')
            for ev in sa_events
        )
        if towbook_only_steps:
            assign_steps = [{
                'time': ev['time'],
                'ts': ev.get('ts'),
                'driver': ev.get('driver', ''),
                'is_reassignment': ev.get('is_reassignment', False),
                'by_name': ev.get('by_name', ''),
                'is_human': ev.get('is_human', False),
                'reason': ev.get('reason'),
                'step_drivers': [],
            } for ev in sa_events]
            return _finalize(assign_steps)

        members_raw = cache.cached_query(f'territory_members_{member_tid}', _fetch_members, ttl=600)
        members = [m for m in members_raw
                   if not ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]

        # Fallback: if membership still empty, retry original territory inference.
        if not members:
            original_tid = None
            for h in territory_rows:
                if h.get('OldValue') is None:
                    nv = h.get('NewValue') or ''
                    if len(nv) >= 15 and nv.startswith('0H'):
                        original_tid = nv
                        break
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

        # Large territories can produce very large member/skill/GPS fan-out.
        # Pre-filter to nearest known-current drivers before expensive history queries.
        if sa_lat is not None and sa_lon is not None and len(all_sr_ids) > _PREFILTER_TRIGGER_SIZE:
            scored: list[tuple[float, str]] = []
            for m in members:
                sr_id = m.get('ServiceResourceId')
                if not sr_id:
                    continue
                sr = m.get('ServiceResource') or {}
                d_lat = sr.get('LastKnownLatitude')
                d_lon = sr.get('LastKnownLongitude')
                if d_lat is None or d_lon is None:
                    continue
                try:
                    dist = haversine(float(d_lat), float(d_lon), sa_lat, sa_lon)
                except (TypeError, ValueError):
                    continue
                scored.append((dist, sr_id))

            top_ids = {sr_id for _, sr_id in sorted(scored, key=lambda x: x[0])[:_MAX_CANDIDATE_MEMBERS]}
            if assigned_sr_id:
                top_ids.add(assigned_sr_id)
            if top_ids:
                members = [m for m in members if m.get('ServiceResourceId') in top_ids]
                all_sr_ids = [sr_id for sr_id in all_sr_ids if sr_id in top_ids]

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

        # ── Round trip 3a: skills (parallel stage 1) ───────────────────────────
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

        p2a = sf_parallel(skills=_get_skills)

        # Build driver_skills + skilled_ids
        driver_skills: dict = _dd(set)
        for r in p2a['skills']:
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

        # ── Round trip 3b: GPS + truck logins (parallel stage 2) ──────────────
        skilled_ids_quoted = ', '.join(f"'{i}'" for i in skilled_ids)

        def _get_gps_history():
            if not gps_start or not skilled_ids:
                return []
            return sf_query_all(f"""
                SELECT ServiceResourceId, Field, NewValue, CreatedDate
                FROM ServiceResourceHistory
                WHERE Field IN ('LastKnownLatitude', 'LastKnownLongitude')
                  AND ServiceResourceId IN ({skilled_ids_quoted})
                  AND CreatedDate >= {gps_start} AND CreatedDate <= {gps_end}
                ORDER BY CreatedDate ASC
            """)

        def _get_truck_logins():
            if not all_step_times or not skilled_ids:
                return None
            if len(skilled_ids) > _MAX_TRUCK_GATE_IDS:
                # AssetHistory scan is the dominant cost on large candidate sets.
                # In fast mode, skip truck-login gating and rely on skills + GPS + capped nearest set.
                return None
            # NewValue/OldValue can't be filtered in SOQL; reduce scan by time window
            # and ERS Truck record type, then filter to relevant driver SR IDs in Python.
            login_start = (min(all_step_times) - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
            login_end   = (max(all_step_times) + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
            rows = sf_query_all(f"""
                SELECT OldValue, NewValue, CreatedDate
                FROM AssetHistory
                WHERE Field = 'ERS_Driver__c'
                  AND Asset.RecordType.Name = 'ERS Truck'
                  AND CreatedDate >= {login_start}
                  AND CreatedDate <= {login_end}
            """)
            return [r for r in rows
                    if (r.get('NewValue') or '') in skilled_ids
                    or (r.get('OldValue') or '') in skilled_ids]

        p2b = sf_parallel(gps_history=_get_gps_history, truck_logins=_get_truck_logins)

        # Build GPS history from raw rows (already fetched for all members in parallel)
        lat_hist: dict = _dd(list)
        lon_hist: dict = _dd(list)
        for row in p2b['gps_history']:
            d_id, ts = row.get('ServiceResourceId'), _parse_dt(row.get('CreatedDate'))
            if d_id and ts and d_id in skilled_ids:
                field = row.get('Field')
                try:
                    val = float(row['NewValue'])
                except (TypeError, ValueError):
                    continue
                if field == 'LastKnownLatitude':
                    lat_hist[d_id].append((ts, val))
                elif field == 'LastKnownLongitude':
                    lon_hist[d_id].append((ts, val))
        for d_id in lat_hist:
            lat_hist[d_id].sort(key=lambda x: x[0])
        for d_id in lon_hist:
            lon_hist[d_id].sort(key=lambda x: x[0])

        truck_login_rows = p2b.get('truck_logins')
        truck_login_hist = build_truck_login_hist(truck_login_rows) if truck_login_rows is not None else None

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
            max_step_drivers = _MAX_STEP_DRIVERS,
        )

        return _finalize(assign_steps)

    result = cache.cached_query(f'sa_report_{sa_number}', _fetch, ttl=3600)  # 1h — historical reports don't change
    if result is None:
        raise HTTPException(status_code=404, detail=f'SA {sa_number} not found')
    # Completed/Canceled SAs won't change — extend cache to 1 hour
    status = (result.get('sa_summary') or {}).get('status', '')
    if status in ('Completed', 'Canceled', 'Unable to Complete', 'No-Show'):
        cache.put(f'sa_report_{sa_number}', result, ttl=3600)
    return result
