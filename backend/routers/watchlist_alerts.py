"""Operational Alerts — Flag-based SA monitoring for the SA Watchlist.

Evaluates active SAs against 6 categories:
1. Call At Risk of Missing PTA — within 20 min of PTA due, not En Route/On Location
2. Call Not Assigned — facility account starts with '000'
3. Call Not Assigned - Rejected — status is 'Rejected'
4. Call Not Assigned - Received — status is 'Received'
5. Call Not Closed — On Location or En Route > 2 hours
6. High Priority Call Late — P1-P7 and CreatedDate > 30 min ago
"""

import logging
from datetime import datetime, timedelta, timezone

from sf_batch import batch_soql_parallel
from utils import parse_dt as _parse_dt

log = logging.getLogger('watchlist.alerts')

# Priority codes that trigger "High Priority Call Late"
_HIGH_PRIORITY_CODES = {'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7'}

# Active (non-terminal) statuses
_ACTIVE_CATEGORIES = {'None', 'Scheduled', 'Dispatched', 'InProgress', 'CheckedIn'}


def _is_tow_drop_off(sa: dict) -> bool:
    """True if SA is a Tow Drop-Off (exclude from most flags)."""
    work_type = (sa.get('WorkType') or {}).get('Name', '')
    return work_type == 'Tow Drop-Off'


def _time_in_status_from_hist(hist_list: list, current_status: str, now_utc: datetime) -> int | None:
    """Minutes since the SA entered its current status (from SAHistory)."""
    status_transitions = [
        h for h in hist_list
        if h.get('Field') == 'Status' and h.get('NewValue') == current_status
    ]
    if not status_transitions:
        return None
    last = status_transitions[-1]
    ts = _parse_dt(last.get('CreatedDate'))
    if not ts:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = round((now_utc - ts).total_seconds() / 60)
    return delta if 0 <= delta < 1440 else None


def build_operational_alerts(sas: list, sa_map: dict, hist_by_sa: dict, now_utc: datetime) -> list:
    """Evaluate all active SAs against the 6 operational flag categories.

    Returns a list of alert dicts for the UI table.
    """
    alerts = []

    for sa in sas:
        sa_id = sa.get('Id', '')
        status = sa.get('Status', '')
        status_cat = sa.get('StatusCategory', '')

        # Only active SAs
        if status_cat not in _ACTIVE_CATEGORIES:
            continue

        is_drop_off = _is_tow_drop_off(sa)
        flags_hit = []

        # ── Flag 1: Call At Risk of Missing PTA ──
        if not is_drop_off and status not in ('En Route', 'On Location'):
            pta_raw = sa.get('ERS_PTA__c')
            created = _parse_dt(sa.get('CreatedDate'))
            if pta_raw and created:
                try:
                    pta_min = float(pta_raw)
                    if 0 < pta_min <= 999:
                        if created.tzinfo is None:
                            created = created.replace(tzinfo=timezone.utc)
                        pta_due = created + timedelta(minutes=pta_min)
                        minutes_until_pta = (pta_due - now_utc).total_seconds() / 60
                        if 0 < minutes_until_pta <= 20:
                            flags_hit.append('Call At Risk of Missing PTA')
                except (TypeError, ValueError):
                    pass

        # ── Flag 2: Call Not Assigned (Facility starts with '000') ──
        if not is_drop_off:
            facility_name = (sa.get('AAA_ERS_Account_Facility__r') or {}).get('Name', '')
            if facility_name.startswith('000'):
                flags_hit.append('Call Not Assigned')

        # ── Flag 3: Call Not Assigned — Rejected ──
        if not is_drop_off and status == 'Rejected':
            flags_hit.append('Call Not Assigned - Rejected')

        # ── Flag 4: Call Not Assigned — Received ──
        if status == 'Received':
            flags_hit.append('Call Not Assigned - Received')

        # ── Flag 5: Call Not Closed ──
        if status in ('On Location', 'En Route'):
            if status == 'En Route' and is_drop_off:
                pass  # exclude drop-off from En Route check
            else:
                hist_list = hist_by_sa.get(sa_id, [])
                time_in = _time_in_status_from_hist(hist_list, status, now_utc)
                if time_in is not None and time_in > 120:
                    flags_hit.append('Call Not Closed')

        # ── Flag 6: High Priority Call Late ──
        if not is_drop_off:
            priority = (sa.get('WO_Priority_Code__c') or '').strip()
            if priority in _HIGH_PRIORITY_CODES:
                created = _parse_dt(sa.get('CreatedDate'))
                if created:
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    age_min = (now_utc - created).total_seconds() / 60
                    if age_min > 30:
                        flags_hit.append('High Priority Call Late')

        if not flags_hit:
            continue

        # Build alert entry
        territory_name = (sa.get('ServiceTerritory') or {}).get('Name', '')
        created = _parse_dt(sa.get('CreatedDate'))
        pta_delta = None
        pta_raw = sa.get('ERS_PTA__c')
        if pta_raw and created:
            try:
                pta_min = float(pta_raw)
                if 0 < pta_min <= 999:
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    pta_due = created + timedelta(minutes=pta_min)
                    pta_delta = round((now_utc - pta_due).total_seconds() / 60)
            except (TypeError, ValueError):
                pass

        for flag in flags_hit:
            alerts.append({
                'sa_id': sa.get('Id', ''),
                'sa_number': sa.get('AppointmentNumber', ''),
                'wo_number': '',  # filled later from WO query
                'wo_id': '',      # filled later
                'priority_code': (sa.get('WO_Priority_Code__c') or '').strip(),
                'gantt_label': sa.get('FSL__GanttLabel__c') or '',
                'pta_delta_min': pta_delta,
                'current_wait': None,  # filled later from WO query
                'territory': territory_name,
                'city': sa.get('City') or '',
                'flag': flag,
                'status': status,
                'latitude': sa.get('Latitude'),
                'longitude': sa.get('Longitude'),
                'created_at': sa.get('CreatedDate') or '',
            })

    # Sort: most urgent first
    _FLAG_PRIORITY = {
        'Call At Risk of Missing PTA': 0,
        'High Priority Call Late': 1,
        'Call Not Assigned': 2,
        'Call Not Assigned - Rejected': 3,
        'Call Not Assigned - Received': 4,
        'Call Not Closed': 5,
    }
    alerts.sort(key=lambda a: (_FLAG_PRIORITY.get(a['flag'], 99), -(a['pta_delta_min'] or 0)))
    return alerts


def fetch_wo_data(woli_ids: list) -> dict:
    """Fetch WorkOrder number and Current_Wait__c via WOLI IDs.

    Returns {woli_id: {wo_number, wo_id, current_wait}}.
    """
    if not woli_ids:
        return {}

    result = {}
    try:
        rows = batch_soql_parallel("""
            SELECT Id, WorkOrderId, WorkOrder.WorkOrderNumber, WorkOrder.Current_Wait__c
            FROM WorkOrderLineItem
            WHERE Id IN ('{id_list}')
        """, woli_ids, chunk_size=200)

        for r in rows:
            woli_id = r.get('Id')
            wo = r.get('WorkOrder') or {}
            result[woli_id] = {
                'wo_number': wo.get('WorkOrderNumber', ''),
                'wo_id': r.get('WorkOrderId', ''),
                'current_wait': wo.get('Current_Wait__c'),
            }
    except Exception as e:
        log.warning(f"Failed to fetch WO data for alerts: {e}")

    return result
