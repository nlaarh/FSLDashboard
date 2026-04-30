"""Pure parsing: SF optimizer request/response JSON → database row dicts.

No SF I/O, no DuckDB I/O — all side-effects belong in optimizer_sync.py.

PARSER_VERSION: bumping invalidates opt_blob_audit so all blobs re-process.
v2 — full enrichment: per-SA fields (priority, duration, location, skills),
       per-driver verdicts (full skill names, home territory, travel),
       request.Services fallback when response.objectChanges is empty,
       extended KPIs (response_avg, extraneous, commute distances).
"""

from datetime import datetime

PARSER_VERSION = 'v4b'

_ERROR_TRUNCATE = 500


def _haversine_mi(lat1, lon1, lat2, lon2) -> float | None:
    """Great-circle distance in miles. Returns None if any coord is missing."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    import math
    R = 3958.7613   # Earth radius miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return round(2 * R * math.asin(math.sqrt(a)), 2)


def _is_absent(sched_start: str | None, sched_end: str | None,
               absences: list[tuple[str, str]]) -> bool:
    if not sched_start or not absences:
        return False
    try:
        sa_start = datetime.fromisoformat(sched_start.replace('Z', '+00:00'))
        sa_end = (datetime.fromisoformat(sched_end.replace('Z', '+00:00'))
                  if sched_end else sa_start)
        for start_str, end_str in absences:
            a_start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            a_end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            if a_start <= sa_end and a_end >= sa_start:
                return True
    except Exception:
        pass
    return False


def _records(field) -> list:
    """SF JSON fields shape: dict {records: [...]} or sometimes a plain list."""
    if isinstance(field, dict):
        return field.get('records', []) or []
    if isinstance(field, list):
        return field
    return []


def parse_run(run_id: str, run_name: str, run_at: str,
              req: dict, resp: dict,
              name_map: dict[str, str]) -> tuple[dict, list[dict], list[dict]]:
    """Parse request+response JSON → (run_row, sa_decisions, driver_verdicts)."""

    # ── Catalogs ────────────────────────────────────────────────────────────────
    skills_catalog = {s['Id']: s.get('MasterLabel') or s.get('DeveloperName') or s.get('Name', s['Id'])
                      for s in req.get('Skills', []) if s.get('Id')}

    # Territory / policy. Build full Id→Name map for resolution downstream.
    territories = req.get('Territories', [])
    territory_id = territories[0].get('Id', '') if territories else ''
    territory_name_in_req = territories[0].get('Name', '') if territories else ''
    terr_id_to_name = {t.get('Id'): t.get('Name') for t in territories
                        if t.get('Id') and t.get('Name')}
    # Stash on the request for verdict-builder access
    req['_territory_id_to_name'] = terr_id_to_name

    policy_list = req.get('SchedulingPolicy', [])
    policy = policy_list[0] if policy_list else {}
    policy_id = policy.get('Id', '')
    policy_name = policy.get('Name', '')
    daily_opt = bool(policy.get('FSL__Daily_Optimization__c'))
    commit_mode = policy.get('FSL__Commit_Mode__c', '')

    objectives = req.get('Objectives', [])
    work_rules = req.get('WorkRules', [])

    # ── Resource index ──────────────────────────────────────────────────────────
    resources = req.get('Resources', [])
    res_index: dict[str, dict] = {}
    for r in resources:
        rid = r['Id']
        skills = {s.get('SkillId') for s in _records(r.get('ServiceResourceSkills', {}))
                  if s.get('SkillId')}
        skill_names = sorted([skills_catalog.get(sid, sid[:6]) for sid in skills])

        terr_records = _records(r.get('ServiceTerritories', {}))
        terrs = {t.get('ServiceTerritoryId') for t in terr_records if t.get('ServiceTerritoryId')}
        primary_terr = next((t for t in terr_records if t.get('primaryStm')), None) or \
                        (terr_records[0] if terr_records else None)
        home_lat = primary_terr.get('Latitude') if primary_terr else None
        home_lon = primary_terr.get('Longitude') if primary_terr else None
        # Home-territory NAME would need a Territory lookup table — we have ID only here
        home_terr_id = primary_terr.get('ServiceTerritoryId') if primary_terr else None
        is_off_platform = primary_terr.get('ERS_IsOffPlatformContractor__c', False) if primary_terr else False

        res_index[rid] = {
            'name': name_map.get(rid, rid),
            'skills': skills,
            'skill_names': skill_names,
            'territories': terrs,
            'territory_count': len(terrs),
            'absences': [],
            'is_active': r.get('IsActive', True),
            'resource_type': r.get('ResourceType', ''),
            'is_capacity_based': r.get('IsCapacityBased', False),
            'home_lat': home_lat,
            'home_lon': home_lon,
            'home_territory_id': home_terr_id,
            'is_off_platform': bool(is_off_platform),
        }

    # NonAvailabilities (only Approved ones block scheduling)
    non_avail: dict[str, list] = {}
    for na in req.get('NonAvailabilities', []):
        if not na.get('FSL__Approved__c', False):
            continue
        rid = na.get('ResourceId')
        if rid and 'Start' in na and 'End' in na:
            non_avail.setdefault(rid, []).append((na['Start'], na['End']))

    # ── Services & WOLI skill requirements ──────────────────────────────────────
    services: dict[str, dict] = {s['Id']: s for s in req.get('Services', [])}

    woli_by_wo: dict[str, set] = {}
    for woli in req.get('WorkOrderLineItems', []):
        wo_id = woli.get('WorkOrderId', '')
        skills = {sr.get('SkillId') for sr in _records(woli.get('SkillRequirements', []))
                  if sr.get('SkillId')}
        if wo_id:
            woli_by_wo[wo_id] = woli_by_wo.get(wo_id, set()) | skills

    sa_skills: dict[str, set] = {sa_id: woli_by_wo.get(sa.get('ParentRecordId', ''), set())
                                  for sa_id, sa in services.items()}

    # ── Response: object changes + winners ──────────────────────────────────────
    obj_changes: dict[str, dict] = resp.get('objectChanges') or {}

    winners: dict[str, dict] = {}
    for ar in resp.get('assignedResourcesToUpsert', []) or []:
        sa_id = ar.get('ServiceAppointmentId')
        if sa_id:
            winners[sa_id] = ar

    # FALLBACK — if response is empty, derive winners from request.Services[].ServiceResources
    # (the existing assignment that was either kept or that the optimizer created earlier)
    if not winners and not obj_changes:
        for sa_id, sa in services.items():
            ar_records = _records(sa.get('ServiceResources', {}))
            if ar_records:
                winners[sa_id] = ar_records[0]

    unscheduled_index: dict[str, str] = {}
    for u in resp.get('unscheduledServiceAppointments', []) or []:
        uid = u.get('serviceAppointmentId')
        if uid:
            parts = [u.get('explanation', ''), u.get('details', '')]
            unscheduled_index[uid] = ' — '.join(p for p in parts if p)[:_ERROR_TRUNCATE]

    # ── KPIs ────────────────────────────────────────────────────────────────────
    kpis = resp.get('territoryKpis', {}) or {}
    pre_kpis = kpis.get('territory_pre_opt_kpis', [{}])
    post_kpis = kpis.get('territory_post_opt_kpis', [{}])
    pre = max(pre_kpis, key=lambda k: k.get('num_tasks_scheduled', 0)) if pre_kpis else {}
    post = max(post_kpis, key=lambda k: k.get('num_tasks_scheduled', 0)) if post_kpis else {}
    horizon = req.get('TimeHorizon', {})
    unscheduled_sas = resp.get('unscheduledServiceAppointments', []) or []

    run_row = {
        'id': run_id, 'name': run_name, 'territory_id': territory_id,
        'territory_name': territory_name_in_req,
        'policy_id': policy_id, 'policy_name': policy_name, 'run_at': run_at,
        'horizon_start': horizon.get('Start'), 'horizon_end': horizon.get('Finish'),
        'resources_count': len(resources), 'services_count': len(services),
        'pre_scheduled': pre.get('num_tasks_scheduled', 0),
        'post_scheduled': post.get('num_tasks_scheduled', 0),
        # Real count from the response only — don't fall back to "services minus winners"
        # because services with existing assignments aren't unscheduled, just unchanged.
        'unscheduled_count': len(unscheduled_sas),
        'pre_travel_time_s': int(pre.get('travel_time_between', 0) or 0),
        'post_travel_time_s': int(post.get('travel_time_between', 0) or 0),
        'pre_response_avg_s': float(pre.get('response_time_avg_nonappointment', 0.0) or 0.0),
        'post_response_avg_s': float(post.get('response_time_avg_nonappointment', 0.0) or 0.0),
        # NEW v2 enrichments
        'objectives_count': len(objectives),
        'work_rules_count': len(work_rules),
        'skills_count': len(skills_catalog),
        'daily_optimization': daily_opt,
        'commit_mode': commit_mode,
        'post_response_appt_s': float(post.get('response_time_avg_appointment', 0.0) or 0.0),
        'post_extraneous_time_s': int(post.get('extraneous_time', 0) or 0),
        'post_start_commute_dist': int(post.get('start_commute_dist', 0) or 0),
        'post_end_commute_dist': int(post.get('end_commute_dist', 0) or 0),
        'post_resources_unscheduled': int(post.get('num_resources_unscheduled_regular', 0) or 0),
    }

    sa_decisions = []
    driver_verdicts = []

    # ── Iterate ALL services so every SA appears as a decision row ──────────────
    # Action classification:
    #   - In objectChanges → use that activity (Scheduled, Rescheduled, Unscheduled)
    #   - In unscheduledSAs → Unscheduled
    #   - Has existing assignment in services.ServiceResources → Unchanged (no-op this run)
    #   - No assignment, not in changes → Unscheduled
    for sa_id in services:
        change = obj_changes.get(sa_id, {})
        raw_activity = change.get('activity', '')
        if raw_activity in ('Scheduled', 'Rescheduled'):
            action = 'Scheduled'
        elif raw_activity:
            action = raw_activity
        elif sa_id in unscheduled_index:
            action = 'Unscheduled'
        elif sa_id in winners:
            action = 'Unchanged'   # already assigned; optimizer didn't change it
        else:
            action = 'Unscheduled'

        unsch_reason = unscheduled_index.get(sa_id)
        if unsch_reason is None:
            details = change.get('activityDetails', '')
            if details and 'Unscheduling Reason:' in details:
                unsch_reason = details.split('Unscheduling Reason:')[-1].strip()[:_ERROR_TRUNCATE]

        sa = services.get(sa_id, {})
        sa_number = sa.get('AppointmentNumber', '')
        sa_territory_id = sa.get('ServiceTerritoryId', '')
        sched_start = sa.get('SchedStartTime') or sa.get('EarliestStartTime')
        sched_end = sa.get('SchedEndTime') or sa.get('DueDate')
        priority = sa.get('ERS_Dynamic_Priority__c')
        duration_min = sa.get('Duration')
        sa_lat = sa.get('Latitude')
        sa_lon = sa.get('Longitude')
        sa_status = sa.get('Status', '')
        is_pinned = bool(sa.get('FSL__Pinned__c'))
        seats = sa.get('ERS_Number_of_Seats_Required__c')

        winner_ar = winners.get(sa_id)
        winner_driver_id = winner_ar.get('ServiceResourceId') if winner_ar else None
        winner_driver_name = name_map.get(winner_driver_id, winner_driver_id) if winner_driver_id else None
        winner_travel_time = winner_ar.get('EstimatedTravelTime') if winner_ar else None
        winner_travel_dist = (winner_ar.get('FSL__EstimatedTravelDistanceTo__c') or None) if winner_ar else None

        required_skills = sa_skills.get(sa_id, set())
        required_skill_names = sorted([skills_catalog.get(s, s[:6]) for s in required_skills])

        sa_decisions.append({
            'id': f"{run_id}_{sa_id}", 'run_id': run_id, 'sa_id': sa_id,
            'sa_number': sa_number,
            'sa_work_type': None,    # Not in JSON; populated downstream if needed
            'action': action,
            'unscheduled_reason': unsch_reason,
            'winner_driver_id': winner_driver_id, 'winner_driver_name': winner_driver_name,
            'winner_travel_time_min': winner_travel_time, 'winner_travel_dist_mi': winner_travel_dist,
            'run_at': run_at,
            # NEW v2 enrichments
            'priority': priority,
            'duration_min': duration_min,
            'sa_status': sa_status,
            'sa_lat': sa_lat, 'sa_lon': sa_lon,
            'earliest_start': sa.get('EarliestStartTime'),
            'due_date': sa.get('DueDate'),
            'sched_start': sa.get('SchedStartTime'),
            'sched_end': sa.get('SchedEndTime'),
            'required_skills': ', '.join(required_skill_names) if required_skill_names else None,
            'is_pinned': is_pinned,
            'seats_required': seats,
        })

        # Per-driver verdicts — only for SAs the optimizer actually deliberated on.
        # 'Unchanged' SAs were just kept as-is, no deliberation, no verdict needed.
        if action == 'Unchanged':
            continue

        for rid, rdata in res_index.items():
            is_winner = (rid == winner_driver_id)
            all_absences = rdata['absences'] + non_avail.get(rid, [])

            if sa_territory_id and sa_territory_id not in rdata['territories']:
                reason_code, status = 'territory', 'excluded'
            elif required_skills and not required_skills.issubset(rdata['skills']):
                reason_code, status = 'skill', 'excluded'
            elif _is_absent(sched_start, sched_end, all_absences):
                reason_code, status = 'absent', 'excluded'
            elif is_winner:
                reason_code, status = None, 'winner'
            else:
                reason_code, status = None, 'eligible'

            # Distance: winner's exact value, or estimated haversine for everyone else
            if is_winner:
                t_time = winner_travel_time
                t_dist = winner_travel_dist
            else:
                # Haversine from driver's home → SA location, ÷ 25 mph for travel time est
                t_dist = _haversine_mi(rdata.get('home_lat'), rdata.get('home_lon'),
                                        sa_lat, sa_lon)
                t_time = round(t_dist / 25.0 * 60, 1) if t_dist is not None else None

            # Resolve territory ID → name from req.Territories or fallback to SF cache
            home_terr_id = rdata.get('home_territory_id', '')
            home_terr_name = (req.get('_territory_id_to_name', {}) or {}).get(home_terr_id, home_terr_id)

            driver_verdicts.append({
                'id': f"{run_id}_{sa_id}_{rid}", 'run_id': run_id, 'sa_id': sa_id,
                'driver_id': rid, 'driver_name': rdata['name'],
                'status': status, 'exclusion_reason': reason_code,
                'travel_time_min': t_time, 'travel_dist_mi': t_dist,
                'driver_skills': ', '.join(rdata['skill_names']),
                'driver_territory': home_terr_name,
                'run_at': run_at,
            })

        # Synthetic winner verdict if winner driver wasn't in res_index
        if winner_driver_id and winner_driver_id not in res_index:
            driver_verdicts.append({
                'id': f"{run_id}_{sa_id}_{winner_driver_id}",
                'run_id': run_id, 'sa_id': sa_id,
                'driver_id': winner_driver_id,
                'driver_name': winner_driver_name or winner_driver_id,
                'status': 'winner', 'exclusion_reason': None,
                'travel_time_min': winner_travel_time, 'travel_dist_mi': winner_travel_dist,
                'driver_skills': '',
                'driver_territory': '',
                'run_at': run_at,
            })

    return run_row, sa_decisions, driver_verdicts
