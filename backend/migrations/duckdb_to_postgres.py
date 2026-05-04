"""One-shot ETL: DuckDB → Azure Postgres Flexible.

Run AFTER the Postgres provisioning succeeds. Uses Microsoft Entra ID auth
(no passwords). Idempotent — safe to re-run; uses INSERT … ON CONFLICT.

Usage:
    cd apidev/FSLAPP/backend
    python -m migrations.duckdb_to_postgres                        # all tables
    python -m migrations.duckdb_to_postgres --table opt_runs       # one table
    python -m migrations.duckdb_to_postgres --dry-run              # show plan only
    python -m migrations.duckdb_to_postgres --truncate-first       # destructive

Pre-reqs:
    - az login (signed-in to AAAWCNY Azure Sandbox subscription)
    - .duckdb file at ~/.fslapp/optimizer.duckdb
    - Postgres deployed via infra/postgres/deploy.sh
    - psycopg installed: pip install 'psycopg[binary,pool]'
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import duckdb
import psycopg
from azure.identity import DefaultAzureCredential

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('etl')

PG_HOST = os.environ.get('FSLAPP_PG_HOST', 'fslapp-pg.postgres.database.azure.com')
PG_DATABASE = os.environ.get('FSLAPP_PG_DATABASE', 'fslapp')
PG_USER = os.environ.get('PGUSER') or os.environ.get('FSLAPP_PG_USER', 'nlaaroubi@nyaaa.com')

DUCKDB_PATH = Path.home() / '.fslapp' / 'optimizer.duckdb'

# Tables to copy, in dependency order. Schema is `optimizer.*` on Postgres side.
# Each entry: (duckdb_table, pg_schema, pg_table, primary_key_col, time_col)
# `time_col` is used by `--days N` to filter `WHERE <col> >= now() - INTERVAL N days`.
# None means "always copy all rows" (small lookup tables / no time column).
TABLES = [
    ('opt_runs',            'optimizer', 'opt_runs',            'id',     'run_at'),
    ('opt_resources',       'optimizer', 'opt_resources',       'id',     None),
    ('opt_sa_decisions',    'optimizer', 'opt_sa_decisions',    'id',     'run_at'),
    ('opt_driver_verdicts', 'optimizer', 'opt_driver_verdicts', 'id',     'run_at'),
    ('opt_blob_audit',      'optimizer', 'opt_blob_audit',      'run_id', 'processed_at'),
    ('opt_sync_errors',     'optimizer', 'opt_sync_errors',     None,     'failed_at'),
]

CHUNK_SIZE = 5000   # rows per INSERT batch


def get_pg_token() -> str:
    """Fetch a fresh Azure AD access token for Postgres (valid ~60min)."""
    cred = DefaultAzureCredential()
    return cred.get_token('https://ossrdbms-aad.database.windows.net/.default').token


def pg_connect():
    """Open Postgres connection with current Entra token."""
    return psycopg.connect(
        host=PG_HOST,
        dbname=PG_DATABASE,
        user=PG_USER,
        password=get_pg_token(),
        sslmode='require',
        connect_timeout=10,
    )


def duck_columns(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    return [r[1] for r in rows]


def pg_columns(pg_conn, schema: str, table: str) -> list[str]:
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            (schema, table),
        )
        return [r[0] for r in cur.fetchall()]


def copy_table(duck_conn, pg_conn, duck_table: str, pg_schema: str, pg_table: str,
               pk: str | None, time_col: str | None, days: int | None,
               dry_run: bool, truncate_first: bool) -> dict:
    """Copy one table, idempotent via ON CONFLICT (when pk is set).

    `days` + `time_col` together filter to rows where `time_col >= now() - INTERVAL N days`.
    If `time_col` is None for this table, the filter is ignored (small lookup tables).
    """
    duck_cols = duck_columns(duck_conn, duck_table)
    pg_cols   = pg_columns(pg_conn, pg_schema, pg_table)
    common    = [c for c in duck_cols if c in pg_cols]
    skipped   = [c for c in duck_cols if c not in pg_cols]
    if skipped:
        log.warning(f"  {duck_table}: skipping {len(skipped)} cols not on PG side: {skipped}")
    if not common:
        log.error(f"  {duck_table}: no common columns with {pg_schema}.{pg_table} — abort")
        return {'rows': 0, 'inserted': 0, 'skipped': 0, 'error': 'no common columns'}

    where_clause = ""
    if days is not None and time_col is not None and time_col in duck_cols:
        # DuckDB syntax: TIMESTAMP - INTERVAL works fine. Cast string columns just in case.
        where_clause = f" WHERE {time_col} >= now() - INTERVAL '{int(days)} days'"
        log.info(f"  Filter: {time_col} >= now() - INTERVAL '{days} days'")

    total = duck_conn.execute(
        f"SELECT COUNT(*) FROM {duck_table}{where_clause}"
    ).fetchone()[0]
    log.info(f"  {duck_table} → {pg_schema}.{pg_table}: {total} rows, {len(common)} cols")

    if dry_run:
        log.info(f"    DRY RUN: would copy with cols {common[:6]}{'…' if len(common) > 6 else ''}")
        return {'rows': total, 'inserted': 0, 'skipped': 0, 'dry_run': True}

    if truncate_first:
        log.info(f"    TRUNCATE {pg_schema}.{pg_table}")
        with pg_conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {pg_schema}.{pg_table}")
        pg_conn.commit()

    # Stream rows in CHUNK_SIZE batches
    cols_sql = ', '.join(f'"{c}"' for c in common)
    placeholders = ', '.join(['%s'] * len(common))
    if pk:
        update_set = ', '.join(f'"{c}" = EXCLUDED."{c}"' for c in common if c != pk)
        insert_sql = (
            f'INSERT INTO {pg_schema}.{pg_table} ({cols_sql}) '
            f'VALUES ({placeholders}) '
            f'ON CONFLICT ("{pk}") DO UPDATE SET {update_set}'
        )
    else:
        # No PK → plain INSERT (truncate_first is the only safe path here)
        insert_sql = (
            f'INSERT INTO {pg_schema}.{pg_table} ({cols_sql}) VALUES ({placeholders})'
        )

    inserted = 0
    t0 = time.time()
    cursor = duck_conn.execute(f"SELECT {cols_sql} FROM {duck_table}{where_clause}")
    with pg_conn.cursor() as pgcur:
        while True:
            rows = cursor.fetchmany(CHUNK_SIZE)
            if not rows:
                break
            pgcur.executemany(insert_sql, rows)
            inserted += len(rows)
            if inserted % 50000 == 0 or inserted == total:
                rate = inserted / max(time.time() - t0, 0.001)
                log.info(f"    {inserted}/{total} ({rate:.0f} rows/sec)")
    pg_conn.commit()
    elapsed = time.time() - t0
    log.info(f"  {duck_table}: {inserted} rows in {elapsed:.1f}s ({inserted/max(elapsed,0.001):.0f} rows/sec)")
    return {'rows': total, 'inserted': inserted, 'skipped': 0, 'elapsed_s': elapsed}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--table', help='Copy only this table (default: all)')
    p.add_argument('--dry-run', action='store_true',
                   help='Show plan, count rows, do not write')
    p.add_argument('--truncate-first', action='store_true',
                   help='TRUNCATE Postgres tables before copy (destructive!)')
    p.add_argument('--duckdb-path', default=str(DUCKDB_PATH),
                   help=f'DuckDB file (default: {DUCKDB_PATH})')
    p.add_argument('--days', type=int, default=None,
                   help='Only copy rows from last N days (filters by run_at/processed_at/failed_at). Default: all rows.')
    args = p.parse_args()

    duck_path = Path(args.duckdb_path)
    if not duck_path.exists():
        log.error(f"DuckDB file not found: {duck_path}")
        return 1
    log.info(f"Source: {duck_path}")

    log.info(f"Target: postgresql://{PG_USER}@{PG_HOST}/{PG_DATABASE} (Entra auth)")

    duck = duckdb.connect(str(duck_path), read_only=True)
    try:
        pg = pg_connect()
    except Exception as e:
        log.error(f"Postgres connection failed: {e}")
        log.error("Hint: 'az login' and check FSLAPP_PG_HOST is set or DNS resolves.")
        return 2

    try:
        with pg.cursor() as cur:
            cur.execute("SELECT current_user, current_database(), current_setting('search_path')")
            row = cur.fetchone()
            log.info(f"Connected as: {row[0]} on {row[1]} (search_path={row[2]})")

        results = {}
        targets = [t for t in TABLES if args.table is None or t[0] == args.table]
        if not targets:
            log.error(f"--table {args.table} not in known list: {[t[0] for t in TABLES]}")
            return 3
        log.info(f"Plan: copy {len(targets)} table(s)" +
                 (f" (last {args.days} days)" if args.days else " (ALL rows)"))
        for duck_table, pg_schema, pg_table, pk, time_col in targets:
            log.info(f"")
            log.info(f"=== {duck_table} → {pg_schema}.{pg_table} ===")
            results[duck_table] = copy_table(
                duck, pg, duck_table, pg_schema, pg_table, pk, time_col, args.days,
                dry_run=args.dry_run, truncate_first=args.truncate_first,
            )

        log.info("")
        log.info("=== Summary ===")
        total_rows = 0
        for tbl, r in results.items():
            inserted = r.get('inserted', 0)
            total = r.get('rows', 0)
            elapsed = r.get('elapsed_s', 0)
            total_rows += inserted
            tag = 'DRY' if r.get('dry_run') else 'OK ' if r.get('inserted') == r.get('rows') else 'PARTIAL'
            log.info(f"  [{tag}] {tbl:25s}  {inserted:>9}/{total:<9} rows  {elapsed:.1f}s")
        log.info(f"Total rows written: {total_rows}")

        if not args.dry_run:
            log.info("")
            log.info("Running ANALYZE on optimizer.* tables…")
            with pg.cursor() as cur:
                for _, schema, table, _, _ in targets:
                    cur.execute(f"ANALYZE {schema}.{table}")
            pg.commit()
            log.info("ANALYZE done.")

    finally:
        pg.close()
        duck.close()

    log.info("")
    log.info("✅ ETL complete.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
