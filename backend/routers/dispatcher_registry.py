"""Dispatcher registry — DB-backed source of truth, SF User ID auto-resolved on demand."""

import logging
import db_adapter
from sf_client import sf_query_all

log = logging.getLogger('dispatcher_registry')

_POSITION_TO_ROLE = {
    'Manager':           'ers-manager',
    'Supervisor':        'ers-supervisor',
    'Assistant Manager': 'ers-supervisor',
    'Dispatcher':        'ers-dispatcher',
}


def load_dispatchers(resolve_sf_ids: bool = True) -> dict:
    """Load active dispatcher registry from DB.

    Returns {email: {sf_id, name, role, channel, observer}}.
    If resolve_sf_ids=True, auto-fetches missing SF User IDs from Salesforce
    and persists them so subsequent calls are instant.
    """
    try:
        with db_adapter.reader() as db:
            db.execute("""
                SELECT email, first_name, last_name, position, sf_user_id, channel, observer
                FROM dispatchers
                WHERE active = TRUE
                ORDER BY last_name, first_name
            """)
            rows = db.fetchall()
    except Exception as e:
        log.error("Failed to load dispatcher registry: %s", e)
        return {}

    registry: dict = {}
    missing: list = []

    for r in rows:
        email    = r['email']
        first    = r['first_name']
        last     = r['last_name']
        position = r['position']
        sf_id    = r['sf_user_id']
        channel  = r['channel']
        observer = r['observer']
        registry[email] = {
            "sf_id":    sf_id,
            "name":     f"{first} {last}",
            "role":     _POSITION_TO_ROLE.get(position or '', 'ers-dispatcher'),
            "channel":  channel,
            "observer": bool(observer),
        }
        # Observers excluded from SF scoring — no SF ID needed
        if not sf_id and not observer:
            missing.append(email)

    if resolve_sf_ids and missing:
        _resolve_and_persist(missing, registry)

    return registry


def _resolve_and_persist(emails: list, registry: dict):
    """Query SF for User records matching these email/usernames, update registry and persist."""
    email_list = ", ".join(f"'{e}'" for e in emails)
    try:
        rows = sf_query_all(
            f"SELECT Id, Username FROM User WHERE Username IN ({email_list}) AND IsActive = TRUE"
        )
    except Exception as e:
        log.warning("SF User ID resolution failed: %s", e)
        return

    resolved = {r["Username"]: r["Id"] for r in rows if r.get("Username") and r.get("Id")}
    if not resolved:
        return

    for email, sf_id in resolved.items():
        if email in registry:
            registry[email]["sf_id"] = sf_id

    try:
        with db_adapter.writer() as db:
            for email, sf_id in resolved.items():
                db.execute(
                    "UPDATE dispatchers SET sf_user_id = %s WHERE email = %s AND sf_user_id IS NULL",
                    (sf_id, email),
                )
        log.info("Resolved and persisted %d SF User IDs", len(resolved))
    except Exception as e:
        log.warning("Failed to persist resolved SF IDs: %s", e)
