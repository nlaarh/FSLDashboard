"""Daily retention job — purges optimizer rows older than N days.

Why: at ~290 runs/day × ~6,200 verdicts/run, opt_driver_verdicts grows by
~1.8M rows/day. Without retention, Postgres fills up in ~6 months.

Schedule: run once per day (App Service WebJob, Azure Function timer, or cron).
Idempotent + safe — only DELETEs by run_at; opt_resources / opt_runs metadata
small enough to keep indefinitely.

Usage:
    python -m optimizer_retention                     # default 3 days
    python -m optimizer_retention --days 7            # custom window
    python -m optimizer_retention --days 3 --dry-run  # preview only
"""

import argparse
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('retention')

DEFAULT_DAYS = int(os.environ.get('FSLAPP_RETENTION_DAYS', '3'))


# Tables eligible for retention purge. Order matters — verdicts first to avoid FK issues.
# Each entry: (schema, table, time_col).
PURGE_TABLES = [
    ('optimizer', 'opt_driver_verdicts', 'run_at'),       # ~1.8M rows/day, biggest
    ('optimizer', 'opt_sa_decisions',    'run_at'),       # ~60K rows/day
    ('optimizer', 'opt_runs',            'run_at'),       # ~290 rows/day
    ('optimizer', 'opt_blob_audit',      'processed_at'), # one row per run
    ('optimizer', 'opt_sync_errors',     'failed_at'),    # only failed runs
]


def run_retention(days: int, dry_run: bool = False) -> dict:
    """Delete rows older than `days` from every retention-eligible table."""
    # Lazy import so the module can be imported without psycopg in scope
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / '.env', override=False)

    import pg_pool

    results = {}
    with pg_pool.writer() as conn:
        for schema, table, time_col in PURGE_TABLES:
            with conn.cursor() as cur:
                # Count first
                cur.execute(
                    f"SELECT COUNT(*) FROM {schema}.{table} "
                    f"WHERE {time_col} < now() - INTERVAL '{int(days)} days'"
                )
                to_delete = cur.fetchone()[0]
                total = cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}").fetchone()[0]

                if to_delete == 0:
                    log.info(f"  {schema}.{table}: {total:>9} rows total, none to purge")
                    results[table] = {'deleted': 0, 'kept': total}
                    continue

                if dry_run:
                    log.info(f"  {schema}.{table}: would DELETE {to_delete}/{total} ({100*to_delete//total}%)")
                    results[table] = {'deleted': 0, 'kept': total, 'would_delete': to_delete}
                    continue

                cur.execute(
                    f"DELETE FROM {schema}.{table} "
                    f"WHERE {time_col} < now() - INTERVAL '{int(days)} days'"
                )
                deleted = cur.rowcount
                log.info(f"  {schema}.{table}: deleted {deleted} rows (kept {total - deleted})")
                results[table] = {'deleted': deleted, 'kept': total - deleted}
        if not dry_run:
            conn.commit()

    if not dry_run:
        # ANALYZE rebuilds stats so the planner picks good indexes after the purge
        log.info("ANALYZE …")
        with pg_pool.writer() as conn:
            with conn.cursor() as cur:
                for schema, table, _ in PURGE_TABLES:
                    cur.execute(f"ANALYZE {schema}.{table}")
            conn.commit()

    return results


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--days', type=int, default=DEFAULT_DAYS,
                   help=f'Retention window in days (default: {DEFAULT_DAYS}, '
                        'overridable via FSLAPP_RETENTION_DAYS env var)')
    p.add_argument('--dry-run', action='store_true',
                   help='Show counts only, do not delete')
    args = p.parse_args()

    if args.days < 1:
        log.error(f"--days must be >= 1, got {args.days}")
        return 1

    log.info(f"Retention: keep last {args.days} days {'(DRY RUN)' if args.dry_run else ''}")
    results = run_retention(args.days, args.dry_run)

    total_deleted = sum(r.get('deleted', 0) for r in results.values())
    total_kept = sum(r.get('kept', 0) for r in results.values())
    log.info(f"Total: deleted {total_deleted}, kept {total_kept}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
