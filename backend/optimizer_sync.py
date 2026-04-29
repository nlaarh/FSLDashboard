"""Optimizer sync job — delta-pulls FSL optimization run files from SF into DuckDB.

Runs every 15 min via threading (same pattern as refresher.py).
Leader election via lock file — only one worker syncs across all gunicorn processes.
"""

import os, time, logging, threading, json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests as _requests
from sf_client import get_auth, refresh_auth
import optimizer_db
import database
from optimizer_parser import parse_run

log = logging.getLogger('optimizer_sync')

_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_LOCK_DIR = Path('/home/fslapp/locks') if _ON_AZURE else Path(os.path.expanduser('~/.fslapp/locks'))
_LOCK_FILE = _LOCK_DIR / '.optimizer_sync.lock'

_LEADER_STALE_AGE   = 90     # seconds — lock considered abandoned after this
_SYNC_INTERVAL      = 900    # 15 minutes
_SF_QUERY_TIMEOUT   = 60     # seconds for SOQL queries
_SF_BINARY_TIMEOUT  = 120    # seconds for ContentVersion downloads
_SOQL_CHUNK_SIZE    = 50     # max IDs per IN clause
_ERROR_TRUNCATE     = 500    # max chars stored for error messages
_MAX_RETRY_ATTEMPTS = 5      # abandon a run after this many failed retries
_RETRY_BATCH_SIZE   = 10     # failed runs to retry per tick


# ── Lock / leader election ────────────────────────────────────────────────────

def _acquire_lock() -> bool:
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    if _LOCK_FILE.exists():
        age = time.time() - _LOCK_FILE.stat().st_mtime
        if age < _LEADER_STALE_AGE:
            return False
        try:
            _LOCK_FILE.unlink()
        except Exception:
            return False
    try:
        with open(_LOCK_FILE, 'x') as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False
    except Exception:
        return False


def _release_lock():
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ── SF HTTP helpers ───────────────────────────────────────────────────────────

def _sf_request(url_suffix: str, timeout: int = _SF_QUERY_TIMEOUT,
                **kwargs) -> _requests.Response:
    """Authenticated SF GET with one 401 retry on token expiry."""
    token, instance = get_auth()
    url = f"{instance}{url_suffix}"
    r = _requests.get(url, headers={'Authorization': f'Bearer {token}'},
                      timeout=timeout, **kwargs)
    if r.status_code == 401:
        token, instance = refresh_auth()
        url = f"{instance}{url_suffix}"
        r = _requests.get(url, headers={'Authorization': f'Bearer {token}'},
                          timeout=timeout, **kwargs)
    r.raise_for_status()
    return r


def _sf_query(soql: str) -> dict:
    return _sf_request('/services/data/v59.0/query/',
                       params={'q': soql}).json()


def _sf_get_binary(path: str) -> bytes:
    return _sf_request(path, timeout=_SF_BINARY_TIMEOUT).content


def _sf_query_all(soql: str) -> list[dict]:
    """Paginate through all SF SOQL results, handling nextRecordsUrl."""
    data = _sf_query(soql)
    records = list(data.get('records', []))
    while not data.get('done', True):
        next_url = data.get('nextRecordsUrl', '')
        if not next_url:
            break
        data = _sf_request(next_url).json()
        records.extend(data.get('records', []))
    return records


# ── File resolution ───────────────────────────────────────────────────────────

