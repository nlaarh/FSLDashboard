"""Watchlist data pull: everything the Watchlist needs, read from Salesforce in as few requests as possible.

One query returns the appointments of the last 24 h together with their drivers (AssignedResource), their
Status / driver-change history and their work order (through ParentRecord -> WorkOrderLineItem -> WorkOrder).
That replaces the old chain of appointments -> drivers + history -> duplicate candidates -> RAP lookup -> work-order
lookup (6 stages, 8-10 requests). The result is a plain "snapshot" dict; routers/watchlist.py turns it into alerts
with pure Python (no Salesforce), once for everybody and once per contractor territory scope.

The work order is reached through ParentRecord (WOLI) exactly as before, never through ERS_Work_Order__c
(16 % of appointments have a WOLI parent but an empty ERS_Work_Order__c).
"""

import logging
from datetime import datetime, timedelta, timezone

from routers.watchlist_alerts import find_no_sa_wos
from sf_batch import batch_soql_parallel
from sf_client import sf_query_all
from utils import parse_dt as _parse_dt

log = logging.getLogger('watchlist.snapshot')

_ACTIVE_CATEGORIES = ('None', 'Scheduled', 'Dispatched', 'InProgress', 'CheckedIn')

_SNAPSHOT_SOQL = """
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
           LastModifiedDate, Street, City, Latitude, Longitude,
           TYPEOF ParentRecord WHEN WorkOrderLineItem THEN
               WorkOrderId, WorkOrder.WorkOrderNumber, WorkOrder.Current_Wait__c,
               WorkOrder.Vehicle_Make__c, WorkOrder.Vehicle_Model__c, WorkOrder.License_Plate__c,
               WorkOrder.Type__c, WorkOrder.Customer_Name__c,
               WorkOrder.ERS_Unable_To_Complete_Dupe__c, WorkOrder.CreatedDate, WorkOrder.ServiceTerritory.Name
           END,
           (SELECT Id, ServiceAppointmentId,
                   ServiceResource.Name, ServiceResource.Id,
                   ServiceResource.ERS_Tech_ID__c,
                   ServiceResource.ERS_Driver_Type__c,
                   ServiceResource.LastKnownLatitude,
                   ServiceResource.LastKnownLongitude,
                   CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name
            FROM ServiceResources ORDER BY CreatedDate ASC),
           (SELECT ServiceAppointmentId, Field, OldValue, NewValue,
                   CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name
            FROM Histories
            WHERE Field IN ('Status', 'ERS_Assigned_Resource__c') ORDER BY CreatedDate ASC)
    FROM ServiceAppointment
    WHERE RecordType.Name = 'ERS Service Appointment'
      AND ServiceTerritoryId != null
      AND CreatedDate >= {cutoff_24h}
      AND (
            StatusCategory IN ('None', 'Scheduled', 'Dispatched', 'InProgress', 'CheckedIn')
            OR (
                StatusCategory IN ('Completed', 'Canceled')
                AND LastModifiedDate >= {cutoff_recent_terminal}
            )
      )
    ORDER BY CreatedDate ASC
"""

# Fallbacks for the (very rare) appointment whose child list did not fit in the one response.
_AR_SOQL = """
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
"""
_HIST_SOQL = """
    SELECT ServiceAppointmentId, Field, OldValue, NewValue,
           CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name
    FROM ServiceAppointmentHistory
    WHERE ServiceAppointmentId IN ('{id_list}')
      AND Field IN ('Status', 'ERS_Assigned_Resource__c')
    ORDER BY CreatedDate ASC
"""


# Active appointments that have no territory at all (the base read requires one). Only the territory flag looks at them,
# so no drivers/history here. CreatedDate is the indexed filter (explain: Index on CreatedDate, relative cost 0.01).
_UNROUTED_SOQL = """
    SELECT Id, AppointmentNumber, Status, StatusCategory,
           ServiceTerritoryId, ServiceTerritory.Name,
           WorkType.Name, WorkTypeId, ERS_PTA__c, ParentRecordId,
           WO_Priority_Code__c, FSL__GanttLabel__c,
           AccountId, Account.Name, Account.PersonMobilePhone, Account.Phone,
           Phone, Mobile_Phone__c, CreatedDate, SchedStartTime, LastModifiedDate,
           Street, City, Latitude, Longitude,
           TYPEOF ParentRecord WHEN WorkOrderLineItem THEN
               WorkOrderId, WorkOrder.WorkOrderNumber, WorkOrder.Current_Wait__c,
               WorkOrder.Vehicle_Make__c, WorkOrder.Vehicle_Model__c, WorkOrder.License_Plate__c,
               WorkOrder.Type__c, WorkOrder.Customer_Name__c, WorkOrder.ServiceTerritory.Name
           END
    FROM ServiceAppointment
    WHERE RecordType.Name = 'ERS Service Appointment'
      AND ServiceTerritoryId = null
      AND CreatedDate >= {cutoff_24h}
      AND StatusCategory IN ('None', 'Scheduled', 'Dispatched', 'InProgress', 'CheckedIn')
"""

