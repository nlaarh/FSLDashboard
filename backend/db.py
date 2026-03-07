"""DuckDB local cache for Salesforce data.

All Salesforce reads go through this module. Data is stored in a single
fsl_data.duckdb file that persists on disk. Sync pulls from SF incrementally.
"""

import os, time as _time, threading
from datetime import datetime, date, timedelta, timezone
from contextlib import contextmanager

import duckdb

from sf_client import sf_query, sf_query_all, refresh_auth

# ── Connection ───────────────────────────────────────────────────────────────

_LOCAL_DIR = os.path.expanduser('~/.fslapp')
os.makedirs(_LOCAL_DIR, exist_ok=True)
_DB_PATH = os.path.join(_LOCAL_DIR, 'fsl_data.duckdb')
_local = threading.local()  # thread-local storage for connections


def get_con() -> duckdb.DuckDBPyConnection:
    """Get or create a thread-local DuckDB connection.

    Each thread gets its own connection so reads (request threads) and
    writes (sync thread) never collide on the same connection object.
    DuckDB handles file-level locking internally across connections.
    """
    if not hasattr(_local, 'con') or _local.con is None:
        _local.con = duckdb.connect(_DB_PATH)
        _ensure_schema(_local.con)
    return _local.con


def close():
    if hasattr(_local, 'con') and _local.con:
        _local.con.close()
        _local.con = None


# ── Schema ───────────────────────────────────────────────────────────────────

def _ensure_schema(con: duckdb.DuckDBPyConnection):
    """Create tables if they don't exist."""

    # Static / semi-static
    con.execute("""
        CREATE TABLE IF NOT EXISTS work_types (
            id VARCHAR PRIMARY KEY, name VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS skill_requirements (
            related_record_id VARCHAR, skill_name VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS service_territories (
            id VARCHAR PRIMARY KEY, name VARCHAR, is_active BOOLEAN,
            lat DOUBLE, lon DOUBLE, street VARCHAR, city VARCHAR,
            state VARCHAR, postal_code VARCHAR, parent_id VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS scheduling_policies (
            id VARCHAR PRIMARY KEY, name VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS policy_goals (
            policy_id VARCHAR, goal_name VARCHAR, weight DOUBLE
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS policy_work_rules (
            policy_id VARCHAR, rule_name VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS territory_members (
            territory_id VARCHAR, resource_id VARCHAR,
            resource_name VARCHAR, last_lat DOUBLE, last_lon DOUBLE,
            territory_type VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS service_resources (
            id VARCHAR PRIMARY KEY, name VARCHAR, is_active BOOLEAN,
            last_lat DOUBLE, last_lon DOUBLE,
            last_location_date TIMESTAMP, driver_type VARCHAR,
            resource_type VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS resource_skills (
            resource_id VARCHAR, skill_name VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS polygons (
            id VARCHAR PRIMARY KEY, name VARCHAR,
            territory_id VARCHAR, territory_name VARCHAR,
            color VARCHAR, kml TEXT
        )
    """)

    # Dynamic
    con.execute("""
        CREATE TABLE IF NOT EXISTS service_appointments (
            id VARCHAR PRIMARY KEY, appointment_number VARCHAR,
            status VARCHAR, created_date TIMESTAMP,
            sched_start TIMESTAMP, sched_end TIMESTAMP,
            actual_start TIMESTAMP, actual_end TIMESTAMP,
            duration_min DOUBLE,
            street VARCHAR, city VARCHAR, state VARCHAR, postal_code VARCHAR,
            lat DOUBLE, lon DOUBLE,
            territory_id VARCHAR, territory_name VARCHAR,
            work_type_name VARCHAR, work_type_id VARCHAR,
            work_order_id VARCHAR,
            ers_pta DOUBLE, ers_dispatch_method VARCHAR,
            ers_auto_assign BOOLEAN,
            ers_cancel_reason VARCHAR, ers_decline_reason VARCHAR,
            off_platform_truck_id VARCHAR,
            dispatched_lat DOUBLE, dispatched_lon DOUBLE,
            schedule_mode VARCHAR, auto_schedule BOOLEAN,
            account_name VARCHAR, account_phone VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS assigned_resources (
            id VARCHAR PRIMARY KEY, sa_id VARCHAR,
            resource_id VARCHAR, resource_name VARCHAR,
            estimated_travel DOUBLE, actual_travel DOUBLE,
            created_date TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS work_orders (
            id VARCHAR PRIMARY KEY, wo_number VARCHAR,
            territory_id VARCHAR, created_date TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id VARCHAR PRIMARY KEY, resource_id VARCHAR,
            start_time TIMESTAMP, end_time TIMESTAMP,
            status VARCHAR, territory_id VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS resource_absences (
            id VARCHAR PRIMARY KEY, resource_id VARCHAR,
            resource_name VARCHAR,
            start_time TIMESTAMP, end_time TIMESTAMP, type VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS surveys (
            id VARCHAR PRIMARY KEY, wo_number VARCHAR,
            overall_satisfaction VARCHAR,
            response_time_satisfaction VARCHAR,
            technician_satisfaction VARCHAR,
            nps VARCHAR, nps_group VARCHAR,
            created_date TIMESTAMP
        )
    """)

    # Sync metadata
    con.execute("""
        CREATE TABLE IF NOT EXISTS _sync_meta (
            table_name VARCHAR PRIMARY KEY,
            last_sync TIMESTAMP,
            row_count INTEGER
        )
    """)