def _batch_get_content_versions(run_ids: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """Return {run_id: (req_cv_id, resp_cv_id)} for a batch of run IDs in 2 SOQL queries."""
    if not run_ids:
        return {}

    ids_str = "','".join(run_ids)
    data = _sf_query(
        f"SELECT LinkedEntityId,ContentDocumentId,ContentDocument.Title"
        f" FROM ContentDocumentLink WHERE LinkedEntityId IN ('{ids_str}')"
    )

    run_docs: dict[str, dict[str, str]] = {}
    for rec in data.get('records', []):
        rid = rec['LinkedEntityId']
        doc_id = rec['ContentDocumentId']
        title = rec.get('ContentDocument', {}).get('Title', '')
        run_docs.setdefault(rid, {})
        if title.startswith('Request_'):
            run_docs[rid]['req'] = doc_id
        elif title.startswith('Response_'):
            run_docs[rid]['resp'] = doc_id

    all_doc_ids = list({doc_id for docs in run_docs.values() for doc_id in docs.values()})
    doc_to_cv: dict[str, str] = {}
    if all_doc_ids:
        for i in range(0, len(all_doc_ids), _SOQL_CHUNK_SIZE):
            chunk = all_doc_ids[i:i + _SOQL_CHUNK_SIZE]
            doc_ids_str = "','".join(chunk)
            cv_data = _sf_query(
                f"SELECT Id,ContentDocumentId FROM ContentVersion"
                f" WHERE ContentDocumentId IN ('{doc_ids_str}') AND IsLatest=true"
            )
            for rec in cv_data.get('records', []):
                doc_to_cv[rec['ContentDocumentId']] = rec['Id']

    result: dict[str, tuple[str | None, str | None]] = {}
    for run_id in run_ids:
        docs = run_docs.get(run_id, {})
        result[run_id] = (
            doc_to_cv.get(docs.get('req', '')),
            doc_to_cv.get(docs.get('resp', '')),
        )
    return result


def _download_json(cv_id: str) -> dict:
    raw = _sf_get_binary(f"/services/data/v59.0/sobjects/ContentVersion/{cv_id}/VersionData")
    return json.loads(raw)


# ── Resource name resolution ──────────────────────────────────────────────────

def _resolve_resource_names(resource_ids: list[str]) -> dict[str, str]:
    """Fetch ServiceResource Names for IDs not already in opt_resources."""
    if not resource_ids:
        return {}
    with optimizer_db.get_conn(read_only=True) as conn:
        rows = conn.execute(
            f"SELECT id, name FROM opt_resources WHERE id IN ({','.join(['?']*len(resource_ids))})",
            resource_ids
        ).fetchall()
    known = {r[0]: r[1] for r in rows}
    missing = [rid for rid in resource_ids if rid not in known]
    if not missing:
        return known

    names: dict[str, str] = dict(known)
    for i in range(0, len(missing), _SOQL_CHUNK_SIZE):
        chunk = missing[i:i + _SOQL_CHUNK_SIZE]
        ids_str = "','".join(chunk)
        data = _sf_query(
            f"SELECT Id,Name FROM ServiceResource WHERE Id IN ('{ids_str}')"
        )
        for rec in data.get('records', []):
            names[rec['Id']] = rec['Name']

    optimizer_db.upsert_resource_names([{'id': k, 'name': v} for k, v in names.items() if k in missing])
    return names


# ── Insert helper ─────────────────────────────────────────────────────────────

def _insert_run(run_row: dict, sa_decisions: list[dict], driver_verdicts: list[dict]) -> int:
    with optimizer_db.get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO opt_runs
               (id, name, territory_id, territory_name, policy_id, policy_name,
                run_at, horizon_start, horizon_end, resources_count, services_count,
                pre_scheduled, post_scheduled, unscheduled_count,
                pre_travel_time_s, post_travel_time_s, pre_response_avg_s, post_response_avg_s)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [run_row[k] for k in ('id','name','territory_id','territory_name','policy_id','policy_name',
                'run_at','horizon_start','horizon_end','resources_count','services_count',
                'pre_scheduled','post_scheduled','unscheduled_count',
                'pre_travel_time_s','post_travel_time_s','pre_response_avg_s','post_response_avg_s')]
        )
        if sa_decisions:
            conn.executemany(
                """INSERT OR IGNORE INTO opt_sa_decisions
                   (id, run_id, sa_id, sa_number, sa_work_type, action, unscheduled_reason,
                    winner_driver_id, winner_driver_name, winner_travel_time_min,
                    winner_travel_dist_mi, run_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [[dec[k] for k in ('id','run_id','sa_id','sa_number','sa_work_type','action',
                    'unscheduled_reason','winner_driver_id','winner_driver_name',
                    'winner_travel_time_min','winner_travel_dist_mi','run_at')]
                 for dec in sa_decisions]
            )
        if driver_verdicts:
            conn.executemany(
                """INSERT OR IGNORE INTO opt_driver_verdicts
                   (id, run_id, sa_id, driver_id, driver_name, status, exclusion_reason,
                    travel_time_min, travel_dist_mi, run_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [[v[k] for k in ('id','run_id','sa_id','driver_id','driver_name','status',
                    'exclusion_reason','travel_time_min','travel_dist_mi','run_at')]
                 for v in driver_verdicts]
            )
    return len(driver_verdicts)


# ── Territory name resolution ─────────────────────────────────────────────────

def _resolve_territory_name(territory_id: str) -> str:
    if not territory_id:
        return ''
    try:
        data = _sf_query(
            f"SELECT Name FROM ServiceTerritory WHERE Id='{territory_id}'"
        )
        recs = data.get('records', [])
        return recs[0]['Name'] if recs else territory_id
    except Exception:
        return territory_id


# ── Shared run-processing helper ──────────────────────────────────────────────

def _process_one_run(run_id: str, run_name: str, run_at: str,
                     req_json: dict, resp_json: dict,
                     territory_cache: dict) -> int:
    """Parse and insert one run. Returns verdict count. Raises on error."""
    resource_ids = [r['Id'] for r in req_json.get('Resources', [])]
    name_map = _resolve_resource_names(resource_ids)
    run_row, sa_decisions, driver_verdicts = parse_run(
        run_id, run_name, run_at, req_json, resp_json, name_map
    )
    territory_id = run_row['territory_id']
    if territory_id not in territory_cache:
        territory_cache[territory_id] = _resolve_territory_name(territory_id)
    run_row['territory_name'] = territory_cache[territory_id]
    return _insert_run(run_row, sa_decisions, driver_verdicts)


# ── Retry failed runs ─────────────────────────────────────────────────────────

def _retry_failed_run(run_id: str, run_name: str, territory_cache: dict, counts: dict):
    try:
        cv_map = _batch_get_content_versions([run_id])
        req_cv_id, resp_cv_id = cv_map.get(run_id, (None, None))
        if not req_cv_id or not resp_cv_id:
            with optimizer_db.get_conn() as conn:
                conn.execute(
                    "UPDATE opt_sync_errors SET attempts=attempts+1 WHERE run_id=?", [run_id]
                )
            return
        req_json = _download_json(req_cv_id)
        resp_json = _download_json(resp_cv_id)

        with optimizer_db.get_conn(read_only=True) as conn:
            opt_row = conn.execute("SELECT run_at FROM opt_runs WHERE id=?", [run_id]).fetchone()
            err_row = conn.execute("SELECT run_at FROM opt_sync_errors WHERE run_id=?", [run_id]).fetchone()
        if opt_row and opt_row[0]:
            run_at = str(opt_row[0])
        elif err_row and err_row[0]:
            run_at = str(err_row[0])
        else:
            log.warning(f"optimizer_sync: no run_at for retry of {run_name} — skipping")
            with optimizer_db.get_conn() as conn:
                conn.execute(
                    "UPDATE opt_sync_errors SET attempts=attempts+1 WHERE run_id=?", [run_id]
                )
            return

        _process_one_run(run_id, run_name, run_at, req_json, resp_json, territory_cache)
        with optimizer_db.get_conn() as conn:
            conn.execute(
                "UPDATE opt_sync_errors SET retried=true, attempts=attempts+1 WHERE run_id=?",
                [run_id]
            )
        counts['inserted'] += 1
    except Exception as e:
        log.warning(f"optimizer_sync: retry failed for {run_name}: {e}")
        with optimizer_db.get_conn() as conn:
            conn.execute(
                "UPDATE opt_sync_errors SET attempts=attempts+1 WHERE run_id=?", [run_id]
            )


# ── Main sync tick ────────────────────────────────────────────────────────────

def sync_tick(days: int = 30):
    """One sync cycle. Called by background thread every _SYNC_INTERVAL seconds."""
    started_at = datetime.now(timezone.utc).isoformat()
    start_ts = time.time()
    counts = dict(found=0, inserted=0, skipped=0, failed=0, verdicts=0, purged=0)
    status = 'success'
    error_detail = None
    territory_cache: dict[str, str] = {}

    try:
        # Step 1: retry previously failed runs (capped at _MAX_RETRY_ATTEMPTS)
        with optimizer_db.get_conn() as conn:
            errors = conn.execute(
                "SELECT run_id, run_name FROM opt_sync_errors"
                f" WHERE retried=false AND attempts < {_MAX_RETRY_ATTEMPTS}"
                f" LIMIT {_RETRY_BATCH_SIZE}"
            ).fetchall()
        for run_id, run_name in errors:
            _retry_failed_run(run_id, run_name, territory_cache, counts)

        # Step 2: determine cursor
        with optimizer_db.get_conn(read_only=True) as conn:
            row = conn.execute("SELECT MAX(run_at) FROM opt_runs").fetchone()
        if row and row[0]:
            cursor_ts = str(row[0])
            if 'T' not in cursor_ts:
                cursor_ts = cursor_ts.replace(' ', 'T')
        else:
            cursor_ts = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
        cursor_str = cursor_ts[:19].replace(' ', 'T') + 'Z'

        # Step 3: fetch new runs from SF
        soql = (
            f"SELECT Id,Name,CreatedDate FROM FSL__Optimization_Request__c"
            f" WHERE CreatedDate >= {cursor_str}"
            f" ORDER BY CreatedDate ASC LIMIT {_SOQL_CHUNK_SIZE}"
        )
        data = _sf_query(soql)
        sf_runs = data.get('records', [])
        counts['found'] = len(sf_runs)

        if sf_runs:
            all_ids = [r['Id'] for r in sf_runs]
            with optimizer_db.get_conn(read_only=True) as conn:
                placeholders = ','.join(['?'] * len(all_ids))
                existing_ids = {row[0] for row in conn.execute(
                    f"SELECT id FROM opt_runs WHERE id IN ({placeholders})", all_ids
                ).fetchall()}
        else:
            existing_ids = set()

        new_sf_runs = []
        for sf_run in sf_runs:
            if sf_run['Id'] in existing_ids:
                counts['skipped'] += 1
            else:
                new_sf_runs.append(sf_run)

        content_versions = _batch_get_content_versions([r['Id'] for r in new_sf_runs])

        # Step 4: process each new run
        for sf_run in new_sf_runs:
            run_id = sf_run['Id']
            run_name = sf_run.get('Name', run_id)
            run_at = sf_run['CreatedDate']

            try:
                req_cv_id, resp_cv_id = content_versions.get(run_id, (None, None))
                if not req_cv_id or not resp_cv_id:
                    raise RuntimeError("Missing content versions — files not attached to run")
                req_json = _download_json(req_cv_id)
                resp_json = _download_json(resp_cv_id)
                verdicts_n = _process_one_run(run_id, run_name, run_at, req_json, resp_json, territory_cache)
                counts['inserted'] += 1
                counts['verdicts'] += verdicts_n
                with optimizer_db.get_conn() as conn:
                    conn.execute("UPDATE opt_sync_errors SET retried=true WHERE run_id=?", [run_id])
                log.info(f"optimizer_sync: stored {run_name} — {verdicts_n} verdicts")
            except Exception as e:
                log.warning(f"optimizer_sync: failed run {run_name}: {e}")
                with optimizer_db.get_conn() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO opt_sync_errors"
                        "(run_id,run_name,error,failed_at,retried,run_at,attempts)"
                        " VALUES(?,?,?,now(),false,?,1)",
                        [run_id, run_name, str(e)[:_ERROR_TRUNCATE], run_at]
                    )
                counts['failed'] += 1

        # Step 5: purge old rows
        counts['purged'] = optimizer_db.purge_old_runs(days=days)
        status = 'success' if counts['failed'] == 0 else 'partial'

    except Exception as e:
        log.error(f"optimizer_sync: tick failed: {e}", exc_info=True)
        status = 'failed'
        error_detail = str(e)[:_ERROR_TRUNCATE]

    finally:
        finished_at = datetime.now(timezone.utc).isoformat()
        duration_ms = int((time.time() - start_ts) * 1000)
        try:
            database.write_sync_audit(
                started_at=started_at, finished_at=finished_at, status=status,
                runs_found=counts['found'], runs_inserted=counts['inserted'],
                runs_skipped=counts['skipped'], runs_failed=counts['failed'],
                verdicts_inserted=counts['verdicts'], rows_purged=counts['purged'],
                error_detail=error_detail, duration_ms=duration_ms,
            )
        except Exception:
            pass


