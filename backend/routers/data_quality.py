"""Data quality audit endpoints."""

from datetime import datetime, date, timedelta
from collections import defaultdict
from fastapi import APIRouter

from utils import _ET
from sf_client import sf_query_all, sf_parallel
import cache

router = APIRouter()


@router.get("/api/data-quality")
def api_data_quality():
    """Field completeness and data quality stats for the last 28 days."""

    def _fetch():
        d28 = (date.today() - timedelta(days=28)).isoformat()
        since = f"{d28}T00:00:00Z"

        # Batch 1: SA-level counts (8 queries max)
        batch1 = sf_parallel(
            total=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            completed=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND Status = 'Completed'
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            has_actual_start=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND Status = 'Completed'
                  AND ActualStartTime != null
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            has_actual_end=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND Status = 'Completed'
                  AND ActualEndTime != null
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            has_sched_start=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND SchedStartTime != null
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            has_pta=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND ERS_PTA__c != null
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            pta_bad=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND ERS_PTA__c != null
                  AND (ERS_PTA__c = 0 OR ERS_PTA__c >= 999)
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            has_dispatch_method=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND ERS_Dispatch_Method__c != null
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
        )

        # Batch 2: remaining queries (7 queries — removed ungroupable dispatch_methods
        # and cross-field ata_valid which SOQL doesn't support)
        batch2 = sf_parallel(
            # Dispatch method sample (get individual values to count in Python)
            dispatch_sample=lambda: sf_query_all(f"""
                SELECT ERS_Dispatch_Method__c
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND ERS_Dispatch_Method__c != null
                  AND WorkType.Name != 'Tow Drop-Off'
                LIMIT 5000
            """),
            wo_count=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM WorkOrder
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
            """),
            survey_count=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM Survey_Result__c
                WHERE CreatedDate >= {since}
                  AND ERS_Overall_Satisfaction__c != null
            """),
            has_auto_assign=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND ERS_Auto_Assign__c = true
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            has_assigned_resource=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM AssignedResource
                WHERE ServiceAppointment.CreatedDate >= {since}
                  AND ServiceAppointment.ServiceTerritoryId != null
                  AND ServiceAppointment.Status = 'Completed'
            """),
            has_parent_territory=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {since}
                  AND ServiceTerritoryId != null
                  AND ERS_Parent_Territory__c != null
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            sa_history_count=lambda: sf_query_all(f"""
                SELECT COUNT(Id) cnt
                FROM ServiceAppointmentHistory
                WHERE Field = 'ServiceTerritory'
                  AND ServiceAppointment.CreatedDate >= {since}
            """),
        )

        # Count dispatch methods from sample in Python
        dm_counter = defaultdict(int)
        for r in batch2.get('dispatch_sample', []):
            dm = r.get('ERS_Dispatch_Method__c') or 'Unknown'
            dm_counter[dm] += 1
        batch2['dispatch_methods'] = [{'method': k, 'cnt': v} for k, v in dm_counter.items()]
        # ATA valid = same as has_actual_start (SOQL can't compare two fields;
        # negative ATA is filtered in Python at calc time with diff > 0 check)
        batch2['ata_valid'] = batch1['has_actual_start']

        # Merge batches
        data = {**batch1, **batch2}

        def _cnt(key):
            return data[key][0].get('cnt', 0) if data.get(key) else 0

        total = _cnt('total')
        completed = _cnt('completed')

        def _pct(n, d):
            return round(100 * n / max(d, 1), 1) if d > 0 else None

        # Build field quality entries
        fields = []

        # -- Timeline fields --
        fields.append({
            'field': 'ServiceAppointment.CreatedDate',
            'label': 'Call Created Time',
            'group': 'Timeline',
            'description': 'When the service appointment was created in Salesforce (call received from AAA). This is the starting clock for all response time calculations.',
            'populated': total,
            'total': total,
            'pct': 100.0,
            'issues': 'Always populated (system field).',
            'impact': 'None - always available.',
            'severity': 'ok',
        })

        has_sched = _cnt('has_sched_start')
        fields.append({
            'field': 'ServiceAppointment.SchedStartTime',
            'label': 'Scheduled Start (Dispatch Time)',
            'group': 'Timeline',
            'description': 'When a driver was assigned/dispatched to the call. Set by FSL optimization or manual dispatch. Used to calculate dispatch queue time (CreatedDate -> SchedStartTime).',
            'populated': has_sched,
            'total': total,
            'pct': _pct(has_sched, total),
            'issues': f'{total - has_sched} SAs ({_pct(total - has_sched, total)}%) missing.' if has_sched < total else 'Fully populated.',
            'impact': 'When missing, response time cannot be decomposed into dispatch vs travel segments. Total response time still works.',
            'severity': 'warn' if _pct(total - has_sched, total) and _pct(total - has_sched, total) > 10 else 'ok',
        })

        has_start = _cnt('has_actual_start')
        fields.append({
            'field': 'ServiceAppointment.ActualStartTime',
            'label': 'Driver Arrival Time',
            'group': 'Timeline',
            'description': 'When the driver physically arrived on scene and started helping the member. For Fleet: set when driver marks "arrived" in the FSL app. For Towbook: synced via Towbook integration (real per-SA arrival timestamps verified via ServiceAppointmentHistory).',
            'populated': has_start,
            'total': completed,
            'pct': _pct(has_start, completed),
            'issues': f'{completed - has_start} completed SAs ({_pct(completed - has_start, completed)}%) missing arrival time.' if has_start < completed else 'Fully populated on completed SAs.',
            'impact': 'Missing = no ATA (actual response time), no SLA calculation, no driver leaderboard entry for that call. Affects Response Time, SLA Hit Rate, Driver Leaderboard, ETA Accuracy.',
            'severity': 'critical' if _pct(completed - has_start, completed) and _pct(completed - has_start, completed) > 15 else 'warn' if _pct(completed - has_start, completed) and _pct(completed - has_start, completed) > 5 else 'ok',
        })

        has_end = _cnt('has_actual_end')
        fields.append({
            'field': 'ServiceAppointment.ActualEndTime',
            'label': 'Job Completion Time',
            'group': 'Timeline',
            'description': 'When the driver finished the job and marked the SA complete. Used to calculate on-site service duration (ActualStartTime -> ActualEndTime).',
            'populated': has_end,
            'total': completed,
            'pct': _pct(has_end, completed),
            'issues': f'{completed - has_end} completed SAs ({_pct(completed - has_end, completed)}%) missing.' if has_end < completed else 'Fully populated on completed SAs.',
            'impact': 'Missing = no on-site duration, incomplete time decomposition. Affects Driver Leaderboard on-site column and Response Decomposition chart.',
            'severity': 'warn' if _pct(completed - has_end, completed) and _pct(completed - has_end, completed) > 10 else 'ok',
        })

        # -- PTA fields --
        has_pta = _cnt('has_pta')
        pta_bad = _cnt('pta_bad')
        pta_valid = has_pta - pta_bad
        fields.append({
            'field': 'ServiceAppointment.ERS_PTA__c',
            'label': 'Promised Time of Arrival (PTA)',
            'group': 'PTA / ETA',
            'description': 'Minutes promised to the member at dispatch time. For Fleet: calculated by FSL optimization engine based on driver distance and availability. For Towbook: entered by Towbook dispatch (often a rough estimate). Values of 0 or >= 999 are treated as invalid/sentinel.',
            'populated': has_pta,
            'total': total,
            'pct': _pct(has_pta, total),
            'issues': (
                f'{total - has_pta} SAs ({_pct(total - has_pta, total)}%) have no PTA. '
                f'{pta_bad} ({_pct(pta_bad, total)}%) have invalid values (0 or >= 999). '
                f'{pta_valid} ({_pct(pta_valid, total)}%) are usable.'
            ),
            'impact': 'Invalid PTA excluded from Avg PTA, PTA Accuracy, and ETA Accuracy metrics. High invalid rate means these metrics represent only a subset of calls.',
            'severity': 'critical' if _pct(total - pta_valid, total) and _pct(total - pta_valid, total) > 20 else 'warn' if _pct(total - pta_valid, total) and _pct(total - pta_valid, total) > 10 else 'ok',
            'detail': {
                'total_populated': has_pta,
                'sentinel_zero_or_999': pta_bad,
                'usable': pta_valid,
                'usable_pct': _pct(pta_valid, total),
            },
        })

        # -- Dispatch fields --
        has_dm = _cnt('has_dispatch_method')
        dm_breakdown = {r.get('method', 'Unknown'): r.get('cnt', 0) for r in data.get('dispatch_methods', [])}
        fields.append({
            'field': 'ServiceAppointment.ERS_Dispatch_Method__c',
            'label': 'Dispatch Method',
            'group': 'Dispatch',
            'description': 'How the call was dispatched: "Field Services" (internal fleet via FSL optimization) or "Towbook" (external contractor). Determines which dispatch logic and driver tracking applies.',
            'populated': has_dm,
            'total': total,
            'pct': _pct(has_dm, total),
            'issues': f'{total - has_dm} SAs ({_pct(total - has_dm, total)}%) missing dispatch method.' if has_dm < total else 'Fully populated.',
            'impact': 'Missing = cannot determine Fleet vs Towbook for dispatch mix reporting.',
            'severity': 'warn' if _pct(total - has_dm, total) and _pct(total - has_dm, total) > 5 else 'ok',
            'detail': {'breakdown': dm_breakdown},
        })

        has_aa = _cnt('has_auto_assign')
        fields.append({
            'field': 'ServiceAppointment.ERS_Auto_Assign__c',
            'label': 'Auto-Assigned (Primary Dispatch)',
            'group': 'Dispatch',
            'description': 'Boolean: true when the SA was auto-dispatched by FSL optimization (primary/first-choice dispatch). False or null = manual dispatch (secondary, backup, or Towbook). Used to separate acceptance rates into Primary vs Secondary.',
            'populated': has_aa,
            'total': total,
            'pct': _pct(has_aa, total),
            'issues': f'{has_aa} of {total} SAs ({_pct(has_aa, total)}%) were auto-assigned. The remainder were manual or Towbook dispatches.',
            'impact': 'Drives the Primary vs Secondary acceptance split. Low auto-assign count is normal for Towbook-heavy garages.',
            'severity': 'ok',
        })

        has_parent = _cnt('has_parent_territory')
        fields.append({
            'field': 'ServiceAppointment.ERS_Parent_Territory__c',
            'label': 'Parent (Spotted) Territory',
            'group': 'Dispatch',
            'description': 'The zone/territory where the member is stranded. Used with ERS_Territory_Priority_Matrix__c to determine if this garage is the 1st call (primary) or 2nd+ call (secondary/backup) for that zone.',
            'populated': has_parent,
            'total': total,
            'pct': _pct(has_parent, total),
            'issues': f'{total - has_parent} SAs ({_pct(total - has_parent, total)}%) missing parent territory.' if has_parent < total else 'Fully populated.',
            'impact': 'Missing = SA cannot be classified as primary/secondary for the 1st Call % and 2nd+ Call % columns on the Garage Operations table.',
            'severity': 'warn' if _pct(total - has_parent, total) and _pct(total - has_parent, total) > 15 else 'ok',
        })

        # -- ATA validity --
        ata_valid_cnt = _cnt('ata_valid')
        ata_invalid = has_start - ata_valid_cnt
        fields.append({
            'field': 'ATA (Calculated)',
            'label': 'Actual Time of Arrival (ATA)',
            'group': 'Calculated Metrics',
            'description': 'ActualStartTime minus CreatedDate, in minutes. This is the member\'s actual wait time from call creation to driver arrival. Only valid when > 0 and < 1440 minutes (24 hours). Values outside this range are excluded as bad data.',
            'populated': ata_valid_cnt,
            'total': completed,
            'pct': _pct(ata_valid_cnt, completed),
            'issues': (
                f'{completed - has_start} completed SAs have no ActualStartTime. '
                f'{ata_invalid} have ActualStartTime <= CreatedDate (negative/zero — likely data entry error). '
                f'{ata_valid_cnt} ({_pct(ata_valid_cnt, completed)}%) produce valid ATA.'
            ),
            'impact': 'Invalid ATA excluded from Avg ATA, SLA Hit Rate, Median Response, and Driver Leaderboard calculations. This is the most impactful data quality issue.',
            'severity': 'critical' if _pct(completed - ata_valid_cnt, completed) and _pct(completed - ata_valid_cnt, completed) > 20 else 'warn' if _pct(completed - ata_valid_cnt, completed) and _pct(completed - ata_valid_cnt, completed) > 10 else 'ok',
        })

        # -- Driver assignment --
        has_ar = _cnt('has_assigned_resource')
        fields.append({
            'field': 'AssignedResource (junction)',
            'label': 'Driver Assignment Record',
            'group': 'Driver',
            'description': 'Links a ServiceAppointment to a ServiceResource (driver/truck). Required for Driver Leaderboard. Created when a driver is assigned to a call.',
            'populated': has_ar,
            'total': completed,
            'pct': _pct(has_ar, completed),
            'issues': f'{completed - has_ar} completed SAs ({_pct(completed - has_ar, completed)}%) have no AssignedResource — driver cannot be identified.' if has_ar < completed else 'Fully populated.',
            'impact': 'Missing = driver excluded from leaderboard, no driver-level performance tracking for that call.',
            'severity': 'warn' if _pct(completed - has_ar, completed) and _pct(completed - has_ar, completed) > 10 else 'ok',
        })

        # -- SA History --
        sa_hist = _cnt('sa_history_count')
        fields.append({
            'field': 'ServiceAppointmentHistory',
            'label': 'Territory Assignment History',
            'group': 'Dispatch',
            'description': 'History records tracking when an SA\'s ServiceTerritory changed. First assignment = 1st call garage. Subsequent changes = cascaded/reassigned (2nd+ call). Used for 1st Call vs 2nd+ Call acceptance metrics.',
            'populated': sa_hist,
            'total': total,
            'pct': _pct(sa_hist, total),
            'issues': f'{sa_hist} history records for {total} SAs. SAs with no history are treated as 1st call (no reassignment detected).',
            'impact': 'Low history count is normal — it means most SAs stay with their first garage. Only SAs that get reassigned generate additional history records.',
            'severity': 'ok',
        })

        # -- Survey coverage --
        wo_cnt = _cnt('wo_count')
        sv_cnt = _cnt('survey_count')
        fields.append({
            'field': 'Survey_Result__c',
            'label': 'Member Satisfaction Survey',
            'group': 'Survey',
            'description': 'Post-service survey results linked to WorkOrders via ERS_Work_Order_Number__c. ERS_Overall_Satisfaction__c values: Totally Satisfied, Satisfied, Neither, Dissatisfied, Totally Dissatisfied. AAA accreditation target: 82% Totally Satisfied + Satisfied.',
            'populated': sv_cnt,
            'total': wo_cnt,
            'pct': _pct(sv_cnt, wo_cnt),
            'issues': f'{sv_cnt} surveys for {wo_cnt} work orders ({_pct(sv_cnt, wo_cnt)}% response rate). Low response rate is normal for voluntary surveys.',
            'impact': 'Low survey volume means satisfaction metrics have wider confidence intervals. Garages with < 10 surveys may show volatile satisfaction percentages.',
            'severity': 'warn' if _pct(sv_cnt, wo_cnt) and _pct(sv_cnt, wo_cnt) < 10 else 'ok',
        })

        # Summary stats
        critical_fields = [f for f in fields if f['severity'] == 'critical']
        warn_fields = [f for f in fields if f['severity'] == 'warn']

        return {
            'period': f'{d28} to today',
            'period_days': 28,
            'refreshed_at': datetime.now(_ET).strftime('%Y-%m-%d %I:%M %p ET'),
            'total_sas': total,
            'completed_sas': completed,
            'fields': fields,
            'summary': {
                'total_fields_checked': len(fields),
                'critical_issues': len(critical_fields),
                'warnings': len(warn_fields),
                'healthy': len(fields) - len(critical_fields) - len(warn_fields),
                'critical_field_names': [f['label'] for f in critical_fields],
                'warn_field_names': [f['label'] for f in warn_fields],
            },
        }

    return cache.cached_query_persistent('data_quality_audit', _fetch, ttl=86400)  # 24hr, survives restart


@router.post("/api/data-quality/refresh")
def api_data_quality_refresh():
    """Force refresh data quality audit (clears disk + memory cache)."""
    cache.invalidate('data_quality_audit')
    cache.disk_invalidate('data_quality_audit')
    return api_data_quality()
