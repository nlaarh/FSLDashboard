"""Driver Collection audit repository — verification checkbox persistence.

Backs the contractor "Driver Collection" tab. One row per (username, wo_id, reason)
records that the contractor verified payment was collected for that matched reason.

All SQL uses %s placeholders (db_adapter handles SQLite conversion). Table lives in
the `core` schema (db_adapter sets search_path = core, public).
"""

import logging

import db_adapter

log = logging.getLogger("repo.driver_collection")


def get_verified_keys(username: str) -> set[tuple[str, str]]:
    """Return the set of (wo_id, reason) tuples this contractor has verified."""
    try:
        with db_adapter.reader() as db:
            db.execute(
                "SELECT wo_id, reason FROM driver_collection_audit "
                "WHERE username = %s AND verified = true",
                (username,),
            )
            return {(r["wo_id"], r["reason"]) for r in db.fetchall()}
    except Exception as e:
        log.warning(f"[repo.driver_collection] get_verified_keys failed: {e}")
        raise


def set_verified(username: str, wo_id: str, reason: str, verified: bool) -> None:
    """Upsert when verified=True, delete the row when verified=False."""
    try:
        with db_adapter.writer() as db:
            if verified:
                db.execute(
                    """
                    INSERT INTO driver_collection_audit (username, wo_id, reason, verified, verified_at)
                    VALUES (%s, %s, %s, true, now())
                    ON CONFLICT (username, wo_id, reason)
                    DO UPDATE SET verified = true, verified_at = now()
                    """,
                    (username, wo_id, reason),
                )
            else:
                db.execute(
                    "DELETE FROM driver_collection_audit "
                    "WHERE username = %s AND wo_id = %s AND reason = %s",
                    (username, wo_id, reason),
                )
            db.commit()
    except Exception as e:
        log.warning(f"[repo.driver_collection] set_verified failed: {e}")
        raise
