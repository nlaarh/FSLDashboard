"""Garage 1st / 2nd-call acceptance — completion-based, computed org-wide per period.

DEFINITION (replaces the old decline-reason logic):
  1st Call Accepted     = this garage was the FIRST garage the call was spotted to,
                          AND this garage completed the work order.
  1st Call Not Accepted = this garage was first, but a DIFFERENT garage (or none) completed it.
  2nd+ Accepted         = this garage was NOT first, but the call moved to it at some point,
                          AND this garage completed it.
  2nd+ Not Accepted     = NOT first, moved to it, but a DIFFERENT garage (or none) completed it.

WHY ONE ORG-WIDE FORWARD PASS (not per-garage):
  "First garage" and "which garages a call touched" live only in ServiceTerritory
  history, which CANNOT be filtered by garage value in SOQL (WHERE NewValue = ...
  is rejected). Computing per-garage on demand would force scanning all history for
  every one of ~300 garages and hammer the live FSL org. Instead we walk every call
  in the period ONCE, attribute it forward to each garage in its chain, and cache a
  small {territory_id: counts} map. All garages then read their slice in milliseconds.
  The heavy pass runs in the background refresher (see refresher.py), never on a user
  request. Stable past periods are computed once and frozen by the persistent cache;
  the moving current period re-runs on the refresh cadence.

KEY SF FACTS (verified against the live org):
  • Each ServiceTerritory change writes TWO history rows (one with the territory NAME,
    one with the ID). Keep only ID rows (NewValue starts with '0Hh') to dedupe.
  • The initial spotting is captured as an OldValue=null -> NewValue=<first garage>
    row, so the earliest ID-row's NewValue IS the first garage spotted.
  • The completing garage = the SA's current ServiceTerritoryId when Status='Completed'.
  • Tow Drop-Off SAs are excluded (never a member-facing dispatch).
"""

import logging
import time
from collections import defaultdict
from datetime import date, timedelta
from threading import Thread

from fastapi import APIRouter, HTTPException, Query, Request

from sf_client import sf_query_all, sanitize_soql
from routers.garages import _check_territory_access
import cache

log = logging.getLogger("garage.acceptance")

router = APIRouter()

# Persistent cache: a stable past period computes once and is frozen; the moving
# current period is refreshed by the background refresher. 26h stale window means
# a never-warmed period blocks at most one user (mitigated by refresher pre-warm).
_MAP_STALE_HOURS = 26


def _since_until(period_start: str, period_end: str) -> tuple[str, str]:
    """[period_start 00:00, period_end+1 00:00) in UTC ISO — inclusive of end day."""
    next_day = (date.fromisoformat(period_end) + timedelta(days=1)).isoformat()
    return f"{period_start}T00:00:00Z", f"{next_day}T00:00:00Z"


def _is_dropoff(work_type_name: str | None) -> bool:
    return "drop" in (work_type_name or "").lower()


# ── Org-wide data pull (runs in background; large but only ONCE per period) ──────

def _fetch_period_sas(since: str, until: str) -> list[dict]:
    """Every non-drop-off SA created in the window, org-wide.
    Current ServiceTerritoryId = the completing garage when Status='Completed'."""
    return sf_query_all(f"""
        SELECT Id, ServiceTerritoryId, Status, WorkType.Name
        FROM ServiceAppointment
        WHERE CreatedDate >= {since}
          AND CreatedDate < {until}
          AND ServiceTerritoryId != null
        ORDER BY CreatedDate ASC
    """)


def _fetch_period_territory_history(since: str, until: str) -> list[dict]:
    """ServiceTerritory change history for every SA created in the window.

    Filtered by the SA's CreatedDate (which IS filterable) — NOT by NewValue
    (which is not). Two rows per change; we keep only the ID rows downstream.
    """
    return sf_query_all(f"""
        SELECT ServiceAppointmentId, NewValue, CreatedDate
        FROM ServiceAppointmentHistory
        WHERE Field = 'ServiceTerritory'
          AND ServiceAppointment.CreatedDate >= {since}
          AND ServiceAppointment.CreatedDate < {until}
        ORDER BY ServiceAppointmentId, CreatedDate ASC
    """)


