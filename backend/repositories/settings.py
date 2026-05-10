import json
import logging

import db_adapter

log = logging.getLogger("repo.settings")


def get_setting(key: str, default=None):
    """Get a setting value. Returns parsed JSON or default."""
    with db_adapter.reader() as db:
        row = db.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]
    return default


def put_setting(key: str, value):
    """Set a setting value (stored as JSON)."""
    with db_adapter.writer() as db:
        db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            (key, json.dumps(value)),
        )
    log.debug("Setting %s updated", key)


def get_all_settings() -> dict[str, str]:
    """Get all settings as a dict."""
    with db_adapter.reader() as db:
        rows = db.execute("SELECT key, value FROM settings").fetchall()
        result = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                result[row["key"]] = row["value"]
        return result


def delete_setting(key: str):
    """Delete a setting."""
    with db_adapter.writer() as db:
        db.execute("DELETE FROM settings WHERE key = %s", (key,))
    log.debug("Setting %s deleted", key)