# ── Query helpers ────────────────────────────────────────────────────────────

def query(sql: str, params: list | None = None) -> list[dict]:
    """Execute SQL and return list of dicts."""
    con = get_con()
    result = con.execute(sql, params or []).fetchall()
    columns = [desc[0] for desc in con.description]
    return [dict(zip(columns, row)) for row in result]


def query_one(sql: str, params: list | None = None) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def query_scalar(sql: str, params: list | None = None):
    con = get_con()
    result = con.execute(sql, params or []).fetchone()
    return result[0] if result else None


def execute(sql: str, params: list | None = None):
    get_con().execute(sql, params or [])


def executemany(sql: str, data: list):
    get_con().executemany(sql, data)


# ── Sync helpers ─────────────────────────────────────────────────────────────

def _get_last_sync(table_name: str) -> datetime | None:
    row = query_one(
        "SELECT last_sync FROM _sync_meta WHERE table_name = ?",
        [table_name])
    return row['last_sync'] if row else None


def _set_last_sync(table_name: str, ts: datetime, count: int):
    execute(
        "INSERT OR REPLACE INTO _sync_meta VALUES (?, ?, ?)",
        [table_name, ts, count])


def _sf_ts(dt: datetime) -> str:
    """Format datetime for SOQL."""
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def is_seeded() -> bool:
    """Check if DB has been seeded (has SA data)."""
    try:
        n = query_scalar("SELECT COUNT(*) FROM service_appointments")
        return n is not None and n > 0
    except Exception:
        return False


# ── Static table sync (full replace) ────────────────────────────────────────

