"""Scheduler Report Card: INTERIM snapshot storage (slice 1) as JSON files.

architecture.md section 13 stores snapshots in ops.src_snapshot, but that migration is admin-applied
(Kathy, with the user's approval) and has not run yet. Until then, snapshots go to JSON files:
  Azure:  /home/fslapp/report_card/      (persistent App Service storage, shared by workers)
  local:  ~/.fslapp/report_card/          (outside the repo, so nothing can be committed)
  override: REPORT_CARD_STORE_DIR
The Postgres L2 cache was not used: locally it is the PRODUCTION database (gold rule: no test data
in production stores). Append-only: a rebuild first renames the current file to
<name>.snapshot.<epoch>.json, so every earlier version is kept. Nothing is ever deleted.
"""

import json
import os
import threading
import re
import time
from pathlib import Path

_ON_AZURE = bool(os.environ.get('WEBSITE_SITE_NAME'))
_DEFAULT = Path('/home/fslapp/report_card') if _ON_AZURE else Path(os.path.expanduser('~/.fslapp/report_card'))
STALE_BUILD_S = 15 * 60
_SAFE = re.compile(r'^[A-Za-z0-9]{15,18}$')
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _dir() -> Path:
    d = Path(os.environ.get('REPORT_CARD_STORE_DIR') or _DEFAULT)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(territory_id: str, service_date: str, suffix: str) -> Path:
    if not _SAFE.match(territory_id) or not _DATE.match(service_date):
        raise ValueError('bad territory id or date')
    return _dir() / f'{territory_id}_{service_date}.{suffix}.json'


def _write(path: Path, data: dict):
    tmp = path.with_suffix(f'.tmp{os.getpid()}.{threading.get_ident()}')   # per thread: two requests can save the same file at once
    tmp.write_text(json.dumps(data, separators=(',', ':'), default=str))
    os.replace(tmp, path)


def load_snapshot(territory_id: str, service_date: str) -> dict | None:
    p = _path(territory_id, service_date, 'snapshot')
    return json.loads(p.read_text()) if p.exists() else None


def save_snapshot(territory_id: str, service_date: str, snapshot: dict) -> int:
    p = _path(territory_id, service_date, 'snapshot')
    if p.exists():
        os.replace(p, _path(territory_id, service_date, f'snapshot.{int(p.stat().st_mtime)}'))
    _write(p, snapshot)
    return p.stat().st_size


def get_status(territory_id: str, service_date: str) -> dict | None:
    """Build status shared across workers. A 'building' row older than 15 min is reported failed."""
    p = _path(territory_id, service_date, 'status')
    if not p.exists():
        return None
    s = json.loads(p.read_text())
    if s.get('status') == 'building' and time.time() - s.get('started_ts', 0) > STALE_BUILD_S:
        s = {**s, 'status': 'failed', 'error': 'stale build reclaimed'}
    return s


def set_status(territory_id: str, service_date: str, **fields):
    _write(_path(territory_id, service_date, 'status'), fields)


def load_ai(key: str) -> dict | None:
    """AI day findings cached by fact-sheet hash (architecture 11.1), interim file store."""
    p = _ai_path(key)
    return json.loads(p.read_text()) if p.exists() else None


def save_ai(key: str, data: dict):
    _write(_ai_path(key), data)


def _ai_path(key: str) -> Path:
    if not re.match(r'^[A-Za-z0-9._-]{20,200}$', key):
        raise ValueError('bad AI cache key')
    d = _dir() / 'ai'
    d.mkdir(exist_ok=True)
    return d / f'{key}.json'


# ── Call Story (call-story-architecture 2, 3.4, 5): segment files, raw story bundles ──

def list_days() -> list:
    """[(territory_id, service_date)] of every current snapshot in the store."""
    out = []
    for p in _dir().glob('*_*.snapshot.json'):
        tid, _, rest = p.name.partition('_')
        day = rest.split('.')[0]
        if _SAFE.match(tid) and _DATE.match(day):
            out.append((tid, day))
    return sorted(out)


def load_segments(territory_id: str, service_date: str) -> dict | None:
    """Segment rows of a day, or None when missing or older than the snapshot they came from."""
    p, snap = _path(territory_id, service_date, 'segments.cs1'), _path(territory_id, service_date, 'snapshot')
    if not p.exists() or (snap.exists() and snap.stat().st_mtime > p.stat().st_mtime):
        return None
    return json.loads(p.read_text())


def save_segments(territory_id: str, service_date: str, data: dict):
    _write(_path(territory_id, service_date, 'segments.cs1'), data)


def load_story_raw(wo_id: str) -> dict | None:
    p = _story_path(wo_id)
    return json.loads(p.read_text()) if p.exists() else None


def save_story_raw(wo_id: str, raw: dict):
    p = _story_path(wo_id)
    if p.exists():
        os.replace(p, p.with_name(f'{p.stem}.{int(p.stat().st_mtime)}.json'))
    _write(p, raw)


def story_raw_age_s(wo_id: str) -> float | None:
    p = _story_path(wo_id)
    return time.time() - p.stat().st_mtime if p.exists() else None


def _story_path(wo_id: str) -> Path:
    if not _SAFE.match(wo_id or ''):
        raise ValueError('bad work order id')
    d = _dir() / 'stories'
    d.mkdir(exist_ok=True)
    return d / f'{wo_id}.raw.cs1.json'
