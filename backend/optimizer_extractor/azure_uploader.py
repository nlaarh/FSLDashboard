"""Azure Blob upload — idempotent, content-addressable layout.

Layout: optimizer-files/{YYYY-MM-DD}/{run_id}/{request,response,metadata}.json
"""

import os
import json
import logging
from datetime import datetime
from azure.storage.blob import BlobServiceClient, ContentSettings

log = logging.getLogger('optimizer_extractor.azure')

_CONN = os.environ.get('AZ_OPT_CONNECTION_STRING')
_CONTAINER = os.environ.get('AZ_OPT_CONTAINER', 'optimizer-files')


def _client() -> BlobServiceClient:
    if not _CONN:
        raise RuntimeError("AZ_OPT_CONNECTION_STRING not set in environment / .env")
    return BlobServiceClient.from_connection_string(_CONN)


def _blob_path(run_at: datetime, run_id: str, filename: str) -> str:
    return f"{run_at.strftime('%Y-%m-%d')}/{run_id}/{filename}"


def already_uploaded(run_at: datetime, run_id: str) -> bool:
    """True iff both request.json and response.json already exist for this run."""
    bs = _client().get_container_client(_CONTAINER)
    prefix = f"{run_at.strftime('%Y-%m-%d')}/{run_id}/"
    names = {b.name for b in bs.list_blobs(name_starts_with=prefix)}
    return any(n.endswith('request.json') for n in names) and any(n.endswith('response.json') for n in names)


def upload_run(run_at: datetime, run_id: str, run_name: str,
               request_json: bytes, response_json: bytes,
               metadata_extras: dict | None = None) -> None:
    """Upload request + response + metadata blobs for one run. Overwrites if exists."""
    container = _client().get_container_client(_CONTAINER)
    paths = {
        'request.json':  request_json,
        'response.json': response_json,
        'metadata.json': json.dumps({
            'run_id':   run_id,
            'run_name': run_name,
            'run_at':   run_at.isoformat(),
            'uploaded_at': datetime.utcnow().isoformat() + 'Z',
            **(metadata_extras or {}),
        }, indent=2).encode('utf-8'),
    }
    for name, body in paths.items():
        path = _blob_path(run_at, run_id, name)
        container.upload_blob(
            name=path, data=body, overwrite=True,
            content_settings=ContentSettings(content_type='application/json'),
        )
    log.info(f"[{run_id}] uploaded {len(paths)} blobs to {_CONTAINER}/{run_at.strftime('%Y-%m-%d')}/{run_id}/")


def list_uploaded_runs(date_prefix: str | None = None) -> list[str]:
    """Return run_ids that have been uploaded under {date_prefix}/. If no date, all."""
    container = _client().get_container_client(_CONTAINER)
    prefix = f"{date_prefix}/" if date_prefix else ""
    seen: set[str] = set()
    for b in container.list_blobs(name_starts_with=prefix):
        # name: "2026-04-29/a1uPb000.../request.json"
        parts = b.name.split('/')
        if len(parts) >= 2:
            seen.add(parts[-2])
    return sorted(seen)
