"""Watchlist repository — manual SA watchlist CRUD."""

import logging
import db_adapter

_log = logging.getLogger("repo.watchlist")


def watchlist_add(sa_number: str, sa_id: str, added_by: str):
    """Add or replace a watchlist entry."""
    with db_adapter.writer() as db:
        db.execute(
            """
            INSERT INTO watchlist_manual (sa_number, sa_id, added_by)
            VALUES (%s, %s, %s)
            ON CONFLICT (sa_number) DO UPDATE SET
                sa_id = EXCLUDED.sa_id,
                added_by = EXCLUDED.added_by,
                added_at = CURRENT_TIMESTAMP
            """,
            (sa_number, sa_id, added_by),
        )
    _log.info(f"Watchlist add: {sa_number} by {added_by}")


def watchlist_remove(sa_number: str):
    """Remove a watchlist entry."""
    with db_adapter.writer() as db:
        db.execute(
            "DELETE FROM watchlist_manual WHERE sa_number = %s",
            (sa_number,),
        )
    _log.info(f"Watchlist remove: {sa_number}")


def watchlist_list() -> list[dict]:
    """Return all watchlist entries ordered by added_at descending."""
    with db_adapter.reader() as db:
        db.execute(
            """
            SELECT sa_number, sa_id, added_by, added_at
            FROM watchlist_manual
            ORDER BY added_at DESC
            """,
        )
        rows = db.fetchall()
    _log.debug(f"Watchlist list: {len(rows)} rows")
    return rows