# ── The forward pass ─────────────────────────────────────────────────────────

def _build_territory_chains(history: list[dict]) -> dict[str, list[str]]:
    """{sa_id: [territory_id_first, ... , territory_id_last]} from history.

    Keep only ID rows (NewValue starts with '0Hh' — dedupes the NAME/ID double
    rows) and collapse consecutive duplicates. History is already ordered by
    (ServiceAppointmentId, CreatedDate ASC), so the first element is the first
    garage the call was spotted to.
    """
    chains: dict[str, list[str]] = defaultdict(list)
    for h in history:
        sa_id = h.get("ServiceAppointmentId")
        new_val = h.get("NewValue") or ""
        if not sa_id or not new_val.startswith("0Hh"):
            continue
        chain = chains[sa_id]
        if not chain or chain[-1] != new_val:
            chain.append(new_val)
    return chains


def _build_acceptance_map(sas: list[dict], history: list[dict]) -> dict[str, dict]:
    """Forward pass → {territory_id: {first_total, first_accepted,
    second_total, second_accepted, first_wos, second_wos}}.

    Each call is attributed to every garage in its chain: the first garage gets a
    1st-call tally, every other distinct garage gets a 2nd+ tally. 'Accepted' means
    the completing garage == that garage. *_wos hold lightweight WO refs so the
    drill-down can list calls without re-querying Salesforce.
    """
    chains = _build_territory_chains(history)

    def _blank() -> dict:
        return {
            "first_total": 0, "first_accepted": 0,
            "second_total": 0, "second_accepted": 0,
            # bucket -> list of {sa_id, status} refs (kept small for drill-down)
            "first_accepted_sa": [], "first_not_sa": [],
            "second_accepted_sa": [], "second_not_sa": [],
        }

    result: dict[str, dict] = defaultdict(_blank)

    for sa in sas:
        if _is_dropoff((sa.get("WorkType") or {}).get("Name")):
            continue
        sa_id = sa.get("Id")
        current = sa.get("ServiceTerritoryId")
        if not current:
            continue
        # Chain: history if present, else the call never moved (single garage).
        chain = chains.get(sa_id) or [current]
        first = chain[0]
        completing = current if sa.get("Status") == "Completed" else None

        # 1st-call bucket for the FIRST garage
        bucket = result[first]
        bucket["first_total"] += 1
        ref = {"sa_id": sa_id, "status": sa.get("Status")}
        if completing == first:
            bucket["first_accepted"] += 1
            bucket["first_accepted_sa"].append(ref)
        else:
            bucket["first_not_sa"].append(ref)

        # 2nd+ bucket for every OTHER distinct garage the call moved to
        for terr in dict.fromkeys(chain[1:]):  # distinct, preserve order, skip first
            if terr == first:
                continue
            b2 = result[terr]
            b2["second_total"] += 1
            if completing == terr:
                b2["second_accepted"] += 1
                b2["second_accepted_sa"].append(ref)
            else:
                b2["second_not_sa"].append(ref)

    return dict(result)


def _compute_acceptance_map(period_start: str, period_end: str) -> dict:
    """Org-wide pass for the period. Returns {'map': {...}, 'period': ...}.
    Heavy — intended to run in the background refresher, then be served from cache."""
    since, until = _since_until(period_start, period_end)
    sas = _fetch_period_sas(since, until)
    history = _fetch_period_territory_history(since, until)
    amap = _build_acceptance_map(sas, history)
    log.info(
        f"acceptance map {period_start}..{period_end}: "
        f"{len(sas)} SAs, {len(history)} history rows, {len(amap)} garages"
    )
    return {"map": amap, "period_start": period_start, "period_end": period_end,
            "sa_count": len(sas)}


def acceptance_map_cache_key(period_start: str, period_end: str) -> str:
    return f"accept_map_{period_start}_{period_end}"


_MAP_TTL_SEC = _MAP_STALE_HOURS * 3600


