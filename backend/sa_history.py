"""One shared, incrementally updated copy of recent ServiceAppointment history, for the dashboards.

Why: the Command Center, Scheduler Insights and Ops Territories each looked up the same appointments' Status,
Assigned-Resource and Territory history in batches of 200 ids, every refresh: about 27 Salesforce queries per cycle,
nearly all for appointments that are already closed and can no longer change. History rows are append-only, so:

  * first use (and once an hour, to be safe): ONE query loads the last WINDOW_H hours (about 25,000 rows, ~6 s);
  * every later use: ONE small query fetches only rows created since the last sync, and they are merged in;
  * dashboards then read their rows from memory, in the same shape the old per-batch queries returned.

An appointment created before the loaded window is read straight from Salesforce, exactly as before.
If anything fails, the old direct lookup is used, so a dashboard never gets less than it did.
"""

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import sf_client

log = logging.getLogger('sa_history')

FIELDS = ('Status', 'ERS_Assigned_Resource__c', 'ServiceTerritory')
WINDOW_H = 26            # covers a rolling 24 h window plus the time between full reloads
FULL_RELOAD_S = 3600     # re-load everything once an hour (picks up anything a delta could have missed)
OVERLAP_S = 180          # each delta re-reads this much, so rows that appear late are not lost (de-duplicated by Id)
MIN_SYNC_GAP_S = 20      # screens refreshing together share one delta
_COLS = ("Id, ServiceAppointmentId, Field, NewValue, OldValue, CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name")
# No record-type filter on purpose: Ops Territories also counts Lobby and Counter appointments, and the store must
# return the same rows the old per-id lookups did for whatever appointments a dashboard passes in.
_BASE = f"SELECT {_COLS} FROM ServiceAppointmentHistory WHERE Field IN ({', '.join(repr(f) for f in FIELDS)})"

_lock = threading.RLock()
_st = {'rows': {}, 'seen': set(), 'window_start': None, 'loaded_at': 0.0, 'synced_at': 0.0}
stats = {'full_loads': 0, 'deltas': 0, 'served_from_memory': 0, 'fallback_ids': 0}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _norm(ts: str | None) -> str:
    """'2026-10-05T14:02:09.000+0000' / '...Z' -> comparable 'YYYY-MM-DDTHH:MM:SS' (UTC)."""
    return (ts or '')[:19]


def _add(rows: list, store: dict, seen: set) -> int:
    n = 0
    for r in rows:
        rid = r.get('Id')
        if rid in seen:
            continue
        seen.add(rid)
        store.setdefault(r['Field'], defaultdict(list))[r['ServiceAppointmentId']].append(
            {'ServiceAppointmentId': r['ServiceAppointmentId'], 'NewValue': r.get('NewValue'), 'OldValue': r.get('OldValue'),
             'CreatedDate': r.get('CreatedDate'), 'CreatedBy': r.get('CreatedBy'), '_id': rid})
        n += 1
    return n


def _sort(store: dict):
    for per_sa in store.values():
        for lst in per_sa.values():
            lst.sort(key=lambda r: (_norm(r['CreatedDate']), r['_id'] or ''))     # ties: the order Salesforce wrote them


def _full_load(now: float):
    ws = datetime.fromtimestamp(now, timezone.utc) - timedelta(hours=WINDOW_H)
    rows = sf_client.sf_query_all(f"{_BASE} AND ServiceAppointment.CreatedDate >= {_iso(ws)} ORDER BY CreatedDate ASC")
    store, seen = {}, set()
    _add(rows, store, seen)
    _sort(store)
    _st.update(rows=store, seen=seen, window_start=_iso(ws), loaded_at=now, synced_at=now)
    stats['full_loads'] += 1
    log.info('sa_history full load: %d rows', len(rows))


def _delta(now: float):
    since = datetime.fromtimestamp(_st['synced_at'] - OVERLAP_S, timezone.utc)
    rows = sf_client.sf_query_all(f"{_BASE} AND ServiceAppointment.CreatedDate >= {_st['window_start']} "
                                  f"AND CreatedDate >= {_iso(since)} ORDER BY CreatedDate ASC")
    if _add(rows, _st['rows'], _st['seen']):
        _sort(_st['rows'])
    _st['synced_at'] = now                # the time the query STARTED: nothing between syncs can fall through
    stats['deltas'] += 1


def _ensure_fresh():
    now = time.time()
    with _lock:
        if not _st['loaded_at'] or now - _st['loaded_at'] > FULL_RELOAD_S:
            _full_load(now)
        elif now - _st['synced_at'] >= MIN_SYNC_GAP_S:
            _delta(now)


def _direct(field: str, ids: list) -> list:
    """The original per-batch lookup, for appointments older than the loaded window and as the failure fallback."""
    out = []
    for i in range(0, len(ids), 200):
        chunk = "','".join(ids[i:i + 200])
        out += sf_client.sf_query_all(
            f"SELECT ServiceAppointmentId, NewValue, OldValue, CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name "
            f"FROM ServiceAppointmentHistory WHERE ServiceAppointmentId IN ('{chunk}') AND Field = '{field}' ORDER BY CreatedDate ASC")
    return out


def rows_for(field: str, sa_ids, created: dict) -> list:
    """History rows of `field` for these appointments, oldest first per appointment.

    `created` maps appointment id -> its CreatedDate (the caller already has it), so we know which ones the shared
    copy covers. Rows carry ServiceAppointmentId, NewValue, OldValue, CreatedDate and CreatedBy (Name, Profile.Name)."""
    ids = list(dict.fromkeys(sa_ids))
    if field not in FIELDS or not ids:
        return _direct(field, ids) if ids else []
    try:
        _ensure_fresh()
    except Exception:
        log.warning('sa_history unavailable, reading directly', exc_info=True)
        stats['fallback_ids'] += len(ids)
        return _direct(field, ids)
    with _lock:
        ws = _st['window_start']
        covered = [i for i in ids if _norm(created.get(i)) >= _norm(ws)]
        covered_set = set(covered)
        old = [i for i in ids if i not in covered_set]
        per_sa = _st['rows'].get(field, {})
        rows = [{k: v for k, v in r.items() if k != '_id'} for i in covered for r in per_sa.get(i, ())]
        stats['served_from_memory'] += len(covered)
    if old:                                # created before the loaded window: ask Salesforce, as before
        stats['fallback_ids'] += len(old)
        rows += _direct(field, old)
    return rows