# ── Historical backfill ───────────────────────────────────────────────────────

def backfill(days: int = 30, max_runs: int = 500) -> dict:
    """Fetch up to max_runs historical optimizer runs from the last N days.

    Queries all OptimizationRequest records in the window, skips those already
    in DuckDB, and processes up to max_runs in chronological order.
    Returns a stats dict including 'remaining' if more runs need a follow-up call.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    start_ts = time.time()
    territory_cache: dict[str, str] = {}
    counts = dict(total_sf=0, already_loaded=0, processed=0,
                  failed=0, no_files=0, remaining=0, verdicts=0)

    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
        log.info(f"backfill: querying SF for runs since {since} (days={days})")

        # Step 1: fetch all runs in window (paginated — may be 8 000+ records for 30 days)
        soql = (
            f"SELECT Id, Name, CreatedDate FROM FSL__Optimization_Request__c"
            f" WHERE CreatedDate >= {since}"
            f" ORDER BY CreatedDate ASC"
        )
        all_sf_runs = _sf_query_all(soql)
        counts['total_sf'] = len(all_sf_runs)
        log.info(f"backfill: {len(all_sf_runs)} runs in SF for window")

        if not all_sf_runs:
            counts['duration_ms'] = int((time.time() - start_ts) * 1000)
            return counts

        # Step 2: check which are already in DuckDB (chunked to avoid large IN clauses)
        all_ids = [r['Id'] for r in all_sf_runs]
        existing_ids: set[str] = set()
        for i in range(0, len(all_ids), _SOQL_CHUNK_SIZE):
            chunk = all_ids[i:i + _SOQL_CHUNK_SIZE]
            with optimizer_db.get_conn(read_only=True) as conn:
                placeholders = ','.join(['?'] * len(chunk))
                existing_ids.update(
                    row[0] for row in conn.execute(
                        f"SELECT id FROM opt_runs WHERE id IN ({placeholders})", chunk
                    ).fetchall()
                )

        new_runs = [r for r in all_sf_runs if r['Id'] not in existing_ids]
        counts['already_loaded'] = len(all_sf_runs) - len(new_runs)
        log.info(f"backfill: {len(new_runs)} new runs to process ({counts['already_loaded']} already loaded)")

        if len(new_runs) > max_runs:
            counts['remaining'] = len(new_runs) - max_runs
            new_runs = new_runs[:max_runs]

        # Step 3: process in batches of _SOQL_CHUNK_SIZE
        for i in range(0, len(new_runs), _SOQL_CHUNK_SIZE):
            batch = new_runs[i:i + _SOQL_CHUNK_SIZE]
            content_versions = _batch_get_content_versions([r['Id'] for r in batch])

            for sf_run in batch:
                run_id = sf_run['Id']
                run_name = sf_run.get('Name', run_id)
                run_at = sf_run['CreatedDate']

                try:
                    req_cv_id, resp_cv_id = content_versions.get(run_id, (None, None))
                    if not req_cv_id or not resp_cv_id:
                        log.info(f"backfill: no files for {run_name} — skipping")
                        counts['no_files'] += 1
                        continue
                    req_json = _download_json(req_cv_id)
                    resp_json = _download_json(resp_cv_id)
                    verdicts_n = _process_one_run(run_id, run_name, run_at, req_json, resp_json, territory_cache)
                    counts['processed'] += 1
                    counts['verdicts'] += verdicts_n
                    log.info(f"backfill: stored {run_name} — {verdicts_n} verdicts")
                except Exception as e:
                    log.warning(f"backfill: failed {run_name}: {e}")
                    counts['failed'] += 1

    except Exception as e:
        log.error(f"backfill: outer error: {e}", exc_info=True)
        counts['error'] = str(e)[:_ERROR_TRUNCATE]

    finished_at = datetime.now(timezone.utc).isoformat()
    counts['duration_ms'] = int((time.time() - start_ts) * 1000)
    log.info(f"backfill: done — {counts}")
    try:
        database.write_sync_audit(
            started_at=started_at,
            finished_at=finished_at,
            status='backfill' if counts.get('failed', 0) == 0 else 'backfill_partial',
            runs_found=counts['total_sf'],
            runs_inserted=counts['processed'],
            runs_skipped=counts['already_loaded'] + counts['no_files'],
            runs_failed=counts['failed'],
            verdicts_inserted=counts['verdicts'],
            rows_purged=0,
            error_detail=counts.get('error', ''),
            duration_ms=counts['duration_ms'],
        )
    except Exception:
        pass
    return counts


# ── Background thread ─────────────────────────────────────────────────────────

def _run_loop():
    while True:
        try:
            if _acquire_lock():
                try:
                    sync_tick()
                finally:
                    _release_lock()
        except Exception as e:
            log.error(f"optimizer_sync loop error: {e}", exc_info=True)
        time.sleep(_SYNC_INTERVAL)


def start():
    """Start background sync thread. Safe to call from multiple workers — lock prevents duplication."""
    optimizer_db.init_db()
    t = threading.Thread(target=_run_loop, daemon=True, name='optimizer-sync')
    t.start()
    log.info("Optimizer sync thread started")