def _sync_static(log=print):
    """Sync all static/semi-static tables (full replace — they're small).

    Uses BEGIN/COMMIT transactions so DELETE+INSERT is atomic and visible
    within the same connection even across DuckDB thread-local connections.
    """
    con = get_con()
    now = datetime.now(timezone.utc)

    def _dedup(records, key='Id'):
        """Deduplicate SF records by key (SF pagination can return dupes)."""
        seen = set()
        out = []
        for r in records:
            k = r.get(key)
            if k and k not in seen:
                seen.add(k)
                out.append(r)
        return out

    # 1. WorkTypes
    log("  Syncing work_types...")
    recs = _dedup(sf_query_all("SELECT Id, Name FROM WorkType"))
    con.begin()
    con.execute("DELETE FROM work_types")
    for r in recs:
        con.execute("INSERT INTO work_types VALUES (?, ?)",
                    [r['Id'], r.get('Name')])
    con.commit()
    _set_last_sync('work_types', now, len(recs))

    # 2. Skills lookup (used by skill_requirements + resource_skills)
    log("  Loading skill names...")
    skill_recs = sf_query_all("SELECT Id, MasterLabel FROM Skill")
    skill_map = {s['Id']: s.get('MasterLabel', '?') for s in skill_recs}
    log(f"    → {len(skill_map)} skills")

    # 2b. SkillRequirements (only for WorkType IDs, not WOLIs)
    log("  Syncing skill_requirements...")
    wt_ids = [r['Id'] for r in recs]
    con.begin()
    con.execute("DELETE FROM skill_requirements")
    if wt_ids:
        id_list = ",".join(f"'{w}'" for w in wt_ids)
        sk_recs = sf_query_all(
            f"SELECT RelatedRecordId, SkillId "
            f"FROM SkillRequirement WHERE RelatedRecordId IN ({id_list})")
        for r in sk_recs:
            con.execute("INSERT INTO skill_requirements VALUES (?, ?)",
                        [r.get('RelatedRecordId'), skill_map.get(r.get('SkillId'), '?')])
        _set_last_sync('skill_requirements', now, len(sk_recs))
    con.commit()

    # 3. ServiceTerritories
    log("  Syncing service_territories...")
    recs = _dedup(sf_query_all(
        "SELECT Id, Name, IsActive, Latitude, Longitude, "
        "Street, City, State, PostalCode, ParentTerritoryId "
        "FROM ServiceTerritory"))
    con.begin()
    con.execute("DELETE FROM service_territories")
    for r in recs:
        con.execute("INSERT INTO service_territories VALUES (?,?,?,?,?,?,?,?,?,?)", [
            r['Id'], r.get('Name'), r.get('IsActive'),
            r.get('Latitude'), r.get('Longitude'),
            r.get('Street'), r.get('City'), r.get('State'),
            r.get('PostalCode'), r.get('ParentTerritoryId'),
        ])
    con.commit()
    _set_last_sync('service_territories', now, len(recs))

    # 4. Scheduling policies + goals + rules
    log("  Syncing scheduling_policies...")
    pols = _dedup(sf_query_all(
        "SELECT Id, Name FROM FSL__Scheduling_Policy__c "
        "ORDER BY LastModifiedDate DESC LIMIT 10"))
    con.begin()
    con.execute("DELETE FROM scheduling_policies")
    con.execute("DELETE FROM policy_goals")
    con.execute("DELETE FROM policy_work_rules")
    for p in pols:
        con.execute("INSERT INTO scheduling_policies VALUES (?, ?)",
                    [p['Id'], p.get('Name')])
    if pols:
        all_pids = ",".join(f"'{p['Id']}'" for p in pols)
        goals = sf_query_all(
            f"SELECT FSL__Scheduling_Policy__c, FSL__Weight__c, "
            f"FSL__Service_Goal__c "
            f"FROM FSL__Scheduling_Policy_Goal__c "
            f"WHERE FSL__Scheduling_Policy__c IN ({all_pids})")
        goal_ids = list(set(g.get('FSL__Service_Goal__c') for g in goals if g.get('FSL__Service_Goal__c')))
        goal_map = {}
        if goal_ids:
            gid_list = ",".join(f"'{g}'" for g in goal_ids)
            gn = sf_query_all(f"SELECT Id, Name FROM FSL__Service_Goal__c WHERE Id IN ({gid_list})")
            goal_map = {g['Id']: g.get('Name', '?') for g in gn}
        for g in goals:
            con.execute("INSERT INTO policy_goals VALUES (?, ?, ?)", [
                g.get('FSL__Scheduling_Policy__c'),
                goal_map.get(g.get('FSL__Service_Goal__c'), '?'),
                g.get('FSL__Weight__c'),
            ])
        rules = sf_query_all(
            f"SELECT FSL__Scheduling_Policy__c, FSL__Work_Rule__c "
            f"FROM FSL__Scheduling_Policy_Work_Rule__c "
            f"WHERE FSL__Scheduling_Policy__c IN ({all_pids})")
        rule_ids = list(set(r.get('FSL__Work_Rule__c') for r in rules if r.get('FSL__Work_Rule__c')))
        rule_map = {}
        if rule_ids:
            rid_list = ",".join(f"'{r}'" for r in rule_ids)
            rn = sf_query_all(f"SELECT Id, Name FROM FSL__Work_Rule__c WHERE Id IN ({rid_list})")
            rule_map = {r['Id']: r.get('Name', '?') for r in rn}
        for r in rules:
            con.execute("INSERT INTO policy_work_rules VALUES (?, ?)", [
                r.get('FSL__Scheduling_Policy__c'),
                rule_map.get(r.get('FSL__Work_Rule__c'), '?'),
            ])
    con.commit()
    _set_last_sync('scheduling_policies', now, len(pols))

    # 5. Territory members
    log("  Syncing territory_members...")
    recs = sf_query_all(
        "SELECT ServiceTerritoryId, ServiceResourceId, TerritoryType "
        "FROM ServiceTerritoryMember")
    con.begin()
    con.execute("DELETE FROM territory_members")
    for r in recs:
        con.execute("INSERT INTO territory_members VALUES (?,?,?,?,?,?)", [
            r.get('ServiceTerritoryId'), r.get('ServiceResourceId'),
            None, None, None,
            r.get('TerritoryType'),
        ])
    con.commit()
    _set_last_sync('territory_members', now, len(recs))

    # 6. Service resources
    log("  Syncing service_resources...")
    recs = _dedup(sf_query_all(
        "SELECT Id, Name, IsActive, LastKnownLatitude, LastKnownLongitude, "
        "LastKnownLocationDate, ERS_Driver_Type__c, ResourceType "
        "FROM ServiceResource WHERE IsActive = true"))
    con.begin()
    con.execute("DELETE FROM service_resources")
    for r in recs:
        con.execute("INSERT INTO service_resources VALUES (?,?,?,?,?,?,?,?)", [
            r['Id'], r.get('Name'), r.get('IsActive'),
            r.get('LastKnownLatitude'), r.get('LastKnownLongitude'),
            r.get('LastKnownLocationDate'), r.get('ERS_Driver_Type__c'),
            r.get('ResourceType'),
        ])
    con.commit()
    _set_last_sync('service_resources', now, len(recs))

    # 7. Resource skills
    log("  Syncing resource_skills...")
    recs = sf_query_all(
        "SELECT ServiceResourceId, SkillId FROM ServiceResourceSkill")
    con.begin()
    con.execute("DELETE FROM resource_skills")
    for r in recs:
        con.execute("INSERT INTO resource_skills VALUES (?, ?)",
                    [r.get('ServiceResourceId'), skill_map.get(r.get('SkillId'), '?')])
    con.commit()
    _set_last_sync('resource_skills', now, len(recs))

    # 8. Polygons
    log("  Syncing polygons...")
    recs = _dedup(sf_query_all(
        "SELECT Id, Name, FSL__Service_Territory__c, FSL__Color__c "
        "FROM FSL__Polygon__c ORDER BY Name"))
    con.begin()
    con.execute("DELETE FROM polygons")
    for r in recs:
        con.execute("INSERT INTO polygons VALUES (?,?,?,?,?,?)", [
            r['Id'], r.get('Name'),
            r.get('FSL__Service_Territory__c'), None,
            r.get('FSL__Color__c'), None,
        ])
    con.commit()
    _set_last_sync('polygons', now, len(recs))

    # Load KML in small batches
    log("  Loading polygon KML data...")
    poly_ids = [r['Id'] for r in recs]
    for i in range(0, len(poly_ids), 20):
        batch = poly_ids[i:i+20]
        id_list = ",".join(f"'{p}'" for p in batch)
        kml_recs = sf_query_all(
            f"SELECT Id, FSL__KML__c FROM FSL__Polygon__c WHERE Id IN ({id_list})")
        for kr in kml_recs:
            con.execute("UPDATE polygons SET kml = ? WHERE id = ?",
                        [kr.get('FSL__KML__c'), kr['Id']])
        log(f"    KML batch {i//20+1}/{(len(poly_ids)+19)//20}")

    log(f"  Static sync complete.")


