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
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger('db_backup')

_CONN      = os.environ.get('AZ_OPT_CONNECTION_STRING')
_CONTAINER = os.environ.get('AZ_OPT_CONTAINER', 'optimizer-files')
_FOLDER    = 'db-backups'
_KEEP      = 7
_INTERVAL  = 6 * 3600  # 6 hours

_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_LOCAL_DIR = Path('/home/fslapp/db_backups') if _ON_AZURE else Path.home() / '.fslapp' / 'db_backups'

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


def _sas_url(blob_name: str, hours: int = 2) -> str:
    """Generate a time-limited SAS URL for a blob (bypasses public-access restrictions)."""
    try:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas
        m_name = re.search(r'AccountName=([^;]+)', _CONN or '')
        m_key  = re.search(r'AccountKey=([^;]+)',  _CONN or '')
        if not m_name or not m_key:
            return ''
        token = generate_blob_sas(
            account_name=m_name.group(1),
            container_name=_CONTAINER,
            blob_name=blob_name,
            account_key=m_key.group(1),
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=hours),
        )
        return f"https://{m_name.group(1)}.blob.core.windows.net/{_CONTAINER}/{blob_name}?{token}"
    except Exception as exc:
        log.debug(f"SAS URL generation failed: {exc}")
        return ''


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

def _save_local(payload: bytes, filename: str) -> Path:
    """Write a backup payload to the local fallback directory."""
    _LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    path = _LOCAL_DIR / filename
    path.write_bytes(payload)
    # Prune local dir to _KEEP files
    local_files = sorted(_LOCAL_DIR.glob('fslapp_*.json'), key=lambda p: p.name, reverse=True)
    for old in local_files[_KEEP:]:
        try:
            old.unlink()
        except Exception:
            pass
    return path


def backup_now() -> str:
    """Export Postgres core.* critical tables. Uploads to Azure Blob if configured,
    otherwise saves to local fallback directory. Returns blob name or local path."""
    data = _export_tables()
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    filename = f"fslapp_{ts}.json"
    payload = json.dumps(data, default=str).encode('utf-8')
    if _CONN:
        blob_name = f"{_FOLDER}/{filename}"
        _container().get_blob_client(blob_name).upload_blob(payload, overwrite=True)
        log.info(f"DB backup uploaded: {blob_name} ({len(payload):,} bytes)")
        _prune_old_backups()
        _save_local(payload, filename)  # keep a local copy too
        return blob_name
    else:
        path = _save_local(payload, filename)
        log.info(f"DB backup saved locally (no Azure): {path} ({len(payload):,} bytes)")
        return str(path)


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


def _list_local_backups() -> list[dict]:
    """Return metadata for backup files saved in the local fallback directory."""
    if not _LOCAL_DIR.exists():
        return []
    items = []
    for path in sorted(_LOCAL_DIR.glob('fslapp_*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = path.stat()
            items.append({
                "id": str(path),
                "name": path.name,
                "file_name": path.name,
                "source": "Local file",
                "path": str(path),
                "size_bytes": int(stat.st_size),
                "last_modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "recoverable": True,
            })
        except Exception:
            pass
    return items


def list_backups(limit: int = 20) -> dict:
    """Return read-only metadata for existing DB backups (Azure Blob + local files)."""
    info = {
        "configured": bool(_CONN),
        "container": _CONTAINER,
        "folder": _FOLDER,
        "items": [],
    }
    # Always include local backups
    info["items"].extend(_list_local_backups())
    if not _CONN:
        info["error"] = "AZ_OPT_CONNECTION_STRING not set — showing local backups only"
        return info
    try:
        container = _container()
        blobs = sorted(
            [b for b in container.list_blobs(name_starts_with=f"{_FOLDER}/fslapp_")],
            key=lambda b: (b.last_modified or datetime.min.replace(tzinfo=timezone.utc), b.name),
            reverse=True,
        )[:limit]
        for blob in blobs:
            info["items"].append({
                "id": blob.name,
                "name": blob.name,
                "file_name": blob.name.rsplit("/", 1)[-1],
                "source": "Azure Blob",
                "container": _CONTAINER,
                "size_bytes": int(blob.size or 0),
                "last_modified": blob.last_modified.isoformat() if blob.last_modified else "",
                "open_url": _sas_url(blob.name),
                "recoverable": True,
            })
    except Exception as e:
        info["error"] = str(e)
    return info


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
