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


# ── Dynamic sync, seed, incremental sync, status, CLI ────────────────────────
# Moved to db_sync.py — import seed(), sync(), status() from there.
