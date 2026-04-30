"""Orchestrator: discover new runs → drive UI → upload to Azure.

Idempotent: checks Azure listing before extracting. Run on a schedule (launchd/cron)
or manually with date args.

Usage:
    python -m optimizer_extractor.runner                  # today + yesterday backfill
    python -m optimizer_extractor.runner --days 7         # last 7 days
    python -m optimizer_extractor.runner --run-id a1uPb…  # one specific run
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE importing modules that need it
_ROOT = Path(__file__).resolve().parents[3]  # apidev/
load_dotenv(_ROOT / '.env')
sys.path.insert(0, str(_ROOT / 'FSLAPP' / 'backend'))

from optimizer_extractor.auth import get_session
from optimizer_extractor.discover import list_runs
from optimizer_extractor.retrieve import retrieve_batch
from optimizer_extractor.azure_uploader import already_uploaded, upload_run

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
log = logging.getLogger('runner')


def _parse_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace('Z', '+00:00'))


def run(days: int = 2, run_ids: list[str] | None = None,
        headless: bool = True, max_runs: int = 200) -> None:
    """Backfill last N days of optimizer runs into Azure Blob (idempotent)."""
    session = get_session('prod')
    log.info(f"Authenticated as {session.username} ({session.instance_url})")

    if run_ids:
        # Fetch real metadata for the requested IDs (not placeholders)
        import urllib.request, urllib.parse, json as _json
        id_list = "', '".join(run_ids)
        soql = (f"SELECT Id, Name, FSL__Status__c, FSL__Type__c, "
                f"FSL__External_Identifier__c, CreatedDate "
                f"FROM FSL__Optimization_Request__c WHERE Id IN ('{id_list}')")
        url = f"{session.instance_url}/services/data/v59.0/query?q={urllib.parse.quote(soql)}"
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {session.access_token}'})
        targets = _json.loads(urllib.request.urlopen(req).read()).get('records', [])
    else:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        targets = list_runs(session, since)
        log.info(f"Found {len(targets)} runs in last {days} day(s)")

    # Filter out runs that are already uploaded (skip work)
    to_extract = []
    skipped = 0
    by_id: dict[str, dict] = {}
    for run in targets[:max_runs]:
        rid = run['Id']
        run_at = _parse_dt(run['CreatedDate'])
        if already_uploaded(run_at, rid):
            skipped += 1
            continue
        to_extract.append(rid)
        by_id[rid] = run

    log.info(f"To extract: {len(to_extract)} runs (skipped {skipped} already in blob)")
    if not to_extract:
        log.info("=== DONE: nothing to extract ===")
        return

    # Upload each result as soon as it arrives — keeps memory low and gives progress
    counts = {'ok': 0, 'failed': 0}
    def _on_result(rid: str, result):
        if result is None:
            counts['failed'] += 1
            return
        req_bytes, resp_bytes = result
        run = by_id[rid]
        run_at = _parse_dt(run['CreatedDate'])
        try:
            ext_id = run.get('FSL__External_Identifier__c') or ''
            # Parse "<prefix>_<chunk>" → batch grouping for the UI
            batch_id, chunk_num = (None, None)
            if ext_id and '_' in ext_id:
                head, _, tail = ext_id.rpartition('_')
                if tail.isdigit():
                    batch_id, chunk_num = head, int(tail)
            upload_run(
                run_at, rid, run.get('Name', ''),
                req_bytes, resp_bytes,
                metadata_extras={
                    'fsl_status':   run.get('FSL__Status__c'),
                    'fsl_type':     run.get('FSL__Type__c'),
                    'external_id':  ext_id,
                    'batch_id':     batch_id,    # shared across the 3 chunks
                    'chunk_num':    chunk_num,    # 1, 2, or 3
                },
            )
            counts['ok'] += 1
        except Exception as e:
            log.exception(f"[{rid}] upload failed: {e}")
            counts['failed'] += 1

    # Process in chunks of CHUNK_SIZE so a single failed initial-nav doesn't kill the whole job.
    # Each chunk uses its own fresh browser session.
    CHUNK_SIZE = 50
    for chunk_idx in range(0, len(to_extract), CHUNK_SIZE):
        chunk = to_extract[chunk_idx:chunk_idx + CHUNK_SIZE]
        log.info(f"--- Chunk {chunk_idx // CHUNK_SIZE + 1}/{(len(to_extract) + CHUNK_SIZE - 1) // CHUNK_SIZE}: "
                 f"{len(chunk)} runs (overall progress: {chunk_idx}/{len(to_extract)}) ---")
        try:
            retrieve_batch(session, chunk, headless=headless, on_result=_on_result)
        except Exception as e:
            log.exception(f"Chunk failed; continuing with next chunk: {e}")
            counts['failed'] += len(chunk)
            continue
        log.info(f"Running totals: ok={counts['ok']} failed={counts['failed']}")

    log.info(f"=== DONE: ok={counts['ok']} skipped={skipped} failed={counts['failed']} of {len(targets)} ===")


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--days', type=int, default=2,
                   help='Backfill window (default: today + yesterday)')
    p.add_argument('--run-id', action='append',
                   help='Specific run ID(s) to process; repeatable')
    p.add_argument('--headed', action='store_true',
                   help='Show the browser (debugging)')
    p.add_argument('--max-runs', type=int, default=200,
                   help='Cap number of runs per invocation')
    args = p.parse_args()
    run(days=args.days, run_ids=args.run_id, headless=not args.headed, max_runs=args.max_runs)
