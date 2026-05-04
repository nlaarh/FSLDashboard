"""Azure Blob → DuckDB sync. Polls every 30s, idempotent via opt_blob_audit table.

Reads request/response JSON pairs from Azure container (uploaded by
optimizer_extractor.runner), parses with optimizer_parser, loads into DuckDB.

Replaces the old optimizer_sync.py ContentVersion polling.
"""

import os
import json
import time
import logging
import threading
from datetime import datetime
from azure.storage.blob import BlobServiceClient

import optimizer_db
import optimizer_parser

log = logging.getLogger('optimizer_blob_sync')

PARSER_VERSION = optimizer_parser.PARSER_VERSION
POLL_INTERVAL_S = 30

# In-memory caches for SF lookup data — refreshed periodically.
_RESOURCE_NAMES: dict[str, str] = {}    # ServiceResource Id → Name
_SKILL_NAMES:    dict[str, str] = {}    # Skill Id → MasterLabel
_TERRITORY_NAMES: dict[str, str] = {}   # ServiceTerritory Id → Name
_LOOKUPS_LAST_REFRESH = 0


def _refresh_lookups(force: bool = False) -> None:
    """Pull Resource/Skill/Territory ID→Name from SF once per hour. Cached in memory + DuckDB."""
    global _LOOKUPS_LAST_REFRESH
    now = time.time()
    if not force and (now - _LOOKUPS_LAST_REFRESH) < 3600:
        return
    import urllib.request, urllib.parse
    try:
        from sf_client import get_auth
        token, instance = get_auth()

        def _soql(q: str) -> list:
            url = f"{instance}/services/data/v59.0/query?q={urllib.parse.quote(q)}"
            req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
            return json.loads(urllib.request.urlopen(req).read()).get('records', [])

        # ServiceResource → Name
        for r in _soql("SELECT Id, Name FROM ServiceResource"):
            _RESOURCE_NAMES[r['Id']] = r.get('Name') or r['Id']

        # Skill → MasterLabel (or DeveloperName fallback)
        for s in _soql("SELECT Id, MasterLabel, DeveloperName FROM Skill"):
            _SKILL_NAMES[s['Id']] = s.get('MasterLabel') or s.get('DeveloperName') or s['Id']

        # ServiceTerritory → Name
        for t in _soql("SELECT Id, Name FROM ServiceTerritory"):
            _TERRITORY_NAMES[t['Id']] = t.get('Name') or t['Id']

        _LOOKUPS_LAST_REFRESH = now
        # Persist resources for cross-restart
        optimizer_db.upsert_resource_names(
            [{'id': k, 'name': v} for k, v in _RESOURCE_NAMES.items()]
        )
        log.info(f"Refreshed lookups: {len(_RESOURCE_NAMES)} drivers, "
                 f"{len(_SKILL_NAMES)} skills, {len(_TERRITORY_NAMES)} territories")
    except Exception as e:
        log.warning(f"Could not refresh SF lookups: {e}")
        # Fallback: at least load resources we already cached in DuckDB
        try:
            with optimizer_db.get_conn() as conn:
                for rid, name in conn.execute("SELECT id, name FROM opt_resources").fetchall():
                    _RESOURCE_NAMES.setdefault(rid, name)
        except Exception:
            pass


# Backward-compatibility alias
def _refresh_resource_names(force: bool = False) -> None:
    _refresh_lookups(force)

_CONN = os.environ.get('AZ_OPT_CONNECTION_STRING')
_CONTAINER = os.environ.get('AZ_OPT_CONTAINER', 'optimizer-files')


# ── Schema migration: blob audit table ───────────────────────────────────────

