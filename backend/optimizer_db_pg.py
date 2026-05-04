"""Postgres backend for optimizer store.

Mirrors the public API of `optimizer_db.py` (the DuckDB version) so callers
don't need to know which backend is active. Selected via OPT_DB_BACKEND env var.

Schema lives under `optimizer.*` in the `fslapp` database. Connection's
search_path is set to `optimizer, public` (in pg_pool._configure_connection),
so unqualified table names like `opt_runs` resolve correctly.

DuckDB → Postgres translation strategy:
- The `_PgConn` adapter wraps a psycopg connection and translates `?` → `%s`
  in every `execute()` call, so caller code with `conn.execute("…?…", [v])`
  works unchanged.
- `INSERT OR IGNORE` → `INSERT … ON CONFLICT DO NOTHING` (rewritten in
  upsert_resource_names below).
- `INSERT OR REPLACE` is NOT used in this module — that's only in blob_sync,
  handled separately there.
- `now() - INTERVAL`, `FILTER (WHERE …)`, `NULLS LAST`, `lower()` all work
  identically in Postgres.
"""

import logging
from contextlib import contextmanager
from typing import Any, Iterable

import psycopg

import pg_pool

log = logging.getLogger('optimizer_db_pg')


# ── Connection adapter (DuckDB-compatible API on top of psycopg) ────────────

class _PgConn:
    """Thin wrapper around a psycopg connection that mimics duckdb's API.

    Why: callers issue `conn.execute("SELECT ... ?", [val])` patterns straight
    from the DuckDB world. Re-writing every callsite to use psycopg's `%s`
    placeholders + manual `cursor()` calls would be a large diff. This adapter
    lets that code keep working without changes.

    Each `execute()` returns a psycopg cursor — same shape as duckdb's return:
    `.description`, `.fetchone()`, `.fetchall()`, `.fetchmany(n)`, `.rowcount`.
    """

    __slots__ = ('_conn',)

    def __init__(self, pg_conn: psycopg.Connection):
        self._conn = pg_conn

    @staticmethod
    def _translate(sql: str) -> str:
        """DuckDB `?` placeholders → psycopg `%s`. Idempotent for already-`%s` SQL."""
        # Avoid touching SQL that already has %s — a simple guard.
        if '?' not in sql:
            return sql
        # Naive replace is safe because our SQL doesn't use literal `?` chars.
        # If someone introduces a regex or text containing `?`, switch to a
        # proper tokenizer. Verified against current call sites.
        return sql.replace('?', '%s')

    def execute(self, sql: str, params: Iterable[Any] | None = None):
        cur = self._conn.cursor()
        sql = self._translate(sql)
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, list(params))
        return cur

    def executemany(self, sql: str, params_list: Iterable[Iterable[Any]]):
        cur = self._conn.cursor()
        sql = self._translate(sql)
        cur.executemany(sql, [list(p) for p in params_list])
        return cur

    # Pass-through methods callers might invoke
    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        # No-op — the pool manages lifecycle. Wrapper exits via context mgr.
        pass

    @property
    def description(self):
        # Some duckdb code reads conn.description after execute. Not idiomatic
        # in psycopg but supported defensively.
        return None


# ── Public API (mirrors optimizer_db.py signatures exactly) ─────────────────

def init_db() -> None:
    """No-op for Postgres. Schemas + tables are provisioned by infra/postgres/init-schema.sql.

    Kept as a public function so the dispatcher and callers (main.py startup)
    can call it unconditionally without checking the backend.
    """
    log.info("init_db: Postgres backend — schema is managed by init-schema.sql, no-op")


@contextmanager
def get_conn(read_only: bool = False, _retries: int = 3):
    """Context manager that yields a duckdb-compatible connection wrapper.

    `read_only=True` borrows from the reader pool; `False` from the writer
    pool. `_retries` is accepted for API compatibility but unused — psycopg
    pool handles transient errors via its own backoff.
    """
    if read_only:
        with pg_pool.reader() as conn:
            yield _PgConn(conn)
    else:
        with pg_pool.writer() as conn:
            yield _PgConn(conn)


def _rows(cursor) -> list[dict]:
    """Convert a psycopg cursor's rows into list[dict] using column names."""
    if cursor.description is None:
        return []
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ── Maintenance ──────────────────────────────────────────────────────────────

