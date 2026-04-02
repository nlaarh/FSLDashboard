"""Garage Performance Scoring Engine.

8 dimensions weighted to a composite 0-100 score.
All data live from Salesforce (parallel SOQL).
"""

from datetime import datetime, date, timedelta
from collections import defaultdict

from utils import parse_dt as _parse_dt, is_fleet_territory
from sf_client import sf_query_all, sf_parallel, sanitize_soql
from cache import cached_query_persistent

# ── Dimension weights ────────────────────────────────────────────────────────
DIMENSIONS = {
    'sla_hit_rate':       {'weight': 0.30, 'target': 1.0,  'higher_better': True,  'label': '45-Min SLA Hit Rate'},
    'completion_rate':    {'weight': 0.15, 'target': 0.95, 'higher_better': True,  'label': 'Completion Rate'},
    'satisfaction':       {'weight': 0.15, 'target': 0.82, 'higher_better': True,  'label': 'Customer Satisfaction'},
    'median_response':    {'weight': 0.10, 'target': 45,   'higher_better': False, 'label': 'Median Response Time'},
    'pta_accuracy':       {'weight': 0.10, 'target': 0.90, 'higher_better': True,  'label': 'PTA Accuracy'},
    'could_not_wait':     {'weight': 0.10, 'target': 0.03, 'higher_better': False, 'label': '"Could Not Wait" Rate'},
    'dispatch_speed':     {'weight': 0.05, 'target': 5,    'higher_better': False, 'label': 'Dispatch Speed (min)'},
    'decline_rate':       {'weight': 0.05, 'target': 0.02, 'higher_better': False, 'label': 'Facility Decline Rate'},
}


def _score_dimension(actual, target, higher_better):
    if actual is None:
        return None
    if higher_better:
        return min(100, round((actual / max(target, 0.001)) * 100, 1))
    else:
        if actual <= target:
            return 100
        return max(0, round(100 * (1 - (actual - target) / max(target, 0.001)), 1))