def _ensure_audit_table() -> None:
    with optimizer_db.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS opt_blob_audit (
                run_id          VARCHAR PRIMARY KEY,
                blob_prefix     VARCHAR NOT NULL,
                blob_modified   TIMESTAMP,
                processed_at    TIMESTAMP DEFAULT now(),
                parser_version  VARCHAR,
                status          VARCHAR,
                error_message   VARCHAR
            )
        """)


# ── Azure blob enumeration ───────────────────────────────────────────────────

def _client() -> BlobServiceClient:
    if not _CONN:
        raise RuntimeError("AZ_OPT_CONNECTION_STRING not set")
    return BlobServiceClient.from_connection_string(_CONN)


def _list_run_blobs() -> dict[str, dict]:
    """Return {run_id: {prefix, last_modified, has_request, has_response}}"""
    container = _client().get_container_client(_CONTAINER)
    runs: dict[str, dict] = {}
    for blob in container.list_blobs():
        # name = "2026-04-30/a1uPb000009dFZtIAM/request.json"
        parts = blob.name.split('/')
        if len(parts) != 3:
            continue
        date_str, run_id, fname = parts
        slot = runs.setdefault(run_id, {
            'prefix': f"{date_str}/{run_id}",
            'last_modified': None,
            'has_request': False,
            'has_response': False,
        })
        if fname == 'request.json':
            slot['has_request'] = True
        elif fname == 'response.json':
            slot['has_response'] = True
        if not slot['last_modified'] or blob.last_modified > slot['last_modified']:
            slot['last_modified'] = blob.last_modified
    return runs


def _download_pair(prefix: str) -> tuple[dict, dict, dict]:
    """Download request/response/metadata JSONs from blob prefix."""
    container = _client().get_container_client(_CONTAINER)
    req_bytes = container.get_blob_client(f"{prefix}/request.json").download_blob().readall()
    resp_bytes = container.get_blob_client(f"{prefix}/response.json").download_blob().readall()
    meta_bytes = container.get_blob_client(f"{prefix}/metadata.json").download_blob().readall()
    return json.loads(req_bytes), json.loads(resp_bytes), json.loads(meta_bytes)


# ── Sync logic ───────────────────────────────────────────────────────────────

def _already_processed(run_id: str) -> bool:
    """True iff this run has been parsed under the current PARSER_VERSION."""
    with optimizer_db.get_conn(read_only=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM opt_blob_audit WHERE run_id = ? AND parser_version = ? AND status = 'ok'",
            [run_id, PARSER_VERSION]
        ).fetchone()
        return row is not None


def _mark_processed(run_id: str, prefix: str, modified: datetime,
                     status: str, err: str | None = None) -> None:
    with optimizer_db.get_conn() as conn:
        conn.execute("""
            INSERT INTO opt_blob_audit (run_id, blob_prefix, blob_modified,
                                        processed_at, parser_version, status, error_message)
            VALUES (?, ?, ?, now(), ?, ?, ?)
            ON CONFLICT (run_id) DO UPDATE SET
                blob_prefix=excluded.blob_prefix,
                blob_modified=excluded.blob_modified,
                processed_at=excluded.processed_at,
                parser_version=excluded.parser_version,
                status=excluded.status,
                error_message=excluded.error_message
        """, [run_id, prefix, modified, PARSER_VERSION, status, err])


def process_run(run_id: str, slot: dict) -> str:
    """Download blob pair, parse, insert into DuckDB. Returns 'ok' / 'error_*'."""
    if not (slot['has_request'] and slot['has_response']):
        return 'incomplete'
    try:
        req, resp, meta = _download_pair(slot['prefix'])
    except Exception as e:
        _mark_processed(run_id, slot['prefix'], slot['last_modified'], 'download_error', str(e)[:500])
        return 'download_error'

    run_name = meta.get('run_name') or run_id
    run_at = meta.get('run_at') or datetime.now().isoformat()

    # Refresh SF lookups (driver names, skill labels, territory names) once per hour.
    # JSON has only IDs — names live on the SF objects, fetched via REST.
    _refresh_lookups()

    # Build name_map by intersecting request's Resource Ids with our cached names.
    # Inject into the request so parser can resolve names without code changes.
    for r in req.get('Resources', []):
        rid = r.get('Id')
        if rid and not r.get('Name'):
            r['Name'] = _RESOURCE_NAMES.get(rid, rid)
    for s in req.get('Skills', []):
        sid = s.get('Id')
        if sid and not s.get('MasterLabel'):
            s['MasterLabel'] = _SKILL_NAMES.get(sid, sid)
    for t in req.get('Territories', []):
        tid = t.get('Id')
        if tid and not t.get('Name'):
            t['Name'] = _TERRITORY_NAMES.get(tid, tid)

    name_map = dict(_RESOURCE_NAMES)   # pass full cache; parser keys by Resource Id

    try:
        run_row, sa_decisions, driver_verdicts = optimizer_parser.parse_run(
            run_id, run_name, run_at, req, resp, name_map
        )
    except Exception as e:
        log.exception(f"[{run_id}] parser failed")
        _mark_processed(run_id, slot['prefix'], slot['last_modified'], 'parse_error', str(e)[:500])
        return 'parse_error'

    # Insert with PK-based dedup. Pull batch grouping fields from metadata.
    # Backend-aware: optimizer_db.upsert_* dispatches to DuckDB's INSERT OR REPLACE
    # or Postgres's INSERT … ON CONFLICT DO UPDATE based on OPT_DB_BACKEND.
    run_row['batch_id']   = meta.get('batch_id')
    run_row['chunk_num']  = meta.get('chunk_num')
    run_row['fsl_type']   = meta.get('fsl_type')
    run_row['fsl_status'] = meta.get('fsl_status')

    optimizer_db.upsert_run(run_row)
    if sa_decisions:
        optimizer_db.bulk_upsert_decisions(sa_decisions)
    if driver_verdicts:
        # Default driver_skills/driver_territory to empty string for back-compat with
        # the original DuckDB schema where these columns were added later.
        for v in driver_verdicts:
            v.setdefault('driver_skills', '')
            v.setdefault('driver_territory', '')
        optimizer_db.bulk_upsert_verdicts(driver_verdicts)

    optimizer_db.upsert_resource_names([{'id': k, 'name': v} for k, v in name_map.items()])
    _mark_processed(run_id, slot['prefix'], slot['last_modified'], 'ok')
    log.info(f"[{run_id}] ingested: {len(sa_decisions)} decisions, {len(driver_verdicts)} verdicts")
    return 'ok'


def sync_once() -> dict:
    """Run one sync pass. Returns counts."""
    _ensure_audit_table()
    optimizer_db.init_db()
    runs = _list_run_blobs()
    counts = {'total': len(runs), 'ok': 0, 'skipped': 0, 'incomplete': 0, 'failed': 0}
    for run_id, slot in runs.items():
        if _already_processed(run_id):
            counts['skipped'] += 1
            continue
        result = process_run(run_id, slot)
        if result == 'ok':
            counts['ok'] += 1
        elif result == 'incomplete':
            counts['incomplete'] += 1
        else:
            counts['failed'] += 1
    return counts


# ── Background loop (used by main.py at startup) ─────────────────────────────

_thread = None


def _loop():
    log.info(f"Blob sync loop started (poll={POLL_INTERVAL_S}s, parser={PARSER_VERSION})")
    while True:
        try:
            counts = sync_once()
            if counts['ok'] > 0:
                log.info(f"Sync: {counts}")
        except Exception as e:
            log.exception(f"Sync loop error: {e}")
        time.sleep(POLL_INTERVAL_S)


def start():
    """Spawn the background sync thread (idempotent)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, daemon=True, name='opt_blob_sync')
    _thread.start()
    log.info("optimizer_blob_sync thread spawned")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    print(json.dumps(sync_once(), indent=2))