# ── Dynamic table sync (chunked by date) ────────────────────────────────────

def _sync_service_appointments(since: str, until: str, log=print):
    """Pull SAs in 7-day chunks. since/until are YYYY-MM-DD strings."""
    con = get_con()
    start = date.fromisoformat(since)
    end = date.fromisoformat(until)
    total = 0

    while start < end:
        chunk_end = min(start + timedelta(days=7), end)
        log(f"  SAs: {start} → {chunk_end}...")
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
        log(f"    → {len(recs)} SAs ({total} cumulative)")
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
        log(f"  ARs: {start} → {chunk_end}...")
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
        log(f"  WOs: {start} → {chunk_end}...")
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
    log(f"  Shifts: {since} → {until}...")
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
    log(f"    → {len(recs)} shifts")
    return len(recs)


def _sync_absences(since: str, until: str, log=print):
    con = get_con()
    log(f"  Absences: {since} → {until}...")
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
    log(f"    → {len(recs)} absences")
    return len(recs)


def _sync_surveys(since: str, until: str, log=print):
    con = get_con()
    start = date.fromisoformat(since)
    end = date.fromisoformat(until)
    total = 0

    while start < end:
        chunk_end = min(start + timedelta(days=7), end)
        log(f"  Surveys: {start} → {chunk_end}...")
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
    """Full seed from Salesforce. Pulls since → today."""
    if until is None:
        until = date.today().isoformat()

    refresh_auth()
    t0 = _time.time()
    log(f"=== Seeding DuckDB: {since} → {until} ===")

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
        # Sync from 1 day before last sync (overlap to catch late updates)
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
        print(f"Usage: python db.py [seed|sync|status]")
