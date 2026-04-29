#!/usr/bin/env python3
"""One-time backfill script: pulls last N days of optimizer runs from SF into DuckDB.

Usage:
    python optimizer_init.py --days 30
    python optimizer_init.py --days 30 --force   # re-process runs already in DB
"""

import argparse, logging, os, sys, time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'), override=False)
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=False)

import optimizer_db
import optimizer_sync
import database

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('optimizer_init')

_PAGE_SIZE = 50
_THROTTLE_S = 0.5  # sleep between pages to avoid SF rate limits


def main():
    parser = argparse.ArgumentParser(description='Backfill optimizer runs into DuckDB')
    parser.add_argument('--days', type=int, default=30, help='Days to backfill (default 30)')
    parser.add_argument('--force', action='store_true', help='Re-process runs already in DB')
    args = parser.parse_args()

    optimizer_db.init_db()
    database.init_db()

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    log.info(f"Backfilling optimizer runs since {since} ({args.days} days)")

    total_inserted = total_skipped = total_failed = total_verdicts = 0
    offset = 0
    page = 0
    territory_cache: dict[str, str] = {}

    while True:
        page += 1
        soql = (
            f"SELECT Id,Name,CreatedDate FROM FSL__Optimization_Request__c"
            f" WHERE CreatedDate >= {since}"
            f" ORDER BY CreatedDate ASC LIMIT {_PAGE_SIZE} OFFSET {offset}"
        )
        data = optimizer_sync._sf_query(soql)
        sf_runs = data.get('records', [])
        if not sf_runs:
            break

        log.info(f"Page {page}: {len(sf_runs)} runs (offset {offset})")

        # Filter already-stored runs unless --force
        if not args.force:
            run_ids = [r['Id'] for r in sf_runs]
            with optimizer_db.get_conn(read_only=True) as conn:
                placeholders = ','.join(['?'] * len(run_ids))
                existing = {row[0] for row in conn.execute(
                    f"SELECT id FROM opt_runs WHERE id IN ({placeholders})", run_ids
                ).fetchall()}
            new_runs = [r for r in sf_runs if r['Id'] not in existing]
            skipped_n = len(sf_runs) - len(new_runs)
            total_skipped += skipped_n
            if skipped_n:
                log.info(f"  Skipped {skipped_n} already in DB")
        else:
            new_runs = sf_runs

        # Batch-fetch content versions for this page (2 SOQL queries regardless of page size)
        cv_map = optimizer_sync._batch_get_content_versions([r['Id'] for r in new_runs])

        for sf_run in new_runs:
            run_id = sf_run['Id']
            run_name = sf_run.get('Name', run_id)
            run_at = sf_run['CreatedDate']

            try:
                req_cv_id, resp_cv_id = cv_map.get(run_id, (None, None))
                if not req_cv_id or not resp_cv_id:
                    log.warning(f"  {run_name}: no content versions — skipping")
                    total_failed += 1
                    continue

                req_json = optimizer_sync._download_json(req_cv_id)
                resp_json = optimizer_sync._download_json(resp_cv_id)
                run_row, sa_decs, verdicts = optimizer_sync._parse_run(
                    run_id, run_name, run_at, req_json, resp_json
                )
                territory_id = run_row['territory_id']
                if territory_id not in territory_cache:
                    territory_cache[territory_id] = optimizer_sync._resolve_territory_name(territory_id)
                run_row['territory_name'] = territory_cache[territory_id]
                if args.force:
                    # Delete existing rows so INSERT OR IGNORE actually replaces them
                    with optimizer_db.get_conn() as conn:
                        conn.execute("DELETE FROM opt_driver_verdicts WHERE run_id=?", [run_id])
                        conn.execute("DELETE FROM opt_sa_decisions WHERE run_id=?", [run_id])
                        conn.execute("DELETE FROM opt_runs WHERE id=?", [run_id])
                n_verdicts = optimizer_sync._insert_run(run_row, sa_decs, verdicts)
                total_inserted += 1
                total_verdicts += n_verdicts
                log.info(f"  + {run_name}: {len(sa_decs)} SAs, {n_verdicts} verdicts")

            except Exception as e:
                log.error(f"  ! {run_name}: {e}")
                total_failed += 1

        offset += len(sf_runs)
        if len(sf_runs) < _PAGE_SIZE:
            break
        time.sleep(_THROTTLE_S)

    print(
        f"\nBackfill complete — inserted: {total_inserted}  skipped: {total_skipped}"
        f"  failed: {total_failed}  verdicts: {total_verdicts}"
    )


if __name__ == '__main__':
    main()