# Scheduled Start changes of the few candidates only (a day of them across all appointments is >2,000 rows).
_SCHED_HIST_SOQL = """
    SELECT ServiceAppointmentId, OldValue, NewValue, CreatedDate
    FROM ServiceAppointmentHistory
    WHERE ServiceAppointmentId IN ('{id_list}') AND Field = 'SchedStartTime'
    ORDER BY CreatedDate ASC
"""

SCHED_GRACE_SEC = 300      # an appointment younger than this is still being set up


def _iso(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _children(row: dict, name: str) -> tuple[list, bool]:
    """(child rows, complete?) of a sub-select; Salesforce returns null when there are none."""
    block = row.get(name)
    if not block:
        return [], True
    return list(block.get('records') or []), bool(block.get('done', True)) and not block.get('nextRecordsUrl')


def split_rows(rows: list[dict]) -> tuple[list, dict, dict, dict, set]:
    """Salesforce rows -> (plain SA rows, drivers by SA, history by SA, work-order info by WOLI, SAs with cut-off children).

    The plain SA rows look exactly like the old appointment query's rows (no child lists, no ParentRecord block).
    Work-order info per WOLI id also carries the RAP fields and the 'do not flag as duplicate' flag."""
    sas, ar_by_sa, hist_by_sa, wo_by_woli, truncated = [], {}, {}, {}, set()
    for row in rows:
        sa = {k: v for k, v in row.items() if k not in ('ServiceResources', 'Histories', 'ParentRecord')}
        sas.append(sa)
        sa_id = sa['Id']
        ars, ar_done = _children(row, 'ServiceResources')
        hist, hist_done = _children(row, 'Histories')
        if not (ar_done and hist_done):
            truncated.add(sa_id)
        ar_by_sa[sa_id] = ars
        hist_by_sa[sa_id] = hist
        parent = row.get('ParentRecord') or {}
        woli_id = sa.get('ParentRecordId')
        if woli_id and parent.get('WorkOrderId') is not None:
            wo_by_woli[woli_id] = {'wo_id': parent.get('WorkOrderId', ''), 'wo': parent.get('WorkOrder') or {}}
    return sas, ar_by_sa, hist_by_sa, wo_by_woli, truncated


def _fix_truncated(truncated: set, ar_by_sa: dict, hist_by_sa: dict) -> None:
    """Re-read, the old way, the appointments whose driver/history list was cut off in the one big response."""
    ids = sorted(truncated)
    log.warning("Watchlist: %d appointment(s) had incomplete child lists, re-reading them separately", len(ids))
    fresh_ar, fresh_hist = {i: [] for i in ids}, {i: [] for i in ids}
    for r in batch_soql_parallel(_AR_SOQL, ids, chunk_size=200):
        fresh_ar.setdefault(r.get('ServiceAppointmentId'), []).append(r)
    for r in batch_soql_parallel(_HIST_SOQL, ids, chunk_size=200):
        fresh_hist.setdefault(r.get('ServiceAppointmentId'), []).append(r)
    ar_by_sa.update(fresh_ar)
    hist_by_sa.update(fresh_hist)


def duplicate_candidates(sas: list, wo_by_woli: dict, now_utc: datetime) -> list:
    """The appointments the Potential Duplicate flag looks at, same rules the old dedicated query had:
    active, not a Tow Drop-Off, and not on a work order marked 'unable to complete dupe' (work order created in the
    last 24 h). Rows are cut down to the fields that query selected."""
    cutoff = now_utc - timedelta(hours=24)
    out = []
    for sa in sas:
        if sa.get('StatusCategory') not in _ACTIVE_CATEGORIES:
            continue
        if ((sa.get('WorkType') or {}).get('Name')) == 'Tow Drop-Off':
            continue
        wo = (wo_by_woli.get(sa.get('ParentRecordId')) or {}).get('wo') or {}
        wo_created = _parse_dt(wo.get('CreatedDate'))
        if wo.get('ERS_Unable_To_Complete_Dupe__c') is True and wo_created and wo_created >= cutoff:
            continue
        out.append({k: sa.get(k) for k in
                    ('Id', 'AccountId', 'AppointmentNumber', 'Latitude', 'Longitude', 'Street', 'ParentRecordId')})
    return out


def fetch_unrouted(cutoff_24h: str) -> tuple[list, dict]:
    """(appointments, work-order info by WOLI) for active appointments with no territory. A failed read skips the flag."""
    try:
        sas, _, _, wo_by_woli, _ = split_rows(sf_query_all(_UNROUTED_SOQL.format(cutoff_24h=cutoff_24h)))
        return sas, wo_by_woli
    except Exception as e:
        log.warning("Watchlist: no-territory read failed, skipping that flag: %s", e)
        return [], {}


def sched_cleared_ids(sas: list, now_utc: datetime) -> set:
    """Appointments whose Scheduled Start was cleared and is still blank: active, not a Tow Drop-Off, older than
    SCHED_GRACE_SEC, SchedStartTime empty now, and the LATEST Scheduled Start history row went from a value to blank
    (a later row that set it again means it is fine). Only the blank ones are looked up, so this is one small read,
    and none when there are no candidates. A failed read skips the flag."""
    cands = []
    for sa in sas:
        created = _parse_dt(sa.get('CreatedDate'))
        if (sa.get('StatusCategory') in _ACTIVE_CATEGORIES and not sa.get('SchedStartTime') and created
                and ((sa.get('WorkType') or {}).get('Name')) != 'Tow Drop-Off'
                and (now_utc - created).total_seconds() > SCHED_GRACE_SEC):
            cands.append(sa['Id'])
    if not cands:
        return set()
    try:
        rows = batch_soql_parallel(_SCHED_HIST_SOQL, cands, chunk_size=200)
    except Exception as e:
        log.warning("Watchlist: Scheduled Start history read failed, skipping that flag: %s", e)
        return set()
    latest = {}
    for r in sorted(rows, key=lambda r: r.get('CreatedDate') or ''):
        latest[r.get('ServiceAppointmentId')] = r
    return {i for i, r in latest.items() if r.get('OldValue') and not r.get('NewValue')}


def fetch_snapshot(now_utc: datetime | None = None) -> dict:
    """Read everything the Watchlist needs: 1 request for the appointments (+ drivers, history, work orders),
    1 for Submitted work orders with no appointment (+ 0-3 more only for the few still unresolved),
    1 for active appointments without a territory, and 1 for the Scheduled Start history of the few blank-start ones."""
    now_utc = now_utc or datetime.now(timezone.utc)
    cutoff_24h = _iso(now_utc - timedelta(hours=24))
    cutoff_recent_terminal = _iso(now_utc - timedelta(minutes=15))

    rows = sf_query_all(_SNAPSHOT_SOQL.format(cutoff_24h=cutoff_24h, cutoff_recent_terminal=cutoff_recent_terminal))
    sas, ar_by_sa, hist_by_sa, wo_by_woli, truncated = split_rows(rows)
    if truncated:
        _fix_truncated(truncated, ar_by_sa, hist_by_sa)

    unrouted_sas, unrouted_wo = fetch_unrouted(cutoff_24h)
    wo_by_woli.update(unrouted_wo)

    # Work orders that already have an appointment in this pull need no further check.
    wo_ids_with_sa = {v['wo_id'] for v in wo_by_woli.values() if v.get('wo_id')}
    return {
        'now': now_utc,
        'sas': sas,
        'ar_by_sa': ar_by_sa,
        'hist_by_sa': hist_by_sa,
        'wo_by_woli': wo_by_woli,
        'dup_candidates': duplicate_candidates(sas, wo_by_woli, now_utc),
        'unrouted_sas': unrouted_sas,
        'sched_cleared': sched_cleared_ids(sas, now_utc),
        'no_sa_wos': find_no_sa_wos(now_utc, wo_ids_with_sa),
    }