def compute_score(territory_id: str, weeks: int = 4) -> dict:
    """Compute all 8 scoring dimensions. Parallel SOQL queries."""
    territory_id = sanitize_soql(territory_id)
    days = weeks * 7
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    since = f"{cutoff}T00:00:00Z"

    cache_key = f"scorer_{territory_id}_{days}"

    def _compute():
        # Get territory name for fleet/contractor classification
        _t_rows = sf_query_all(f"SELECT Name FROM ServiceTerritory WHERE Id = '{territory_id}' LIMIT 1")
        territory_name = _t_rows[0].get('Name', '') if _t_rows else ''
        _is_fleet = is_fleet_territory(territory_name)

        # All parallel: aggregates for counts, individual only for completed SAs
        data = sf_parallel(
            # Aggregate: total by status
            status_counts=lambda: sf_query_all(f"""
                SELECT Status, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Status IN ('Dispatched','Completed','Canceled',
                                 'Cancel Call - Service Not En Route',
                                 'Cancel Call - Service En Route',
                                 'Unable to Complete','Assigned','No-Show')
                  AND WorkType.Name != 'Tow Drop-Off'
                GROUP BY Status
            """),
            # Individual completed SAs for response time analysis
            completed=lambda: sf_query_all(f"""
                SELECT Id, CreatedDate, SchedStartTime, ActualStartTime,
                       ERS_PTA__c, ERS_Dispatch_Method__c
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Status = 'Completed'
                  AND WorkType.Name != 'Tow Drop-Off'
                ORDER BY CreatedDate DESC
                LIMIT 500
            """),
            # Aggregate: could not wait count
            cnw=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND ERS_Cancellation_Reason__c LIKE 'Member Could Not Wait%'
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            # Aggregate: decline count
            declines=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND ERS_Facility_Decline_Reason__c != null
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            # Towbook on-location (single cross-object query, no chunking)
            tb_on_loc=lambda: sf_query_all(f"""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE Field = 'Status'
                  AND ServiceAppointment.ServiceTerritoryId = '{territory_id}'
                  AND ServiceAppointment.CreatedDate >= {since}
                  AND ServiceAppointment.ERS_Dispatch_Method__c = 'Towbook'
                  AND ServiceAppointment.Status = 'Completed'
                  AND ServiceAppointment.WorkType.Name != 'Tow Drop-Off'
            """),
            # Survey satisfaction (aggregate — no WO lookup needed)
            surveys=lambda: sf_query_all(f"""
                SELECT ERS_Overall_Satisfaction__c, COUNT(Id) cnt
                FROM Survey_Result__c
                WHERE ERS_Work_Order__r.ServiceTerritoryId = '{territory_id}'
                  AND ERS_Work_Order__r.CreatedDate >= {since}
                  AND ERS_Overall_Satisfaction__c != null
                GROUP BY ERS_Overall_Satisfaction__c
            """),
        )



        # Total from aggregate
        total = sum(r.get('cnt', 0) for r in data['status_counts'])
        if total == 0:
            return {'error': 'No SAs found', 'dimensions': {}, 'composite': None}

        completed_count = sum(r.get('cnt', 0) for r in data['status_counts']
                              if r.get('Status') == 'Completed')
        completed_sas = data['completed']

        # SLA Hit Rate + Median Response (from individual completed SAs)
        # Towbook ActualStartTime is a fake future estimate. Real arrival is
        # the 'On Location' status change from ServiceAppointmentHistory.
        # Fleet garages use ActualStartTime directly.
        # Fleet = territory 100*/800*. Everything else = contractor.
        # Contractor sub-type: Towbook (ERS_Dispatch_Method__c='Towbook') vs On-Platform (Field Services)
        tb_count = sum(1 for s in completed_sas if (s.get('ERS_Dispatch_Method__c') or '') == 'Towbook')
        is_towbook = not _is_fleet and tb_count > len(completed_sas) * 0.5

        # Build Towbook on-location map from parallel query result
        towbook_on_loc = {}
        for r in data.get('tb_on_loc', []):
            if r.get('NewValue') == 'On Location':
                sid = r.get('ServiceAppointmentId')
                if sid and sid not in towbook_on_loc:
                    towbook_on_loc[sid] = r['CreatedDate']

        response_times = []
        for s in completed_sas:
            created = _parse_dt(s.get('CreatedDate'))
            dispatch_method = (s.get('ERS_Dispatch_Method__c') or '')

            if dispatch_method == 'Towbook':
                # Towbook: use real on-location time from history
                on_loc_str = towbook_on_loc.get(s.get('Id'))
                on_loc = _parse_dt(on_loc_str)
                if created and on_loc:
                    diff = (on_loc - created).total_seconds() / 60
                    if 0 < diff < 1440:
                        response_times.append(diff)
            else:
                # Fleet: use ActualStartTime
                started = _parse_dt(s.get('ActualStartTime'))
                if created and started:
                    diff = (started - created).total_seconds() / 60
                    if 0 < diff < 1440:
                        response_times.append(diff)

        effective_times = response_times  # Used for SLA and median below

        under_45 = sum(1 for r in effective_times if r <= 45)
        sla_hit_rate = under_45 / max(len(effective_times), 1)
        median_response = sorted(effective_times)[len(effective_times) // 2] if effective_times else None

        # Completion Rate
        completion_rate = completed_count / max(total, 1)

        # PTA Accuracy (from individual completed SAs)
        # Measures: did the driver arrive within the promised PTA window?
        # Towbook: use real on-location time from history.
        # Fleet: use ActualStartTime.
        pta_values = []
        pta_accurate = 0
        pta_evaluated = 0
        for s in completed_sas:
            pta = s.get('ERS_PTA__c')
            if pta is not None:
                pv = float(pta)
                if pv <= 0 or pv >= 999:
                    continue  # skip sentinel/invalid PTA values
                pta_values.append(pv)
                dispatch_method = (s.get('ERS_Dispatch_Method__c') or '')
                created = _parse_dt(s.get('CreatedDate'))
                if dispatch_method == 'Towbook':
                    on_loc_str = towbook_on_loc.get(s.get('Id'))
                    started = _parse_dt(on_loc_str)
                else:
                    started = _parse_dt(s.get('ActualStartTime'))
                if created and started:
                    diff = (started - created).total_seconds() / 60
                    if 0 < diff < 480:
                        pta_evaluated += 1
                        if diff <= pv:
                            pta_accurate += 1

        pta_accuracy = pta_accurate / max(pta_evaluated, 1) if pta_evaluated > 0 else None

        # Could Not Wait Rate (from aggregate)
        cnw_count = data['cnw'][0].get('cnt', 0) if data['cnw'] else 0
        cnw_rate = cnw_count / max(total, 1)

        # Dispatch Speed (from individual completed SAs)
        # SchedStartTime is set by the scheduler, not Towbook — usable for both
        dispatch_times = []
        for s in completed_sas:
            created = _parse_dt(s.get('CreatedDate'))
            sched = _parse_dt(s.get('SchedStartTime'))
            if created and sched:
                diff = (sched - created).total_seconds() / 60
                if 0 <= diff < 1440:
                    dispatch_times.append(diff)
        median_dispatch = sorted(dispatch_times)[len(dispatch_times) // 2] if dispatch_times else None

        # Decline Rate (from aggregate)
        decline_count = data['declines'][0].get('cnt', 0) if data['declines'] else 0
        decline_rate = decline_count / max(total, 1)

        # Satisfaction — from parallel survey query (no WO lookup needed)
        satisfaction_rate = None
        total_surveys = 0
        totally_satisfied = 0
        for sv in data.get('surveys', []):
            sat = (sv.get('ERS_Overall_Satisfaction__c') or '').lower()
            cnt = sv.get('cnt', 1)
            total_surveys += cnt
            if sat == 'totally satisfied':
                totally_satisfied += cnt
        if total_surveys > 0:
            satisfaction_rate = totally_satisfied / total_surveys

        # Score each dimension
        actuals = {
            'sla_hit_rate': sla_hit_rate,
            'completion_rate': completion_rate,
            'satisfaction': satisfaction_rate,
            'median_response': median_response,
            'pta_accuracy': pta_accuracy,
            'could_not_wait': cnw_rate,
            'dispatch_speed': median_dispatch,
            'decline_rate': decline_rate,
        }

        dimensions = {}
        weighted_total = 0
        weight_sum = 0

        for key, cfg in DIMENSIONS.items():
            actual = actuals.get(key)
            score = _score_dimension(actual, cfg['target'], cfg['higher_better'])

            if actual is None:
                display = 'N/A'
            elif key in ('sla_hit_rate', 'completion_rate', 'satisfaction', 'pta_accuracy', 'could_not_wait', 'decline_rate'):
                display = f"{round(actual * 100, 1)}%"
            elif key in ('median_response', 'dispatch_speed'):
                display = f"{round(actual)} min"
            else:
                display = str(round(actual, 2))

            if key in ('sla_hit_rate', 'completion_rate', 'satisfaction', 'pta_accuracy'):
                target_display = f"{round(cfg['target'] * 100)}%"
            elif key in ('could_not_wait', 'decline_rate'):
                target_display = f"< {round(cfg['target'] * 100)}%"
            elif key in ('median_response', 'dispatch_speed'):
                target_display = f"≤ {cfg['target']} min"
            else:
                target_display = str(cfg['target'])

            dimensions[key] = {
                'label': cfg['label'],
                'weight': cfg['weight'],
                'weight_pct': f"{round(cfg['weight'] * 100)}%",
                'actual': actual,
                'actual_display': display,
                'target': cfg['target'],
                'target_display': target_display,
                'score': score,
                'met': score is not None and score >= 80,
            }

            if score is not None:
                weighted_total += score * cfg['weight']
                weight_sum += cfg['weight']

        composite = round(weighted_total / max(weight_sum, 0.01), 1) if weight_sum > 0 else None

        if composite is None:
            grade = '?'
        elif composite >= 90:
            grade = 'A'
        elif composite >= 80:
            grade = 'B'
        elif composite >= 70:
            grade = 'C'
        elif composite >= 60:
            grade = 'D'
        else:
            grade = 'F'

        return {
            'composite': composite,
            'grade': grade,
            'garage_type': 'fleet' if _is_fleet else ('towbook' if is_towbook else 'contractor'),
            'dimensions': dimensions,
            'sample_sizes': {
                'total_sas': total,
                'completed': completed_count,
                'with_response_time': len(effective_times),
                'with_pta': len(pta_values),
                'with_dispatch_time': len(dispatch_times),
                'surveys': total_surveys,
                'declines': decline_count,
            },
        }

    return cached_query_persistent(cache_key, _compute, max_stale_hours=26)