def _map_status_and_data(period_start: str, period_end: str) -> tuple[str, dict | None]:
    """Lazy, single-flight map fetch — never blocks the request.

    Returns ('ready', map) when the org-wide map is cached. Otherwise kicks off ONE
    background computation (guarded by a filesystem lock so 300 simultaneous first
    visitors trigger only a single Salesforce pull) and returns ('computing', None).
    The caller shows a "this may take ~1 minute" message and polls until ready; every
    visitor after the compute finishes is served instantly from cache.
    """
    key = acceptance_map_cache_key(period_start, period_end)
    cached = cache.get_from_any_layer(key, ttl=_MAP_TTL_SEC)
    if cached is not None:
        return "ready", cached

    lock_name = f"acceptmap_{period_start}_{period_end}".replace("-", "")
    if cache.fs_lock_acquire(lock_name, max_age=300):
        def _bg():
            try:
                result = _compute_acceptance_map(period_start, period_end)
                result["cached_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                cache.put(key, result, _MAP_TTL_SEC)
                cache.disk_put(key, result, _MAP_TTL_SEC)
            except Exception as e:  # noqa: BLE001
                log.error(f"acceptance map compute failed for {period_start}..{period_end}: {e}")
            finally:
                cache.fs_lock_release(lock_name)
        Thread(target=_bg, daemon=True).start()
    return "computing", None


def _computing_message(span_days: int) -> tuple[str, int]:
    """Wait message + estimated seconds, scaled to the window size.
    A ~1-month pull is ~1 min; a ~3-month pull is ~2-3 min."""
    if span_days <= 31:
        return (
            "Building 1st/2nd-call acceptance across all garages for this period. "
            "This is a one-time calculation that can take up to about a minute — "
            "it will be instant every time after this.",
            60,
        )
    return (
        "Building 1st/2nd-call acceptance across all garages for this period. "
        "Larger date ranges take longer — this one-time calculation can take up to "
        "a few minutes. It will be instant every time after this.",
        180,
    )


# Max window: 92 days covers any full calendar quarter; blocks 4+ month spans.
_MAX_SPAN_DAYS = 92


def slice_for_territory(amap: dict, territory_id: str) -> dict:
    """Pull one garage's acceptance numbers (with percentages) out of the org map."""
    b = (amap.get("map") or {}).get(territory_id) or {
        "first_total": 0, "first_accepted": 0, "second_total": 0, "second_accepted": 0,
    }
    ft, fa = b["first_total"], b["first_accepted"]
    st, sa = b["second_total"], b["second_accepted"]
    return {
        "first_call_total": ft,
        "first_call_accepted": fa,
        "first_call_pct": round(100 * fa / ft, 1) if ft else None,
        "second_call_total": st,
        "second_call_accepted": sa,
        "second_call_pct": round(100 * sa / st, 1) if st else None,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/api/garages/{territory_id}/acceptance")
def get_acceptance(
    request: Request,
    territory_id: str,
    period_start: str = Query(...),
    period_end: str = Query(...),
):
    """Completion-based 1st / 2nd-call acceptance for one garage.
    Reads a cached org-wide map and slices this garage — milliseconds when warm."""
    _check_territory_access(request, territory_id)
    territory_id = sanitize_soql(territory_id)
    period_start = sanitize_soql(period_start)
    period_end = sanitize_soql(period_end)

    # Enforce a one-month (≤ 30-day) window. Keeps the org-wide pull bounded to a
    # single month and prevents multi-month spans that would slow the compute.
    try:
        span_days = (date.fromisoformat(period_end) - date.fromisoformat(period_start)).days
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (expected YYYY-MM-DD)")
    if span_days < 0:
        raise HTTPException(status_code=400, detail="End date must be on or after start date")
    if span_days > _MAX_SPAN_DAYS:
        raise HTTPException(
            status_code=400,
            detail="Acceptance can be viewed for up to 3 months at a time. "
                   "Pick a start and end date within about 92 days of each other.",
        )

    status, amap = _map_status_and_data(period_start, period_end)
    if status == "computing":
        # First load for this period — tell the user what to expect; they poll until ready.
        msg, est = _computing_message(span_days)
        return {"status": "computing", "message": msg, "estimated_seconds": est}
    out = slice_for_territory(amap, territory_id)
    out["status"] = "ready"
    out["definitions"] = {
        "first_call": (
            "1st Call Acceptance — calls where THIS garage was the first garage the "
            "work order was spotted to. Accepted = this garage completed the work order. "
            "Not Accepted = a different garage (or none) completed it."
        ),
        "second_call": (
            "2nd+ Call Acceptance — calls where this garage was NOT first but the work "
            "order was moved to it at some point. Accepted = this garage completed it. "
            "Not Accepted = a different garage (or none) completed it."
        ),
        "source": (
            "First garage = earliest ServiceTerritory in SA history; completing garage = "
            "the garage on the SA when it reached Completed. Tow Drop-Off excluded."
        ),
    }
    out["cached_at"] = amap.get("cached_at")
    return out


# ── Drill-down: list the actual work orders in a bucket ─────────────────────────

# Modal bucket key -> the per-territory SA-ref list stored in the map.
_BUCKET_FIELD = {
    "first_accepted": "first_accepted_sa",
    "first_not": "first_not_sa",
    "second_accepted": "second_accepted_sa",
    "second_not": "second_not_sa",
}


def _resolve_sa_wos(sa_ids: list[str]) -> list[dict]:
    """Resolve SA ids -> {sa_id, wo_id, wo_number, work_type, status} for the modal.
    Small, targeted query (only one garage's bucket), batched at 200 ids."""
    rows: list[dict] = []
    for i in range(0, len(sa_ids), 200):
        batch = sa_ids[i: i + 200]
        id_csv = "','".join(sanitize_soql(x) for x in batch)
        recs = sf_query_all(f"""
            SELECT Id, Status, WorkType.Name,
                   TYPEOF ParentRecord
                     WHEN WorkOrderLineItem THEN WorkOrderId, WorkOrder.WorkOrderNumber
                     WHEN WorkOrder THEN Id, WorkOrderNumber
                   END
            FROM ServiceAppointment
            WHERE Id IN ('{id_csv}')
        """)
        for sa in recs:
            pr = sa.get("ParentRecord") or {}
            wo_id = pr.get("WorkOrderId") or pr.get("Id")
            wo = pr.get("WorkOrder") or {}
            wo_number = (wo.get("WorkOrderNumber") if isinstance(wo, dict) else None) or pr.get("WorkOrderNumber")
            rows.append({
                "sa_id": sa.get("Id"),
                "wo_id": wo_id,
                "wo_number": wo_number,
                "work_type": (sa.get("WorkType") or {}).get("Name"),
                "status": sa.get("Status"),
            })
    return rows


@router.get("/api/garages/{territory_id}/acceptance-detail")
def get_acceptance_detail(
    request: Request,
    territory_id: str,
    bucket: str = Query(...),
    period_start: str = Query(...),
    period_end: str = Query(...),
):
    """List the work orders behind one acceptance bucket for a garage.
    Reads the cached org-wide map (already warm — the cards loaded first), slices
    this garage's bucket, and resolves the SA ids to WO numbers."""
    _check_territory_access(request, territory_id)
    territory_id = sanitize_soql(territory_id)
    field = _BUCKET_FIELD.get(bucket)
    if not field:
        raise HTTPException(status_code=400, detail=f"Unknown bucket '{bucket}'")
    status, amap = _map_status_and_data(sanitize_soql(period_start), sanitize_soql(period_end))
    if status == "computing":
        return {"bucket": bucket, "count": 0, "rows": [], "status": "computing"}
    terr = (amap.get("map") or {}).get(territory_id) or {}
    sa_ids = [r["sa_id"] for r in (terr.get(field) or []) if r.get("sa_id")]
    rows = _resolve_sa_wos(sa_ids)
    return {"bucket": bucket, "count": len(rows), "rows": rows}
