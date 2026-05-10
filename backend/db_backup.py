"""Automatic Postgres core.* backup to Azure Blob Storage.

Exports critical tables (users, settings, config — NOT cache/logs) as JSON
to the same container used by optimizer_blob_sync, under db-backups/.

Schedule: every 6 hours. Keeps last 7 backups.

Restore: call restore_latest() to recover Postgres core.* from the latest blob.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger('db_backup')

_CONN      = os.environ.get('AZ_OPT_CONNECTION_STRING')
_CONTAINER = os.environ.get('AZ_OPT_CONTAINER', 'optimizer-files')
_FOLDER    = 'db-backups'
_KEEP      = 7
_INTERVAL  = 6 * 3600  # 6 hours

# Tables worth backing up — skip cache, activity_log, opt_sync_audit (ephemeral)
_TABLES = ['users', 'settings', 'bonus_tiers', 'accounting_rates',
           'woa_reviews', 'watchlist_manual']


# ── Blob helpers ──────────────────────────────────────────────────────────────

def _client():
    if not _CONN:
        raise RuntimeError("AZ_OPT_CONNECTION_STRING not set — cannot backup DB")
    from azure.storage.blob import BlobServiceClient
    return BlobServiceClient.from_connection_string(_CONN)


def _container():
    return _client().get_container_client(_CONTAINER)


# ── Export / import ───────────────────────────────────────────────────────────

def _export_tables() -> dict:
    """Read all critical tables from Postgres core.* and return as a dict."""
    import pg_pool
    data = {'_version': 2, '_exported_at': datetime.now(timezone.utc).isoformat()}
    with pg_pool.reader() as conn:
        conn.execute("SET search_path = core, public")
        for table in _TABLES:
            try:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT * FROM "{table}"')
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchall()
                    data[table] = [dict(zip(cols, row)) for row in rows]
                    log.debug(f"Exported {table}: {len(rows)} rows")
            except Exception as e:
                log.warning(f"Could not export {table}: {e}")
                data[table] = []
    return data


def _import_tables(data: dict):
    """Write backed-up data into Postgres core.* (ON CONFLICT DO NOTHING — never overwrites existing)."""
    import pg_pool
    restored = {}
    with pg_pool.writer() as conn:
        conn.execute("SET search_path = core, public")
        for table in _TABLES:
            rows = data.get(table, [])
            if not rows:
                continue
            try:
                cols = list(rows[0].keys())
                placeholders = ', '.join(['%s'] * len(cols))
                col_names = ', '.join(f'"{c}"' for c in cols)
                with conn.cursor() as cur:
                    cur.executemany(
                        f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING',
                        [tuple(r.get(c) for c in cols) for r in rows],
                    )
                restored[table] = len(rows)
            except Exception as e:
                log.warning(f"Could not restore {table}: {e}")
        conn.commit()
    log.info(f"Restored from backup: {restored}")


# ── Backup / restore ──────────────────────────────────────────────────────────

def backup_now() -> str:
    """Export Postgres core.* critical tables and upload to Azure Blob. Returns blob name."""
    data = _export_tables()
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    blob_name = f"{_FOLDER}/fslapp_{ts}.json"
    payload = json.dumps(data, default=str).encode('utf-8')
    _container().get_blob_client(blob_name).upload_blob(payload, overwrite=True)
    log.info(f"DB backup uploaded: {blob_name} ({len(payload):,} bytes)")
    _prune_old_backups()
    return blob_name


def _prune_old_backups():
    """Delete backups older than the most recent _KEEP."""
    container = _container()
    blobs = sorted(
        [b for b in container.list_blobs(name_starts_with=f"{_FOLDER}/fslapp_")],
        key=lambda b: b.name,
        reverse=True,
    )
    for old in blobs[_KEEP:]:
        try:
            container.get_blob_client(old.name).delete_blob()
            log.info(f"Pruned old backup: {old.name}")
        except Exception as e:
            log.warning(f"Could not prune {old.name}: {e}")


def restore_latest() -> bool:
    """Download the most recent backup and import into Postgres core.*. Returns True if restored."""
    if not _CONN:
        log.warning("AZ_OPT_CONNECTION_STRING not set — cannot restore backup")
        return False
    try:
        container = _container()
        blobs = sorted(
            [b for b in container.list_blobs(name_starts_with=f"{_FOLDER}/fslapp_")],
            key=lambda b: b.name,
            reverse=True,
        )
        if not blobs:
            log.info("No backups found in Azure Blob — starting fresh")
            return False
        latest = blobs[0].name
        log.info(f"Restoring from backup: {latest}")
        raw = container.get_blob_client(latest).download_blob().readall()
        data = json.loads(raw)
        _import_tables(data)
        return True
    except Exception as e:
        log.error(f"Backup restore failed: {e}")
        return False


# ── Background loop ───────────────────────────────────────────────────────────

_thread: threading.Thread | None = None


def _loop():
    # Stagger first run by 5 min so startup isn't overloaded
    time.sleep(300)
    while True:
        try:
            backup_now()
        except Exception as e:
            log.error(f"DB backup failed: {e}")
        time.sleep(_INTERVAL)


def start():
    """Spawn background backup thread (idempotent)."""
    global _thread
    if not _CONN:
        log.warning("AZ_OPT_CONNECTION_STRING not set — DB auto-backup disabled")
        return
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, daemon=True, name='db_backup')
    _thread.start()
    log.info(f"DB backup thread started (every {_INTERVAL//3600}h, keep {_KEEP})")
