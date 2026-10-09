"""Dispatch Watchlist — SAs requiring dispatcher attention.

Auto-includes SAs that were manually reassigned by a human dispatcher,
had driver rejections, or experienced dispatch thrash (3+ driver assignments).
Auto-drops SAs completed/canceled for more than 5 minutes.
Only shows SAs from the last 24 hours.

Pure helper functions live in watchlist_helpers.py (keeps this file under 600 lines).
The Salesforce read lives in watchlist_snapshot.py; this file turns that snapshot into alerts and decides when to
re-read it: nobody waits for Salesforce once a copy exists (see "Serving" below).
"""

import logging
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request

import cache
import users as _users
from utils import parse_dt as _parse_dt
from routers.watchlist_alerts import (
    build_operational_alerts, build_no_sa_wo_alerts, _rap_customer,
    enrich_alerts_with_kmi, sort_alerts,
)
from routers.watchlist_snapshot import fetch_snapshot
from routers.auth import get_request_username
from routers.watchlist_helpers import (
    _TERMINAL_STATUSES, _RESOLVED_STATUSES,
    _evaluate_criteria, _build_entry, _build_phases,
    _time_in_status, _compute_flag, _sort_key,
)

router = APIRouter()
log = logging.getLogger('watchlist')

CACHE_KEY = 'dispatch_watchlist'
FRESH_S = 30          # a copy this young is served as is (the screen polls every 30 s)
MAX_STALE_S = 60      # a copy up to this old is served instantly while ONE background rebuild refreshes it;
                      # older than this, the request waits for a rebuild (and falls back to the old copy only if it fails)
_LOCK_NAME = 'watchlist_rebuild'

# Serving: one copy per process. 'snap' = the raw Salesforce snapshot, 'result' = alerts for everybody built from it.
_state: dict = {'snap': None, 'result': None, 'built': 0.0}
_rebuild_lock = threading.Lock()      # one rebuild at a time in this process; waiters reuse its result


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.get("/api/watchlist")
def api_watchlist(request: Request):
    """SAs that dispatchers should be closely following.

    Auto-follow: manual reassignment, driver rejection, or dispatch thrash.
    Auto-drop: completed/canceled > 5 minutes ago.
    Contractors: scoped to their assigned territories only.
    """
    # Determine contractor territory scope
    username = get_request_username(request)
    user = _users.get_user(username) if username else None
    territories: list[str] = (user.get("territories") or []) if user and user.get("role") == "contractor" else []
    return watchlist_for(territories)


# ── Serving: last copy instantly, one background rebuild ─────────────────────

def _age_of(last_updated) -> float:
    """Seconds since an ISO 'last_updated' stamp (infinite when missing)."""
    ts = _parse_dt(last_updated)
    if not ts:
        return float('inf')
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _rebuild(block: bool) -> bool:
    """Read Salesforce once and replace the copy. Only one rebuild runs at a time (block=False: skip if one is running
    or another worker holds the rebuild lock; block=True: wait for the running one, then reuse its result)."""
    if not _rebuild_lock.acquire(blocking=block):
        return False
    try:
        if block and _age_of(_state['result'] and _state['result'].get('last_updated')) <= FRESH_S:
            return True                                  # the rebuild we waited for already refreshed it
        if not block and not cache.fs_lock_acquire(_LOCK_NAME, max_age=90):
            return False                                 # another worker is rebuilding
        try:
            snap = fetch_snapshot()
            result = assemble(snap, None)
        finally:
            if not block:
                cache.fs_lock_release(_LOCK_NAME)
        _state.update(snap=snap, result=result, built=time.time())
        cache.put(CACHE_KEY, result, MAX_STALE_S)
        cache.disk_put(CACHE_KEY, result, MAX_STALE_S)
        return True
    except Exception as e:
        log.error(f"Watchlist build failed: {e}", exc_info=True)
        return False
    finally:
        _rebuild_lock.release()


def _rebuild_in_background() -> None:
    def run():
        cache.set_system_thread(True)                    # a background rebuild is not a user read
        _rebuild(block=False)
    threading.Thread(target=run, daemon=True, name='watchlist-rebuild').start()


def warm() -> None:
    """Fill the copy once after a restart (called by the refresher)."""
    if not _rebuild(block=True):
        raise RuntimeError('watchlist warm-up failed')


def watchlist_for(territories: list[str] | None = None) -> dict:
    """The watchlist for everybody (territories empty) or for a contractor's territories.

    Copy younger than FRESH_S: served. Up to MAX_STALE_S old: served at once and one background rebuild starts.
    Older or missing: wait for a rebuild; if it fails, serve the last copy (or an error body). 'last_updated' always
    says when Salesforce was read, so "updated Ns ago" on screen is true."""
    snap = _state['snap']
    result = _state['result']
    age = time.time() - _state['built'] if snap else float('inf')
    if not territories and age > FRESH_S:
        disk = cache.disk_get_stale(CACHE_KEY)           # a copy another worker/process wrote may be newer
        disk_age = _age_of(disk.get('last_updated')) if disk else float('inf')
        if disk_age < age:
            result, snap, age = disk, None, disk_age

    if age > MAX_STALE_S or (territories and snap is None):
        if not _rebuild(block=True):
            return _fallback(territories, snap, result)
        snap, result = _state['snap'], _state['result']
    elif age > FRESH_S:
        _rebuild_in_background()
    return assemble(snap, territories) if territories else result


def shared_state() -> tuple[dict, dict]:
    """(snapshot, alerts built from it) for everybody, kept fresh by the same rules as the screen (Garage Live reads from here, so its
    flags and wording are the Watchlist's own and it never adds a Salesforce read). Raises RuntimeError when no copy can be made."""
    watchlist_for(None)
    if _state['snap'] is None:
        _rebuild(block=True)
    if _state['snap'] is None:
        raise RuntimeError('watchlist snapshot unavailable')
    return _state['snap'], _state['result']


