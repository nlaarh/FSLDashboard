"""Optimizer sync audit repository."""

import logging
import db_adapter

_log = logging.getLogger("repo.optimizer")


def write_sync_audit(
    started_at,
    finished_at,
    status,
    runs_found=0,
    runs_inserted=0,
    runs_skipped=0,
    runs_failed=0,
    verdicts_inserted=0,
    rows_purged=0,
    error_detail=None,
    duration_ms=0,
):
    """Insert a new optimizer sync audit row."""
    with db_adapter.writer() as db:
        db.execute(
            """
            INSERT INTO opt_sync_audit
                (started_at, finished_at, status, runs_found, runs_inserted,
                 runs_skipped, runs_failed, verdicts_inserted, rows_purged,
                 error_detail, duration_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                started_at,
                finished_at,
                status,
                runs_found,
                runs_inserted,
                runs_skipped,
                runs_failed,
                verdicts_inserted,
                rows_purged,
                error_detail,
                duration_ms,
            ),
        )
    _log.info(f"Sync audit written: status={status} duration={duration_ms}ms")


def get_sync_audit(limit: int = 50) -> list[dict]:
    """Return recent sync audit rows ordered by id descending."""
    with db_adapter.reader() as db:
        db.execute(
            """
            SELECT id, started_at, finished_at, status, runs_found, runs_inserted,
                   runs_skipped, runs_failed, verdicts_inserted, rows_purged,
                   error_detail, duration_ms
            FROM opt_sync_audit
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = db.fetchall()
    _log.debug(f"Sync audit fetched: {len(rows)} rows")
    return rows
