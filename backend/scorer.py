"""Garage Performance Scoring Engine.

8 dimensions weighted to a composite 0-100 score.
All data live from Salesforce (parallel SOQL).
"""

from datetime import datetime, date, timedelta
from collections import defaultdict
from sf_client import sf_query_all, sf_parallel, sanitize_soql
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


def _score_dimension(actual, target, higher_better):
    if actual is None:
        return None
    if higher_better:
        return min(100, round((actual / max(target, 0.001)) * 100, 1))
    else:
        if actual <= target:
            return 100
        return max(0, round(100 * (1 - (actual - target) / max(target, 0.001)), 1))


def _parse_dt(dt_str):
    if not dt_str:
        return None
    if isinstance(dt_str, datetime):
        return dt_str
    try:
        return datetime.fromisoformat(
            str(dt_str).replace('+0000', '+00:00').replace('Z', '+00:00'))
    except Exception:
        return None


def compute_score(territory_id: str, weeks: int = 4) -> dict:
    """Compute all 8 scoring dimensions. Parallel SOQL queries."""
    territory_id = sanitize_soql(territory_id)
    days = weeks * 7
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    since = f"{cutoff}T00:00:00Z"

    cache_key = f"scorer_{territory_id}_{days}"

    def _compute():
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
            # Individual: only Field Services completed with ActualStartTime
            # (Towbook ActualStartTime is bulk-updated at midnight — not real arrival)
            completed=lambda: sf_query_all(f"""
                SELECT CreatedDate, SchedStartTime, ActualStartTime, ERS_PTA__c
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Status = 'Completed'
                  AND ActualStartTime != null
                  AND ERS_Dispatch_Method__c = 'Field Services'
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
            # WO numbers for surveys (limited to 1000 most recent)
            wo_nums=lambda: sf_query_all(f"""
                SELECT WorkOrderNumber FROM WorkOrder
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                ORDER BY CreatedDate DESC
                LIMIT 1000
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
        response_times = []
        for s in completed_sas:
            created = _parse_dt(s.get('CreatedDate'))
            started = _parse_dt(s.get('ActualStartTime'))
            if created and started:
                diff = (started - created).total_seconds() / 60
                if 0 < diff < 1440:
                    response_times.append(diff)

        under_45 = sum(1 for r in response_times if r <= 45)
        sla_hit_rate = under_45 / max(len(response_times), 1)
        median_response = sorted(response_times)[len(response_times) // 2] if response_times else None

        # Completion Rate
        completion_rate = completed_count / max(total, 1)

        # PTA Accuracy (from individual completed SAs)
        # Measures: did the driver arrive within the promised PTA window?
        pta_values = []
        pta_accurate = 0
        pta_evaluated = 0
        for s in completed_sas:
            pta = s.get('ERS_PTA__c')
            if pta is not None:
                pv = float(pta)
                pta_values.append(pv)
                created = _parse_dt(s.get('CreatedDate'))
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

        # Satisfaction — use WO numbers from parallel query (single batch, max 500)
        satisfaction_rate = None
        total_surveys = 0
        totally_satisfied = 0
        wo_nums = [r.get('WorkOrderNumber') for r in data.get('wo_nums', []) if r.get('WorkOrderNumber')]
        if wo_nums:
            num_list = ",".join(f"'{w}'" for w in wo_nums[:500])
            try:
                all_surveys = sf_query_all(f"""
                    SELECT ERS_Overall_Satisfaction__c, COUNT(Id) cnt
                    FROM Survey_Result__c
                    WHERE ERS_Work_Order_Number__c IN ({num_list})
                    GROUP BY ERS_Overall_Satisfaction__c
                """)
                for sv in all_surveys:
                    sat = (sv.get('ERS_Overall_Satisfaction__c') or '').lower()
                    cnt = sv.get('cnt', 1)
                    total_surveys += cnt
                    if sat == 'totally satisfied':
                        totally_satisfied += cnt
                if total_surveys > 0:
                    satisfaction_rate = totally_satisfied / total_surveys
            except Exception:
                pass  # Score still works without satisfaction

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
            'dimensions': dimensions,
            'sample_sizes': {
                'total_sas': total,
                'completed': completed_count,
                'with_response_time': len(response_times),
                'with_pta': len(pta_values),
                'with_dispatch_time': len(dispatch_times),
                'surveys': total_surveys,
                'declines': decline_count,
            },
        }

    return cached_query(cache_key, _compute, ttl=1800)  # 30 min — historical data doesn't change fast
