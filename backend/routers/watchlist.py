"""Dispatch Watchlist — SAs requiring dispatcher attention.

Auto-includes SAs that were manually reassigned by a human dispatcher,
had driver rejections, or experienced dispatch thrash (3+ driver assignments).
Auto-drops SAs completed/canceled for more than 5 minutes.
Only shows SAs from the last 24 hours.

Pure helper functions live in watchlist_helpers.py (keeps this file under 600 lines).
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

import cache
import users as _users
from sf_client import sf_query_all, sf_parallel
from sf_batch import batch_soql_parallel
from utils import parse_dt as _parse_dt
from routers.watchlist_alerts import build_operational_alerts, fetch_wo_data, enrich_alerts_with_kmi
from routers.auth import get_request_username
from routers.watchlist_helpers import (
    _TERMINAL_STATUSES, _RESOLVED_STATUSES,
    _evaluate_criteria, _build_entry, _build_phases,
    _time_in_status, _compute_flag, _sort_key,
)

router = APIRouter()
log = logging.getLogger('watchlist')

CACHE_KEY = 'dispatch_watchlist'
CACHE_TTL = 30


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.get("/api/watchlist")
def api_watchlist(request: Request):
    """SAs that dispatchers should be closely following.

    Auto-follow: manual reassignment, driver rejection, or dispatch thrash.
    Auto-drop: completed/canceled > 5 minutes ago.
    Contractors: scoped to their assigned territories only.
    """
    # Determine contractor territory scope
    username = get_request_username(request)
    user = _users.get_user(username) if username else None
    territories: list[str] = (user.get("territories") or []) if user and user.get("role") == "contractor" else []

    # Contractor-scoped requests bypass shared cache (their slice is user-specific)
    if not territories:
        cached = cache.get(CACHE_KEY)
        if cached:
            return cached
        cached = cache.disk_get(CACHE_KEY, CACHE_TTL)
        if cached:
            cache.put(CACHE_KEY, cached, CACHE_TTL)
            return cached

    try:
        result = _build_watchlist(territories=territories)
    except Exception as e:
        log.error(f"Watchlist build failed: {e}", exc_info=True)
        if not territories:
            stale = cache.get_stale(CACHE_KEY) or cache.disk_get_stale(CACHE_KEY)
            if stale:
                return stale
        return {'watchlist': [], 'total': 0, 'last_updated': None, 'error': str(e)}

    if not territories:
        cache.put(CACHE_KEY, result, CACHE_TTL)
        cache.disk_put(CACHE_KEY, result, CACHE_TTL)
    return result


# ── Build watchlist ──────────────────────────────────────────────────────────

def _build_watchlist(territories: list[str] | None = None) -> dict:
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = (now_utc - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
    # Keep terminal calls only if they changed very recently (UI only needs a short
    # grace window to show "Completed Xm ago" before auto-drop).
    cutoff_recent_terminal = (now_utc - timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Build territory filter clause for contractor scoping
    territory_clause = ""
    if territories:
        ids = ", ".join(f"'{t}'" for t in territories)
        territory_clause = f"AND ServiceTerritoryId IN ({ids})"

    # ── Query 1: Active + recently completed SAs (last 24h) ──
    sas = sf_query_all(f"""
        SELECT Id, AppointmentNumber, Status, StatusCategory,
               ServiceTerritoryId, ServiceTerritory.Name,
               WorkType.Name, WorkTypeId, ERS_PTA__c, Description,
               ERS_Tow_Pick_Up_Drop_off__c, ParentRecordId,
               WO_Priority_Code__c, FSL__GanttLabel__c,
               AAA_ERS_Account_Facility__c, AAA_ERS_Account_Facility__r.Name,
               AAA_ERS_Account_Facility__r.Phone,
               AccountId, Account.Name, Account.PersonMobilePhone, Account.Phone,
               Phone, Mobile_Phone__c,
               ERS_Parent_Territory__c, ERS_Parent_Territory__r.Name,
               CreatedDate, SchedStartTime, ActualStartTime, ActualEndTime,
               LastModifiedDate, Street, City, Latitude, Longitude
        FROM ServiceAppointment
        WHERE RecordType.Name = 'ERS Service Appointment'
          AND ServiceTerritoryId != null
          AND CreatedDate >= {cutoff_24h}
          {territory_clause}
          AND (
                StatusCategory IN ('None', 'Scheduled', 'Dispatched', 'InProgress', 'CheckedIn')
                OR (
                    StatusCategory IN ('Completed', 'Canceled')
                    AND LastModifiedDate >= {cutoff_recent_terminal}
                )
          )
        ORDER BY CreatedDate ASC
    """)

    if not sas:
        return {'watchlist': [], 'total': 0, 'last_updated': now_utc.isoformat()}

    sa_map = {s['Id']: s for s in sas}
    sa_ids = list(sa_map.keys())

    # ── Queries 2 & 3: AssignedResource + SAHistory in parallel ──
    def _q_assigned():
        return batch_soql_parallel("""
            SELECT Id, ServiceAppointmentId,
                   ServiceResource.Name, ServiceResource.Id,
                   ServiceResource.ERS_Tech_ID__c,
                   ServiceResource.ERS_Driver_Type__c,
                   ServiceResource.LastKnownLatitude,
                   ServiceResource.LastKnownLongitude,
                   CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name
            FROM AssignedResource
            WHERE ServiceAppointmentId IN ('{id_list}')
            ORDER BY CreatedDate ASC
        """, sa_ids, chunk_size=200)

    def _q_history():
        return batch_soql_parallel("""
            SELECT ServiceAppointmentId, Field, OldValue, NewValue,
                   CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointmentId IN ('{id_list}')
              AND Field IN ('Status', 'ERS_Assigned_Resource__c')
            ORDER BY CreatedDate ASC
        """, sa_ids, chunk_size=200)

    data = sf_parallel(assigned=_q_assigned, history=_q_history)
    ar_rows = data['assigned']
    hist_rows = data['history']

    # ── Index data by SA ──
    ar_by_sa = defaultdict(list)       # sa_id -> [AssignedResource records]
    hist_by_sa = defaultdict(list)     # sa_id -> [SAHistory records]

    for r in ar_rows:
        sa_id = r.get('ServiceAppointmentId')
        if sa_id:
            ar_by_sa[sa_id].append(r)

    for r in hist_rows:
        sa_id = r.get('ServiceAppointmentId')
        if sa_id:
            hist_by_sa[sa_id].append(r)

    # ── Evaluate each SA against watchlist criteria ──
    entries = []
    for sa_id, sa in sa_map.items():
        # Auto-drop: terminal status AND ActualEndTime > 5 min ago
        status = sa.get('Status', '')
        if status in _TERMINAL_STATUSES:
            end_dt = _parse_dt(sa.get('ActualEndTime'))
            if end_dt:
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                if (now_utc - end_dt).total_seconds() > 300:
                    continue
            else:
                # No ActualEndTime but terminal — use LastModifiedDate as fallback
                mod_dt = _parse_dt(sa.get('LastModifiedDate'))
                if mod_dt:
                    if mod_dt.tzinfo is None:
                        mod_dt = mod_dt.replace(tzinfo=timezone.utc)
                    if (now_utc - mod_dt).total_seconds() > 300:
                        continue

        ar_list = ar_by_sa.get(sa_id, [])
        hist_list = hist_by_sa.get(sa_id, [])

        reasons, flags = _evaluate_criteria(ar_list, hist_list)

        if not reasons:
            continue

        # Auto-drop: En Route/On-Scene — concern resolved unless driver is aging
        if status in _RESOLVED_STATUSES:
            tis = _time_in_status(hist_list, status, now_utc)
            if _compute_flag(status, tis) != 'aging':
                continue

        entry = _build_entry(sa, ar_list, hist_list, reasons, flags, now_utc, sa_map)
        entries.append(entry)

    # ── Sort: active flagged first, then by reassignment count, completed last ──
    entries.sort(key=_sort_key)

    # ── Operational Alerts (new flag-based table) ──
    operational_alerts = build_operational_alerts(sas, sa_map, hist_by_sa, now_utc)

    # ── Enrich alerts with WO data + phases for timeline hover ──
    if operational_alerts:
        woli_ids = list({sa_map[a['sa_id']].get('ParentRecordId')
                        for a in operational_alerts
                        if a['sa_id'] in sa_map and sa_map[a['sa_id']].get('ParentRecordId')})
        wo_data = fetch_wo_data(woli_ids) if woli_ids else {}
        for alert in operational_alerts:
            sa = sa_map.get(alert['sa_id'], {})
            woli_id = sa.get('ParentRecordId', '')
            wo_info = wo_data.get(woli_id, {})
            alert['wo_number'] = wo_info.get('wo_number', '')
            alert['wo_id'] = wo_info.get('wo_id', '')
            alert['current_wait'] = wo_info.get('current_wait')
            # Vehicle from WO
            v_parts = [p for p in [wo_info.get('vehicle_make', ''), wo_info.get('vehicle_model', '')] if p]
            alert['vehicle'] = ' '.join(v_parts)
            alert['vehicle_plate'] = wo_info.get('vehicle_plate', '')
            # Add phases for SAWithTimeline hover
            hist_list = hist_by_sa.get(alert['sa_id'], [])
            alert['phases'] = _build_phases(hist_list, alert['status'], now_utc)
            alert['work_type'] = (sa.get('WorkType') or {}).get('Name', '')
            alert['work_type_id'] = sa.get('WorkTypeId') or ''
        enrich_alerts_with_kmi(operational_alerts)

    return {
        'watchlist': entries,
        'total': len(entries),
        'operational_alerts': operational_alerts,
        'last_updated': now_utc.isoformat(),
    }
