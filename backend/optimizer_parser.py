"""Pure parsing: SF optimizer request/response JSON → database row dicts.

No SF I/O, no DuckDB I/O — all side-effects belong in optimizer_sync.py.
"""

from datetime import datetime

_ERROR_TRUNCATE = 500


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


def parse_run(run_id: str, run_name: str, run_at: str,
              req: dict, resp: dict,
              name_map: dict[str, str]) -> tuple[dict, list[dict], list[dict]]:
    """Parse request+response JSON → (run_row, sa_decisions, driver_verdicts).

    name_map: {resource_id: name} pre-fetched by the caller via _resolve_resource_names.
    territory_name is left blank in run_row — caller fills it after territory cache lookup.
    """

    # Territory / policy
    territories = req.get('Territories', [])
    territory_id = territories[0].get('Id', '') if territories else ''

    policy_list = req.get('SchedulingPolicy', [])
    policy = policy_list[0] if policy_list else {}
    policy_id = policy.get('Id', '')
    policy_name = policy.get('Name', '')

    # Resources index
    resources = req.get('Resources', [])
    res_index: dict[str, dict] = {}
    for r in resources:
        rid = r['Id']
        # ServiceResourceSkills is {records: [...]} not a plain list; field is SkillId
        skills = {s.get('SkillId') for s in r.get('ServiceResourceSkills', {}).get('records', [])
                  if s.get('SkillId')}
        # ServiceTerritories is {records: [...]} not a plain list
        terrs = {t.get('ServiceTerritoryId')
                 for t in r.get('ServiceTerritories', {}).get('records', [])
                 if t.get('ServiceTerritoryId')}
        res_index[rid] = {'name': name_map.get(rid, rid), 'skills': skills,
                          'territories': terrs, 'absences': []}

    # NonAvailabilities — only APPROVED absences block scheduling (FSL__Approved__c=True)
    non_avail: dict[str, list] = {}
    for na in req.get('NonAvailabilities', []):
        if not na.get('FSL__Approved__c', False):
            continue
        rid = na.get('ResourceId')
        if rid and 'Start' in na and 'End' in na:
            non_avail.setdefault(rid, []).append((na['Start'], na['End']))

    # Services (SAs)
    services: dict[str, dict] = {s['Id']: s for s in req.get('Services', [])}

    # Map each SA to its WOLI's skill requirements via WorkOrder Id.
    # Link: SA.ParentRecordId == WOLI.WorkOrderId
    woli_by_wo: dict[str, set] = {}
    for woli in req.get('WorkOrderLineItems', []):
        wo_id = woli.get('WorkOrderId', '')
        raw_srs = woli.get('SkillRequirements', [])
        if isinstance(raw_srs, dict):
            raw_srs = raw_srs.get('records', [])
        skills = {sr.get('SkillId') for sr in raw_srs if isinstance(sr, dict) and sr.get('SkillId')}
        if wo_id:
            woli_by_wo[wo_id] = woli_by_wo.get(wo_id, set()) | skills

    sa_skills: dict[str, set] = {}
    for sa_id, sa in services.items():
        wo_id = sa.get('ParentRecordId', '')
        sa_skills[sa_id] = woli_by_wo.get(wo_id, set())

    # Response indexes
    obj_changes: dict[str, dict] = resp.get('objectChanges', {})

    # Winners from assignedResourcesToUpsert — authoritative source.
    # serviceAppointments[].ServiceResources.records[] is empty for newly Scheduled SAs.
    winners: dict[str, dict] = {}
    for ar in resp.get('assignedResourcesToUpsert', []):
        sa_id = ar.get('ServiceAppointmentId')
        if sa_id:
            winners[sa_id] = ar

    # Unscheduled reason index
    unscheduled_index: dict[str, str] = {}
    for u in resp.get('unscheduledServiceAppointments', []):
        uid = u.get('serviceAppointmentId')
        if uid:
            parts = [u.get('explanation', ''), u.get('details', '')]
            unscheduled_index[uid] = ' — '.join(p for p in parts if p)[:_ERROR_TRUNCATE]

    # KPIs
    kpis = resp.get('territoryKpis', {})
    pre_kpis = kpis.get('territory_pre_opt_kpis', [{}])
    post_kpis = kpis.get('territory_post_opt_kpis', [{}])
    pre = max(pre_kpis, key=lambda k: k.get('num_tasks_scheduled', 0)) if pre_kpis else {}
    post = max(post_kpis, key=lambda k: k.get('num_tasks_scheduled', 0)) if post_kpis else {}
    horizon = req.get('TimeHorizon', {})
    unscheduled_sas = resp.get('unscheduledServiceAppointments', [])

    run_row = {
        'id': run_id, 'name': run_name, 'territory_id': territory_id,
        'territory_name': '',  # filled by caller after territory cache lookup
        'policy_id': policy_id, 'policy_name': policy_name, 'run_at': run_at,
        'horizon_start': horizon.get('Start'), 'horizon_end': horizon.get('Finish'),
        'resources_count': len(resources), 'services_count': len(services),
        'pre_scheduled': pre.get('num_tasks_scheduled', 0),
        'post_scheduled': post.get('num_tasks_scheduled', 0),
        'unscheduled_count': len(unscheduled_sas),
        'pre_travel_time_s': int(pre.get('travel_time_between', 0) or 0),
        'post_travel_time_s': int(post.get('travel_time_between', 0) or 0),
        'pre_response_avg_s': float(pre.get('response_time_avg_nonappointment', 0.0) or 0.0),
        'post_response_avg_s': float(post.get('response_time_avg_nonappointment', 0.0) or 0.0),
    }

    sa_decisions = []
    driver_verdicts = []

    for sa_id, change in obj_changes.items():
        # "Rescheduled" = successfully reassigned, map to "Scheduled"
        raw_activity = change.get('activity', '')
        action = 'Scheduled' if raw_activity in ('Scheduled', 'Rescheduled') else raw_activity

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

        winner_ar = winners.get(sa_id)
        winner_driver_id = winner_ar.get('ServiceResourceId') if winner_ar else None
        winner_driver_name = name_map.get(winner_driver_id, winner_driver_id) if winner_driver_id else None
        winner_travel_time = winner_ar.get('EstimatedTravelTime') if winner_ar else None
        winner_travel_dist = (winner_ar.get('FSL__EstimatedTravelDistanceTo__c') or None) if winner_ar else None

        sa_decisions.append({
            'id': f"{run_id}_{sa_id}", 'run_id': run_id, 'sa_id': sa_id,
            'sa_number': sa_number, 'sa_work_type': None, 'action': action,
            'unscheduled_reason': unsch_reason,
            'winner_driver_id': winner_driver_id, 'winner_driver_name': winner_driver_name,
            'winner_travel_time_min': winner_travel_time, 'winner_travel_dist_mi': winner_travel_dist,
            'run_at': run_at,
        })

        required_skills = sa_skills.get(sa_id, set())

        for rid, rdata in res_index.items():
            is_winner = (rid == winner_driver_id)
            all_absences = rdata['absences'] + non_avail.get(rid, [])

            if sa_territory_id and sa_territory_id not in rdata['territories']:
                reason_code = 'territory'
                status = 'excluded'
            elif required_skills and not required_skills.issubset(rdata['skills']):
                reason_code = 'skill'
                status = 'excluded'
            elif _is_absent(sched_start, sched_end, all_absences):
                reason_code = 'absent'
                status = 'excluded'
            elif is_winner:
                reason_code = None
                status = 'winner'
            else:
                reason_code = None
                status = 'eligible'

            t_time = winner_travel_time if is_winner else None
            t_dist = winner_travel_dist if is_winner else None

            driver_verdicts.append({
                'id': f"{run_id}_{sa_id}_{rid}", 'run_id': run_id, 'sa_id': sa_id,
                'driver_id': rid, 'driver_name': rdata['name'],
                'status': status, 'exclusion_reason': reason_code,
                'travel_time_min': t_time, 'travel_dist_mi': t_dist,
                'run_at': run_at,
            })

        # If the winner wasn't in res_index (sub-territory resource injected by SF),
        # add a synthetic winner verdict so decision trees show them correctly.
        if winner_driver_id and winner_driver_id not in res_index:
            driver_verdicts.append({
                'id': f"{run_id}_{sa_id}_{winner_driver_id}",
                'run_id': run_id, 'sa_id': sa_id,
                'driver_id': winner_driver_id,
                'driver_name': winner_driver_name or winner_driver_id,
                'status': 'winner', 'exclusion_reason': None,
                'travel_time_min': winner_travel_time, 'travel_dist_mi': winner_travel_dist,
                'run_at': run_at,
            })

    return run_row, sa_decisions, driver_verdicts
