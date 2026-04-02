"""DuckDB sync functions — split from db.py.

Contains: dynamic table sync (SAs, ARs, WOs, shifts, absences, surveys),
seed, incremental sync, and status. Uses core functions from db.py.
"""

import os, time as _time
from datetime import datetime, date, timedelta, timezone

from sf_client import sf_query_all, refresh_auth
from db import (
    get_con, query, query_scalar, execute,
    _get_last_sync, _set_last_sync,
    _LOCAL_DIR, _DB_PATH, is_seeded,
    _sync_static,
)


# ── Dynamic table sync (chunked by date) ────────────────────────────────────

def _sync_service_appointments(since: str, until: str, log=print):
    """Pull SAs in 7-day chunks. since/until are YYYY-MM-DD strings."""
    con = get_con()
    start = date.fromisoformat(since)
    end = date.fromisoformat(until)
    total = 0

    while start < end:
        chunk_end = min(start + timedelta(days=7), end)
        log(f"  SAs: {start} -> {chunk_end}...")
        recs = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, CreatedDate,
                   SchedStartTime, SchedEndTime,
                   ActualStartTime, ActualEndTime,
                   FSL__Duration_In_Minutes__c,
                   Street, City, State, PostalCode, Latitude, Longitude,
                   ServiceTerritoryId, WorkTypeId,
                   ERS_PTA__c, ERS_Dispatch_Method__c, ERS_Auto_Assign__c,
                   ERS_Cancellation_Reason__c, ERS_Facility_Decline_Reason__c,
                   Off_Platform_Truck_Id__c,
                   ERS_Dispatched_Geolocation__Latitude__s,
                   ERS_Dispatched_Geolocation__Longitude__s,
                   FSL__Schedule_Mode__c, FSL__Auto_Schedule__c
            FROM ServiceAppointment
            WHERE CreatedDate >= {start.isoformat()}T00:00:00Z
              AND CreatedDate < {chunk_end.isoformat()}T00:00:00Z
            ORDER BY CreatedDate ASC
        """)
        for r in recs:
            con.execute(
                "INSERT OR REPLACE INTO service_appointments VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    r['Id'], r.get('AppointmentNumber'), r.get('Status'),
                    r.get('CreatedDate'), r.get('SchedStartTime'), r.get('SchedEndTime'),
                    r.get('ActualStartTime'), r.get('ActualEndTime'),
                    r.get('FSL__Duration_In_Minutes__c'),
                    r.get('Street'), r.get('City'), r.get('State'), r.get('PostalCode'),
                    r.get('Latitude'), r.get('Longitude'),
                    r.get('ServiceTerritoryId'), None,  # territory_name filled later
                    None, r.get('WorkTypeId'), None,  # wt_name + wo_id filled later
                    r.get('ERS_PTA__c'), r.get('ERS_Dispatch_Method__c'),
                    r.get('ERS_Auto_Assign__c'),
                    r.get('ERS_Cancellation_Reason__c'),
                    r.get('ERS_Facility_Decline_Reason__c'),
                    r.get('Off_Platform_Truck_Id__c'),
                    r.get('ERS_Dispatched_Geolocation__Latitude__s'),
                    r.get('ERS_Dispatched_Geolocation__Longitude__s'),
                    r.get('FSL__Schedule_Mode__c'), r.get('FSL__Auto_Schedule__c'),
                    None, None,  # account name/phone filled later
                ])
        total += len(recs)
        log(f"    -> {len(recs)} SAs ({total} cumulative)")
        start = chunk_end

    # Fill in territory_name and work_type_name from cached lookup tables
    if total > 0:
        log("  Backfilling territory names & work type names...")
        con.execute("""
            UPDATE service_appointments sa SET territory_name = (
                SELECT st.name FROM service_territories st WHERE st.id = sa.territory_id
            ) WHERE sa.territory_name IS NULL AND sa.territory_id IS NOT NULL
        """)
        con.execute("""
            UPDATE service_appointments sa SET work_type_name = (
                SELECT wt.name FROM work_types wt WHERE wt.id = sa.work_type_id
            ) WHERE sa.work_type_name IS NULL AND sa.work_type_id IS NOT NULL
        """)
        log("  Backfill complete.")

    _set_last_sync('service_appointments', datetime.now(timezone.utc), total)
    return total


def _sync_assigned_resources(since: str, until: str, log=print):
    """Pull AssignedResources in 7-day chunks."""
    con = get_con()
    start = date.fromisoformat(since)
    end = date.fromisoformat(until)
    total = 0

    while start < end:
        chunk_end = min(start + timedelta(days=7), end)
        log(f"  ARs: {start} -> {chunk_end}...")
        recs = sf_query_all(f"""
            SELECT Id, ServiceAppointmentId, ServiceResourceId,
                   EstimatedTravelTime, ActualTravelTime, CreatedDate
            FROM AssignedResource
            WHERE CreatedDate >= {start.isoformat()}T00:00:00Z
              AND CreatedDate < {chunk_end.isoformat()}T00:00:00Z
            ORDER BY CreatedDate ASC
        """)
        for r in recs:
            con.execute(
                "INSERT OR REPLACE INTO assigned_resources VALUES (?,?,?,?,?,?,?)",
                [
                    r['Id'], r.get('ServiceAppointmentId'),
                    r.get('ServiceResourceId'), None,  # name filled from service_resources
                    r.get('EstimatedTravelTime'), r.get('ActualTravelTime'),
                    r.get('CreatedDate'),
                ])
        total += len(recs)
        start = chunk_end

    if total > 0:
        log("  Backfilling resource names...")
        con.execute("""
            UPDATE assigned_resources ar SET resource_name = (
                SELECT sr.name FROM service_resources sr WHERE sr.id = ar.resource_id
            ) WHERE ar.resource_name IS NULL AND ar.resource_id IS NOT NULL
        """)

    _set_last_sync('assigned_resources', datetime.now(timezone.utc), total)
    return total


def _sync_work_orders(since: str, until: str, log=print):
    con = get_con()
    start = date.fromisoformat(since)
    end = date.fromisoformat(until)
    total = 0

    while start < end:
        chunk_end = min(start + timedelta(days=7), end)
        log(f"  WOs: {start} -> {chunk_end}...")
        recs = sf_query_all(f"""
            SELECT Id, WorkOrderNumber, ServiceTerritoryId, CreatedDate
            FROM WorkOrder
            WHERE CreatedDate >= {start.isoformat()}T00:00:00Z
              AND CreatedDate < {chunk_end.isoformat()}T00:00:00Z
        """)
        for r in recs:
            con.execute(
                "INSERT OR REPLACE INTO work_orders VALUES (?,?,?,?)",
                [r['Id'], r.get('WorkOrderNumber'),
                 r.get('ServiceTerritoryId'), r.get('CreatedDate')])
        total += len(recs)
        start = chunk_end

    _set_last_sync('work_orders', datetime.now(timezone.utc), total)
    return total


def _sync_shifts(since: str, until: str, log=print):
    con = get_con()
    log(f"  Shifts: {since} -> {until}...")
    recs = sf_query_all(f"""
        SELECT Id, ServiceResourceId, StartTime, EndTime,
               StatusCategory, ServiceTerritoryId
        FROM Shift
        WHERE StartTime >= {since}T00:00:00Z
          AND EndTime <= {until}T23:59:59Z
    """)
    for r in recs:
        con.execute(
            "INSERT OR REPLACE INTO shifts VALUES (?,?,?,?,?,?)",
            [r['Id'], r.get('ServiceResourceId'),
             r.get('StartTime'), r.get('EndTime'),
             r.get('StatusCategory'), r.get('ServiceTerritoryId')])
    _set_last_sync('shifts', datetime.now(timezone.utc), len(recs))
    log(f"    -> {len(recs)} shifts")
    return len(recs)


def _sync_absences(since: str, until: str, log=print):
    con = get_con()
    log(f"  Absences: {since} -> {until}...")
    recs = sf_query_all(f"""
        SELECT Id, ResourceId, Start, End, Type
        FROM ResourceAbsence
        WHERE Start <= {until}T23:59:59Z
          AND End >= {since}T00:00:00Z
    """)
    for r in recs:
        con.execute(
            "INSERT OR REPLACE INTO resource_absences VALUES (?,?,?,?,?,?)",
            [r['Id'], r.get('ResourceId'), None,  # name from service_resources
             r.get('Start'), r.get('End'), r.get('Type')])
    _set_last_sync('resource_absences', datetime.now(timezone.utc), len(recs))
    log(f"    -> {len(recs)} absences")
    return len(recs)


def _sync_surveys(since: str, until: str, log=print):
    con = get_con()
    start = date.fromisoformat(since)
    end = date.fromisoformat(until)
    total = 0

    while start < end:
        chunk_end = min(start + timedelta(days=7), end)
        log(f"  Surveys: {start} -> {chunk_end}...")
        recs = sf_query_all(f"""
            SELECT Id, ERS_Work_Order_Number__c,
                   ERS_Overall_Satisfaction__c,
                   ERS_Response_Time_Satisfaction__c,
                   ERS_Technician_Satisfaction__c,
                   ERS_NPS__c, ERS_NPS_Group__c,
                   CreatedDate
            FROM Survey_Result__c
            WHERE CreatedDate >= {start.isoformat()}T00:00:00Z
              AND CreatedDate < {chunk_end.isoformat()}T00:00:00Z
        """)
        for r in recs:
            con.execute(
                "INSERT OR REPLACE INTO surveys VALUES (?,?,?,?,?,?,?,?)",
                [r['Id'], r.get('ERS_Work_Order_Number__c'),
                 r.get('ERS_Overall_Satisfaction__c'),
                 r.get('ERS_Response_Time_Satisfaction__c'),
                 r.get('ERS_Technician_Satisfaction__c'),
                 r.get('ERS_NPS__c'), r.get('ERS_NPS_Group__c'),
                 r.get('CreatedDate')])
        total += len(recs)
        start = chunk_end

    _set_last_sync('surveys', datetime.now(timezone.utc), total)
    return total


# ── Seed (first run) ────────────────────────────────────────────────────────

def seed(since: str = '2026-01-01', until: str | None = None, log=print):
    """Full seed from Salesforce. Pulls since -> today."""
    if until is None:
        until = date.today().isoformat()

    refresh_auth()
    t0 = _time.time()
    log(f"=== Seeding DuckDB: {since} -> {until} ===")

    # Static tables first
    _sync_static(log=log)

    # Dynamic tables (chunked)
    log("\n--- Dynamic tables ---")
    sa_count = _sync_service_appointments(since, until, log=log)
    ar_count = _sync_assigned_resources(since, until, log=log)
    wo_count = _sync_work_orders(since, until, log=log)
    sh_count = _sync_shifts(since, until, log=log)
    ab_count = _sync_absences(since, until, log=log)
    sv_count = _sync_surveys(since, until, log=log)

    elapsed = round(_time.time() - t0)
    log(f"\n=== Seed complete in {elapsed}s ===")
    log(f"  SAs: {sa_count}, ARs: {ar_count}, WOs: {wo_count}")
    log(f"  Shifts: {sh_count}, Absences: {ab_count}, Surveys: {sv_count}")

    # Report DB size
    db_size = os.path.getsize(_DB_PATH) / 1024 / 1024
    log(f"  DB size: {db_size:.1f} MB")

    return {
        'elapsed_sec': elapsed,
        'service_appointments': sa_count,
        'assigned_resources': ar_count,
        'work_orders': wo_count,
        'shifts': sh_count,
        'absences': ab_count,
        'surveys': sv_count,
        'db_size_mb': round(db_size, 1),
    }


# ── Incremental sync ────────────────────────────────────────────────────────

def sync(log=print):
    """Incremental sync — pulls only new/changed records since last sync."""
    refresh_auth()
    t0 = _time.time()
    now = date.today()
    log(f"=== Incremental sync ===")

    # Static tables: always full replace (they're tiny)
    _sync_static(log=log)

    # Dynamic tables: from last sync to today
    last = _get_last_sync('service_appointments')
    if last:
        since = (last.date() - timedelta(days=1)).isoformat()
    else:
        since = '2026-01-01'
    until = (now + timedelta(days=1)).isoformat()

    log(f"\n--- Incremental since {since} ---")
    sa_count = _sync_service_appointments(since, until, log=log)
    ar_count = _sync_assigned_resources(since, until, log=log)
    wo_count = _sync_work_orders(since, until, log=log)
    sh_count = _sync_shifts(since, until, log=log)
    ab_count = _sync_absences(since, until, log=log)
    sv_count = _sync_surveys(since, until, log=log)

    elapsed = round(_time.time() - t0)
    db_size = os.path.getsize(_DB_PATH) / 1024 / 1024
    log(f"\n=== Sync complete in {elapsed}s (DB: {db_size:.1f} MB) ===")

    return {
        'elapsed_sec': elapsed,
        'since': since,
        'service_appointments': sa_count,
        'assigned_resources': ar_count,
        'work_orders': wo_count,
        'shifts': sh_count,
        'absences': ab_count,
        'surveys': sv_count,
        'db_size_mb': round(db_size, 1),
    }


# ── Status ───────────────────────────────────────────────────────────────────

def status() -> dict:
    """Return sync status for all tables."""
    try:
        meta = query("SELECT * FROM _sync_meta ORDER BY table_name")
    except Exception:
        return {'seeded': False, 'tables': []}
    db_size = os.path.getsize(_DB_PATH) / 1024 / 1024 if os.path.exists(_DB_PATH) else 0
    return {
        'seeded': is_seeded(),
        'db_size_mb': round(db_size, 1),
        'tables': meta,
    }


# ── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'seed'
    if cmd == 'seed':
        seed()
    elif cmd == 'sync':
        sync()
    elif cmd == 'status':
        import json
        print(json.dumps(status(), indent=2, default=str))
    else:
        print(f"Usage: python db_sync.py [seed|sync|status]")