def purge_old_runs(days: int = 30) -> int:
    """Delete rows older than `days` days. Returns total rows deleted."""
    total = 0
    with get_conn() as conn:
        for tbl in ('opt_driver_verdicts', 'opt_sa_decisions', 'opt_runs'):
            cur = conn.execute(
                f"DELETE FROM {tbl} WHERE run_at < now() - INTERVAL '{int(days)} days'"
            )
            total += max(0, cur.rowcount)
        conn.commit()
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

    When `run_id` is provided, returns only that specific run.
    """
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


def upsert_resource_names(resources: list[dict]) -> None:
    """Store resource id→name mappings. Inserts missing ones."""
    if not resources:
        return
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO opt_resources(id, name) VALUES (?, ?) ON CONFLICT (id) DO NOTHING",
            [(r['id'], r['name']) for r in resources]
        )
        conn.commit()


# ── Upsert helpers (used by optimizer_blob_sync) ────────────────────────────
# These wrap the parser's output rows into Postgres `INSERT … ON CONFLICT DO
# UPDATE`, mirroring DuckDB's `INSERT OR REPLACE` semantics.

_RUN_COLS = (
    'id', 'name', 'territory_id', 'territory_name', 'policy_id', 'policy_name',
    'run_at', 'horizon_start', 'horizon_end',
    'resources_count', 'services_count',
    'pre_scheduled', 'post_scheduled', 'unscheduled_count',
    'pre_travel_time_s', 'post_travel_time_s',
    'pre_response_avg_s', 'post_response_avg_s',
    'batch_id', 'chunk_num', 'fsl_type', 'fsl_status',
    'objectives_count', 'work_rules_count', 'skills_count',
    'daily_optimization', 'commit_mode',
    'post_response_appt_s', 'post_extraneous_time_s',
    'post_start_commute_dist', 'post_end_commute_dist',
    'post_resources_unscheduled',
)

_DECISION_COLS = (
    'id', 'run_id', 'sa_id', 'sa_number', 'sa_work_type', 'action',
    'unscheduled_reason', 'winner_driver_id', 'winner_driver_name',
    'winner_travel_time_min', 'winner_travel_dist_mi', 'run_at',
    'priority', 'duration_min', 'sa_status', 'sa_lat', 'sa_lon',
    'earliest_start', 'due_date', 'sched_start', 'sched_end',
    'required_skills', 'is_pinned', 'seats_required',
)

_VERDICT_COLS = (
    'id', 'run_id', 'sa_id', 'driver_id', 'driver_name',
    'status', 'exclusion_reason', 'travel_time_min', 'travel_dist_mi',
    'driver_skills', 'driver_territory', 'run_at',
)


def _build_upsert_sql(table: str, cols: tuple, pk: str) -> str:
    col_list = ', '.join(cols)
    placeholders = ', '.join(['?'] * len(cols))
    update_set = ', '.join(f'{c} = EXCLUDED.{c}' for c in cols if c != pk)
    return (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk}) DO UPDATE SET {update_set}"
    )


def _row_values(row: dict, cols: tuple) -> list:
    """Pluck values from row dict in the column order; missing keys → None."""
    return [row.get(c) for c in cols]


def upsert_run(row: dict) -> None:
    """Insert/update a single opt_runs row."""
    sql = _build_upsert_sql('opt_runs', _RUN_COLS, 'id')
    with get_conn() as conn:
        conn.execute(sql, _row_values(row, _RUN_COLS))
        conn.commit()


def bulk_upsert_decisions(rows: list[dict]) -> None:
    """Insert/update many opt_sa_decisions rows."""
    if not rows:
        return
    sql = _build_upsert_sql('opt_sa_decisions', _DECISION_COLS, 'id')
    with get_conn() as conn:
        conn.executemany(sql, [_row_values(r, _DECISION_COLS) for r in rows])
        conn.commit()


def bulk_upsert_verdicts(rows: list[dict]) -> None:
    """Insert/update many opt_driver_verdicts rows."""
    if not rows:
        return
    sql = _build_upsert_sql('opt_driver_verdicts', _VERDICT_COLS, 'id')
    with get_conn() as conn:
        conn.executemany(sql, [_row_values(r, _VERDICT_COLS) for r in rows])
        conn.commit()


def get_resource_name(resource_id: str, fallback: dict | None = None) -> str:
    with get_conn(read_only=True) as conn:
        cur = conn.execute(
            "SELECT name FROM opt_resources WHERE id = ?", [resource_id]
        )
        row = cur.fetchone()
    if row:
        return row[0]
    if fallback:
        return fallback.get(resource_id, resource_id)
    return resource_id