def _fallback(territories, snap, result) -> dict:
    """The rebuild failed: serve the last copy we have (its last_updated tells the truth about its age)."""
    if territories:
        if snap is not None:
            return assemble(snap, territories)
    else:
        stale = result or cache.get_stale(CACHE_KEY) or cache.disk_get_stale(CACHE_KEY)
        if stale:
            return stale
    return {'watchlist': [], 'total': 0, 'last_updated': None, 'error': 'Salesforce read failed'}


# ── Build watchlist ──────────────────────────────────────────────────────────

def _wo_info(entry: dict | None) -> dict:
    if not entry:
        return {}
    wo = entry.get('wo') or {}
    return {
        'wo_number': wo.get('WorkOrderNumber', ''),
        'wo_id': entry.get('wo_id', ''),
        'current_wait': wo.get('Current_Wait__c'),
        'vehicle_make': wo.get('Vehicle_Make__c', ''),
        'vehicle_model': wo.get('Vehicle_Model__c', ''),
        'vehicle_plate': wo.get('License_Plate__c', ''),
    }


def assemble(snap: dict, territories: list[str] | None = None) -> dict:
    """Alerts and watchlist entries from a snapshot. Pure Python, no Salesforce, so it also serves each contractor's
    territories from the shared snapshot. Duplicate checks always look at every territory (as they always did)."""
    now_utc = snap['now']
    scope = set(territories) if territories else None
    sas = [s for s in snap['sas'] if scope is None or s.get('ServiceTerritoryId') in scope]
    ar_by_sa, hist_by_sa, wo_by_woli = snap['ar_by_sa'], snap['hist_by_sa'], snap['wo_by_woli']

    def _kmi(alerts):
        known = snap.get('kmi_map')
        snap['kmi_map'] = enrich_alerts_with_kmi(alerts, known)

    # WO-level flag: Submitted WOs with no SA can't be found from the SA list below
    no_sa_alerts = build_no_sa_wo_alerts(snap['no_sa_wos'], now_utc, territories)

    if not sas:
        if no_sa_alerts:
            _kmi(no_sa_alerts)
        return {'watchlist': [], 'total': 0, 'operational_alerts': no_sa_alerts,
                'last_updated': now_utc.isoformat()}

    sa_map = {s['Id']: s for s in sas}

    # ── Evaluate each SA against watchlist criteria ──
    entries = []
    for sa_id, sa in sa_map.items():
        # Auto-drop: terminal status AND ActualEndTime > 5 min ago
        status = sa.get('Status', '')
        if status in _TERMINAL_STATUSES:
            end_dt = _parse_dt(sa.get('ActualEndTime'))
            if end_dt:
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                if (now_utc - end_dt).total_seconds() > 300:
                    continue
            else:
                # No ActualEndTime but terminal — use LastModifiedDate as fallback
                mod_dt = _parse_dt(sa.get('LastModifiedDate'))
                if mod_dt:
                    if mod_dt.tzinfo is None:
                        mod_dt = mod_dt.replace(tzinfo=timezone.utc)
                    if (now_utc - mod_dt).total_seconds() > 300:
                        continue

        ar_list = ar_by_sa.get(sa_id, [])
        hist_list = hist_by_sa.get(sa_id, [])

        reasons, flags = _evaluate_criteria(ar_list, hist_list)

        if not reasons:
            continue

        # Auto-drop: En Route/On-Scene — concern resolved unless driver is aging
        if status in _RESOLVED_STATUSES:
            tis = _time_in_status(hist_list, status, now_utc)
            if _compute_flag(status, tis) != 'aging':
                continue

        entry = _build_entry(sa, ar_list, hist_list, reasons, flags, now_utc, sa_map)
        entries.append(entry)

    # ── Sort: active flagged first, then by reassignment count, completed last ──
    entries.sort(key=_sort_key)

    # ── Operational Alerts (new flag-based table) ──
    rap_by_woli = {woli: _rap_customer(v.get('wo')) for woli, v in wo_by_woli.items()}
    operational_alerts = build_operational_alerts(sas, sa_map, hist_by_sa, now_utc,
                                                  snap['dup_candidates'], rap_by_woli)

    # ── Enrich alerts with WO data + phases for timeline hover ──
    for alert in operational_alerts:
        sa = sa_map.get(alert['sa_id'], {})
        wo_info = _wo_info(wo_by_woli.get(sa.get('ParentRecordId', '')))
        alert['wo_number'] = wo_info.get('wo_number', '')
        alert['wo_id'] = wo_info.get('wo_id', '')
        alert['current_wait'] = wo_info.get('current_wait')
        # Vehicle from WO
        v_parts = [p for p in [wo_info.get('vehicle_make', ''), wo_info.get('vehicle_model', '')] if p]
        alert['vehicle'] = ' '.join(v_parts)
        alert['vehicle_plate'] = wo_info.get('vehicle_plate', '')
        # Add phases for SAWithTimeline hover
        hist_list = hist_by_sa.get(alert['sa_id'], [])
        alert['phases'] = _build_phases(hist_list, alert['status'], now_utc)
        alert['work_type'] = (sa.get('WorkType') or {}).get('Name', '')
        alert['work_type_id'] = sa.get('WorkTypeId') or ''

    operational_alerts.extend(no_sa_alerts)
    if operational_alerts:
        _kmi(operational_alerts)
        sort_alerts(operational_alerts)

    return {
        'watchlist': entries,
        'total': len(entries),
        'operational_alerts': operational_alerts,
        'last_updated': now_utc.isoformat(),
    }
