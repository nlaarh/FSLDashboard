"""DuckDB store for optimizer run analysis — schema, connection, query helpers."""

import os
import logging
import time as _time
import duckdb
from pathlib import Path
from contextlib import contextmanager

log = logging.getLogger('optimizer_db')

_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_DB_DIR = Path('/home/fslapp') if _ON_AZURE else Path(os.path.expanduser('~/.fslapp'))
DB_PATH = str(_DB_DIR / 'optimizer.duckdb')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opt_resources (
    id           VARCHAR PRIMARY KEY,
    name         VARCHAR,
    updated_at   TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS opt_runs (
    id                 VARCHAR PRIMARY KEY,
    name               VARCHAR,
    territory_id       VARCHAR,
    territory_name     VARCHAR,
    policy_id          VARCHAR,
    policy_name        VARCHAR,
    run_at             TIMESTAMP NOT NULL,
    horizon_start      TIMESTAMP,
    horizon_end        TIMESTAMP,
    resources_count    INTEGER,
    services_count     INTEGER,
    pre_scheduled      INTEGER,
    post_scheduled     INTEGER,
    unscheduled_count  INTEGER,
    pre_travel_time_s  INTEGER,
    post_travel_time_s INTEGER,
    pre_response_avg_s DOUBLE,
    post_response_avg_s DOUBLE,
    synced_at          TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS opt_sa_decisions (
    id                     VARCHAR PRIMARY KEY,
    run_id                 VARCHAR NOT NULL,
    sa_id                  VARCHAR NOT NULL,
    sa_number              VARCHAR,
    sa_work_type           VARCHAR,
    action                 VARCHAR,
    unscheduled_reason     VARCHAR,
    winner_driver_id       VARCHAR,
    winner_driver_name     VARCHAR,
    winner_travel_time_min DOUBLE,
    winner_travel_dist_mi  DOUBLE,
    run_at                 TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS opt_driver_verdicts (
    id               VARCHAR PRIMARY KEY,
    run_id           VARCHAR NOT NULL,
    sa_id            VARCHAR NOT NULL,
    driver_id        VARCHAR NOT NULL,
    driver_name      VARCHAR,
    status           VARCHAR,
    exclusion_reason VARCHAR,
    travel_time_min  DOUBLE,
    travel_dist_mi   DOUBLE,
    driver_skills    VARCHAR,   -- comma-separated skill list
    driver_territory VARCHAR,   -- driver's home territory name
    run_at           TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS opt_sync_errors (
    run_id    VARCHAR PRIMARY KEY,
    run_name  VARCHAR,
    error     VARCHAR,
    failed_at TIMESTAMP,
    retried   BOOLEAN DEFAULT false,
    run_at    VARCHAR,
    attempts  INTEGER DEFAULT 0
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_opt_runs_run_at       ON opt_runs(run_at);
CREATE INDEX IF NOT EXISTS idx_opt_runs_territory    ON opt_runs(territory_id);
CREATE INDEX IF NOT EXISTS idx_sa_decisions_sa_num   ON opt_sa_decisions(sa_number);
CREATE INDEX IF NOT EXISTS idx_sa_decisions_run_id   ON opt_sa_decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_sa_decisions_run_at   ON opt_sa_decisions(run_at);
CREATE INDEX IF NOT EXISTS idx_verdicts_driver_name  ON opt_driver_verdicts(driver_name);
CREATE INDEX IF NOT EXISTS idx_verdicts_run_id       ON opt_driver_verdicts(run_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_sa_id        ON opt_driver_verdicts(sa_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_run_at       ON opt_driver_verdicts(run_at);
"""


def _rows(cursor) -> list[dict]:
    """Convert DuckDB cursor result to list of dicts (no pandas required)."""
    if cursor.description is None:
        return []
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


_MIGRATIONS = [
    # Added attempts column after initial deploy — ensure existing tables pick it up
    "ALTER TABLE opt_sync_errors ADD COLUMN IF NOT EXISTS attempts INTEGER DEFAULT 0",
    "ALTER TABLE opt_sync_errors ADD COLUMN IF NOT EXISTS run_at VARCHAR",
    # Driver verdict enrichment — seed/sync populate, UI renders per driver
    "ALTER TABLE opt_driver_verdicts ADD COLUMN IF NOT EXISTS driver_skills VARCHAR",
    "ALTER TABLE opt_driver_verdicts ADD COLUMN IF NOT EXISTS driver_territory VARCHAR",
    # Batch grouping — when FSL splits one big optimization into N parallel chunks,
    # all share the same batch_id; chunk_num distinguishes them (1, 2, 3, …).
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS batch_id VARCHAR",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS chunk_num INTEGER",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS fsl_type VARCHAR",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS fsl_status VARCHAR",
    # Parser v2 — policy + extended KPIs
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS objectives_count INTEGER",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS work_rules_count INTEGER",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS skills_count INTEGER",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS daily_optimization BOOLEAN",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS commit_mode VARCHAR",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS post_response_appt_s DOUBLE",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS post_extraneous_time_s INTEGER",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS post_start_commute_dist INTEGER",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS post_end_commute_dist INTEGER",
    "ALTER TABLE opt_runs ADD COLUMN IF NOT EXISTS post_resources_unscheduled INTEGER",
    # Per-SA enrichments
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS priority DOUBLE",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS duration_min DOUBLE",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS sa_status VARCHAR",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS sa_lat DOUBLE",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS sa_lon DOUBLE",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS earliest_start TIMESTAMP",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS due_date TIMESTAMP",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS sched_start TIMESTAMP",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS sched_end TIMESTAMP",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS required_skills VARCHAR",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN",
    "ALTER TABLE opt_sa_decisions ADD COLUMN IF NOT EXISTS seats_required DOUBLE",
]

def init_db():
    """Create tables, indexes, and run incremental migrations."""
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(DB_PATH)
    conn.execute(_SCHEMA)
    conn.execute(_INDEXES)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except Exception:
            pass  # Column already exists — DuckDB IF NOT EXISTS doesn't cover all cases
    conn.close()
    log.info(f"Optimizer DuckDB initialized at {DB_PATH}")


@contextmanager
def get_conn(read_only: bool = False, _retries: int = 3):
    # NOTE: read_only is accepted but IGNORED in-process. DuckDB requires all
    # connections in the same process to have the same configuration, and the
    # blob_sync background thread holds a write connection. Forcing read-only
    # here would raise "Can't open a connection ... with a different
    # configuration". We rely on query-level safety in callers (SELECT only).
    last_err = None
    for attempt in range(_retries):
        try:
            conn = duckdb.connect(DB_PATH, read_only=False)
            try:
                yield conn
                return
            finally:
                conn.close()
        except duckdb.IOException as e:
            msg = str(e).lower()
            transient = ('lock' in msg) or ('conflict' in msg) or ('busy' in msg)
            if transient and attempt < _retries - 1:
                _time.sleep(0.2 * (attempt + 1))
                last_err = e
                continue
            raise
    raise last_err  # type: ignore


def purge_old_runs(days: int = 30) -> int:
    """Delete rows older than `days` days. Returns total rows deleted."""
    total = 0
    with get_conn() as conn:
        for tbl in ('opt_driver_verdicts', 'opt_sa_decisions', 'opt_runs'):
            n = conn.execute(
                f"DELETE FROM {tbl} WHERE run_at < now() - INTERVAL '{int(days)} days'"
            ).rowcount
            total += max(0, n)  # DuckDB returns -1 for empty deletes (DB-API 2.0)
    return total


# ── Read helpers ─────────────────────────────────────────────────────────────

def list_runs(from_dt: str, to_dt: str, territory: str | None = None) -> list[dict]:
    sql = """
        SELECT id, name, territory_name, policy_name, run_at,
               resources_count, services_count,
               pre_scheduled, post_scheduled, unscheduled_count,
               pre_travel_time_s, post_travel_time_s,
               pre_response_avg_s, post_response_avg_s,
               batch_id, chunk_num, fsl_type, fsl_status,
               objectives_count, work_rules_count, skills_count,
               daily_optimization, commit_mode,
               post_response_appt_s, post_extraneous_time_s,
               post_start_commute_dist, post_end_commute_dist,
               post_resources_unscheduled
        FROM opt_runs
        WHERE run_at BETWEEN ? AND ?
    """
    params: list = [from_dt, to_dt]
    if territory:
        sql += " AND lower(territory_name) LIKE ?"
        params.append(f"%{territory.lower()}%")
    sql += " ORDER BY run_at DESC LIMIT 500"
    with get_conn(read_only=True) as conn:
        return _rows(conn.execute(sql, params))


def get_run_detail(run_id: str) -> dict | None:
    with get_conn(read_only=True) as conn:
        run_rows = _rows(conn.execute("SELECT * FROM opt_runs WHERE id = ?", [run_id]))
        if not run_rows:
            return None
        # ORDER BY priority DESC NULLS LAST so high-priority SAs surface first
        decisions = _rows(conn.execute(
            """SELECT * FROM opt_sa_decisions
               WHERE run_id = ?
               ORDER BY action,
                        CASE WHEN priority IS NULL THEN 1 ELSE 0 END,
                        priority DESC""", [run_id]
        ))
        return {'run': run_rows[0], 'decisions': decisions}


def get_sa_decision(sa_number: str, limit: int = 5, run_id: str | None = None) -> list[dict]:
    """Return the last `limit` runs that touched this SA, with full driver verdicts.

    When `run_id` is provided, returns only that specific run (or empty list if no
    match) — used by the per-run SA decision page so we don't have to page through
    dozens of recent runs to find the one the user is looking at.
    """
    # Normalize SA number format
    sa_num = sa_number.strip()
    if not sa_num.upper().startswith('SA-'):
        sa_num = 'SA-' + sa_num.zfill(8)

    with get_conn(read_only=True) as conn:
        if run_id:
            decisions = _rows(conn.execute(
                """SELECT d.*, r.territory_name, r.policy_name
                   FROM opt_sa_decisions d
                   JOIN opt_runs r ON r.id = d.run_id
                   WHERE d.sa_number = ? AND d.run_id = ?""",
                [sa_num, run_id]
            ))
        else:
            decisions = _rows(conn.execute(
                """SELECT d.*, r.territory_name, r.policy_name
                   FROM opt_sa_decisions d
                   JOIN opt_runs r ON r.id = d.run_id
                   WHERE d.sa_number = ?
                   ORDER BY d.run_at DESC LIMIT ?""",
                [sa_num, limit]
            ))
        for dec in decisions:
            dec['verdicts'] = _rows(conn.execute(
                """SELECT driver_name, driver_id, status, exclusion_reason,
                          travel_time_min, travel_dist_mi,
                          driver_skills, driver_territory
                   FROM opt_driver_verdicts
                   WHERE run_id = ? AND sa_id = ?
                   ORDER BY CASE status WHEN 'winner' THEN 0
                                        WHEN 'eligible' THEN 1
                                        ELSE 2 END,
                            travel_time_min NULLS LAST""",
                [dec['run_id'], dec['sa_id']]
            ))
        return decisions


def get_driver_analysis(driver_name: str, days: int = 7) -> dict:
    # Use f-string for INTERVAL — days is always int (no injection risk)
    interval = f"INTERVAL '{int(days)} days'"
    with get_conn(read_only=True) as conn:
        summary = _rows(conn.execute(
            f"""SELECT status, COUNT(*) as count
               FROM opt_driver_verdicts
               WHERE lower(driver_name) LIKE lower(?)
                 AND run_at >= now() - {interval}
               GROUP BY status""",
            [f"%{driver_name}%"]
        ))
        reasons = _rows(conn.execute(
            f"""SELECT exclusion_reason, COUNT(*) as count
               FROM opt_driver_verdicts
               WHERE lower(driver_name) LIKE lower(?)
                 AND status = 'excluded'
                 AND run_at >= now() - {interval}
               GROUP BY exclusion_reason ORDER BY count DESC""",
            [f"%{driver_name}%"]
        ))
        return {'summary': summary, 'exclusion_reasons': reasons}


def get_unscheduled_analysis(run_id: str) -> list[dict]:
    with get_conn(read_only=True) as conn:
        return _rows(conn.execute(
            """SELECT d.sa_number, d.sa_work_type, d.unscheduled_reason,
                      COUNT(v.id) FILTER (WHERE v.status='excluded') as excluded_count,
                      COUNT(v.id) FILTER (WHERE v.status='eligible') as eligible_count
               FROM opt_sa_decisions d
               LEFT JOIN opt_driver_verdicts v ON v.run_id=d.run_id AND v.sa_id=d.sa_id
               WHERE d.run_id = ? AND d.action = 'Unscheduled'
               GROUP BY d.sa_number, d.sa_work_type, d.unscheduled_reason""",
            [run_id]
        ))


def get_exclusion_patterns(territory: str | None, days: int = 7) -> list[dict]:
    interval = f"INTERVAL '{int(days)} days'"
    sql = f"""
        SELECT v.exclusion_reason, COUNT(*) as fires,
               COUNT(DISTINCT v.driver_id) as drivers_affected
        FROM opt_driver_verdicts v
        JOIN opt_runs r ON r.id = v.run_id
        WHERE v.status = 'excluded'
          AND v.run_at >= now() - {interval}
    """
    params: list = []
    if territory:
        sql += " AND lower(r.territory_name) LIKE ?"
        params.append(f"%{territory.lower()}%")
    sql += " GROUP BY v.exclusion_reason ORDER BY fires DESC"
    with get_conn(read_only=True) as conn:
        return _rows(conn.execute(sql, params))


def query_optimizer_sql(sql: str) -> list[dict]:
    """Read-only SQL escape hatch. Only SELECT allowed."""
    stripped = sql.strip().upper()
    if not stripped.startswith('SELECT'):
        raise ValueError("Only SELECT queries are permitted")
    for forbidden in ('INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ATTACH', 'COPY'):
        if forbidden in stripped:
            raise ValueError(f"Forbidden keyword: {forbidden}")
    with get_conn(read_only=True) as conn:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(500)
        return [dict(zip(cols, row)) for row in rows]


def upsert_resource_names(resources: list[dict]):
    """Store resource id→name mappings. Only inserts missing ones."""
    if not resources:
        return
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO opt_resources(id, name) VALUES (?, ?)",
            [(r['id'], r['name']) for r in resources]
        )


def get_resource_name(resource_id: str, fallback: dict | None = None) -> str:
    with get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT name FROM opt_resources WHERE id = ?", [resource_id]
        ).fetchone()
    if row:
        return row[0]
    if fallback:
        return fallback.get(resource_id, resource_id)
    return resource_id
