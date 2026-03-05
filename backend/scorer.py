"""Garage Performance Scoring Engine.

8 dimensions weighted to a composite 0-100 score.
All data from Salesforce — no assumptions.
"""

from datetime import datetime, timedelta
from collections import defaultdict
from sf_client import sf_query_all, sf_query
from cache import cached_query

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


def _parse_dt(dt_str):
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(
            dt_str.replace('+0000', '+00:00').replace('Z', '+00:00'))
    except Exception:
        return None


def _to_eastern(dt_str):
    dt = _parse_dt(dt_str)
    return (dt - timedelta(hours=5)) if dt else None


def _score_dimension(actual, target, higher_better):
    """Score a dimension 0-100."""
    if actual is None:
        return None
    if higher_better:
        # e.g., SLA hit rate: actual=0.6, target=1.0 → score = 60
        return min(100, round((actual / max(target, 0.001)) * 100, 1))
    else:
        # e.g., median response: actual=60, target=45 → over by 15, score = 100 - (15/45)*100 = 66.7
        if actual <= target:
            return 100
        return max(0, round(100 * (1 - (actual - target) / max(target, 0.001)), 1))


def compute_score(territory_id: str, weeks: int = 4) -> dict:
    """Compute all 8 scoring dimensions for a garage."""
    days = weeks * 7

    # ── 1. SAs with timing data ──────────────────────────────────────────
    cache_key = f"scorer_sas_{territory_id}_{days}"
    sas = cached_query(cache_key, lambda: sf_query_all(f"""
        SELECT Id, CreatedDate, Status, WorkType.Name,
               ActualStartTime, SchedStartTime, ERS_PTA__c,
               ERS_Cancellation_Reason__c
        FROM ServiceAppointment
        WHERE ServiceTerritoryId = '{territory_id}'
          AND CreatedDate = LAST_N_DAYS:{days}
          AND Status IN ('Dispatched', 'Completed', 'Canceled',
                         'Cancel Call - Service Not En Route', 'Cancel Call - Service En Route',
                         'Unable to Complete', 'Assigned', 'No-Show')
        ORDER BY CreatedDate ASC
    """), ttl=300)

    if not sas:
        return {'error': 'No SAs found', 'dimensions': {}, 'composite': None}

    total = len(sas)
    completed = [s for s in sas if s.get('Status') == 'Completed']
    canceled = [s for s in sas if 'Cancel' in (s.get('Status') or '')]

    # ── 2. SLA Hit Rate (actual response ≤ 45 min) ──────────────────────
    response_times = []
    for s in completed:
        created = _to_eastern(s.get('CreatedDate'))
        started = _to_eastern(s.get('ActualStartTime'))
        if created and started:
            diff = (started - created).total_seconds() / 60
            if 0 < diff < 1440:
                response_times.append(diff)

    under_45 = sum(1 for r in response_times if r <= 45)
    sla_hit_rate = under_45 / max(len(response_times), 1)
    median_response = sorted(response_times)[len(response_times) // 2] if response_times else None

    # ── 3. Completion Rate ───────────────────────────────────────────────
    completion_rate = len(completed) / max(total, 1)

    # ── 4. PTA Accuracy (promised ≤45 AND delivered ≤45) ─────────────────
    pta_values = []
    pta_accurate = 0
    for s in sas:
        pta = s.get('ERS_PTA__c')
        if pta is not None:
            pv = float(pta)
            pta_values.append(pv)

    # For PTA accuracy, need SAs where PTA ≤45 AND actual response ≤45
    for s in completed:
        pta = s.get('ERS_PTA__c')
        if pta is not None and float(pta) <= 45:
            created = _to_eastern(s.get('CreatedDate'))
            started = _to_eastern(s.get('ActualStartTime'))
            if created and started:
                diff = (started - created).total_seconds() / 60
                if 0 < diff <= 45:
                    pta_accurate += 1

    pta_promised_under_45 = sum(1 for v in pta_values if v <= 45)
    pta_accuracy = pta_accurate / max(pta_promised_under_45, 1) if pta_promised_under_45 > 0 else None

    # ── 5. "Could Not Wait" Cancellation Rate ────────────────────────────
    could_not_wait = sum(1 for s in sas
                         if (s.get('ERS_Cancellation_Reason__c') or '').lower().startswith('member could not wait'))
    cnw_rate = could_not_wait / max(total, 1)

    # ── 6. Dispatch Speed (CreatedDate → SchedStartTime) ─────────────────
    dispatch_times = []
    for s in sas:
        created = _to_eastern(s.get('CreatedDate'))
        sched = _to_eastern(s.get('SchedStartTime'))
        if created and sched:
            diff = (sched - created).total_seconds() / 60
            if 0 <= diff < 1440:
                dispatch_times.append(diff)
    median_dispatch = sorted(dispatch_times)[len(dispatch_times) // 2] if dispatch_times else None

    # ── 7. Facility Decline Rate ─────────────────────────────────────────
    cache_key_decl = f"scorer_decl_{territory_id}_{days}"
    decline_count = cached_query(cache_key_decl, lambda: sf_query(f"""
        SELECT COUNT(Id) cnt FROM ServiceAppointment
        WHERE ServiceTerritoryId = '{territory_id}'
          AND CreatedDate = LAST_N_DAYS:{days}
          AND ERS_Facility_Decline_Reason__c != null
    """), ttl=300)['records'][0]['cnt']
    decline_rate = decline_count / max(total, 1)

    # ── 8. Customer Satisfaction (via WorkOrder linkage) ──────────────────
    cache_key_sat = f"scorer_sat_{territory_id}_{days}"

    def _get_satisfaction():
        # Get WO numbers directly from WorkOrder table for this territory
        wo_recs = sf_query_all(f"""
            SELECT WorkOrderNumber
            FROM WorkOrder
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate = LAST_N_DAYS:{days}
              AND WorkOrderNumber != null
        """)
        wo_nums = list(set(
            r.get('WorkOrderNumber', '')
            for r in wo_recs if r.get('WorkOrderNumber')
        ))
        if not wo_nums:
            return None

        total_sat = 0
        totally_satisfied = 0
        # Batch query surveys
        for i in range(0, len(wo_nums), 100):
            batch = wo_nums[i:i+100]
            wo_list = ",".join(f"'{w}'" for w in batch)
            surveys = sf_query_all(f"""
                SELECT ERS_Overall_Satisfaction__c
                FROM Survey_Result__c
                WHERE ERS_Work_Order_Number__c IN ({wo_list})
                  AND ERS_Overall_Satisfaction__c != null
            """)
            for sv in surveys:
                sat = sv.get('ERS_Overall_Satisfaction__c', '')
                total_sat += 1
                if sat.lower() == 'totally satisfied':
                    totally_satisfied += 1
        if total_sat == 0:
            return None
        return {'total_surveys': total_sat, 'totally_satisfied': totally_satisfied,
                'rate': totally_satisfied / total_sat}

    sat_data = cached_query(cache_key_sat, _get_satisfaction, ttl=600)
    satisfaction_rate = sat_data['rate'] if sat_data else None

    # ── Score each dimension ─────────────────────────────────────────────
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

        # Format actual for display
        if actual is None:
            display = 'N/A'
        elif key in ('sla_hit_rate', 'completion_rate', 'satisfaction', 'pta_accuracy', 'could_not_wait', 'decline_rate'):
            display = f"{round(actual * 100, 1)}%"
        elif key in ('median_response', 'dispatch_speed'):
            display = f"{round(actual)} min"
        else:
            display = str(round(actual, 2))

        # Format target
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

    # Letter grade
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
        'dimensions': dimensions,
        'sample_sizes': {
            'total_sas': total,
            'completed': len(completed),
            'with_response_time': len(response_times),
            'with_pta': len(pta_values),
            'with_dispatch_time': len(dispatch_times),
            'surveys': sat_data['total_surveys'] if sat_data else 0,
            'declines': decline_count,
        },
    }
