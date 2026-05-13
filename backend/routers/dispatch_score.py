"""Dispatcher Performance Scorecard — monthly-cached, AI-powered coaching insights.

Scores active ERS dispatchers on outcome quality, response speed, consistency,
volume, rescue ratio, and daily engagement over a rolling 90-day window.
Cache key rotates monthly so each month gets its own snapshot.
Managers can force-refresh at any time.
"""

import logging
import statistics
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

import cache
import db_adapter
import users
from sf_client import sf_query_all
from utils import parse_dt as _parse_dt
from routers import dispatcher_registry
from routers.dispatch_insight import generate_insight as _generate_insight, insight_cache_key as _insight_cache_key, _enforce_tip_rules

router = APIRouter()
log = logging.getLogger('dispatch_score')

_COMPUTING_KEY = "dispatch_score_computing"
_PARTIAL_KEY   = "dispatch_score_partial"
_compute_lock  = threading.Lock()

_DISPATCH_SCORE_ROLES = {"superadmin", "admin", "executive"}

# Call type complexity weights — heavier calls should not inflate UTC rates unfairly
_COMPLEXITY = {
    "tow drop-off": 0.8,
    "battery":      1.0,
    "lockout":      1.0,
    "tire":         1.1,
    "tow pick-up":  1.2,
    "locksmith":    1.3,
    "winch out":    2.0,
}

# Stale SA guard: Alger/Gancasz get overnight backlog — cap before scoring
_RESPONSE_CAP_MIN = 120


# ── Role guard ────────────────────────────────────────────────────────────────

def _require_dispatch_score_role(request: Request) -> str:
    from routers.auth import _verify_cookie
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    parts = payload.split(":")
    username = parts[0] if parts else ""
    cookie_role = parts[1] if len(parts) > 1 else ""
    role = (users.get_user(username) or {}).get("role") or cookie_role
    if role not in _DISPATCH_SCORE_ROLES:
        raise HTTPException(status_code=403, detail="Dispatch scorecard restricted to managers")
    return username


# ── Scoring functions ─────────────────────────────────────────────────────────

def _score_outcome(adj_comp_pct: float) -> int:
    """0–40 pts based on complexity-adjusted completion rate."""
    if adj_comp_pct >= 93: return 40
    if adj_comp_pct >= 90: return 35
    if adj_comp_pct >= 85: return 30
    if adj_comp_pct >= 80: return 23
    if adj_comp_pct >= 75: return 15
    return 7


def _score_speed(median_min: float) -> int:
    """0–25 pts based on median response time (AR created – SA created)."""
    if median_min <= 5:  return 25
    if median_min <= 10: return 22
    if median_min <= 15: return 18
    if median_min <= 20: return 14
    if median_min <= 30: return 10
    if median_min <= 45: return 5
    return 2


def _score_consistency(slow_pct: float) -> int:
    """0–20 pts based on % of dispatches where response took > 30 min."""
    if slow_pct < 15: return 20
    if slow_pct < 20: return 17
    if slow_pct < 30: return 13
    if slow_pct < 40: return 8
    if slow_pct < 55: return 4
    return 1


def _score_volume(count: int) -> int:
    """0–15 pts based on total dispatches in the 90-day window."""
    if count >= 400: return 15
    if count >= 250: return 13
    if count >= 150: return 10
    if count >= 75:  return 7
    if count >= 25:  return 4
    return 0


def _tier(score: int) -> str:
    if score >= 85: return "Elite"
    if score >= 70: return "Proficient"
    if score >= 50: return "Developing"
    return "Needs Support"


def _complexity_weight(work_type: str | None) -> float:
    if not work_type:
        return 1.0
    return _COMPLEXITY.get(work_type.lower().strip(), 1.0)


# ── Cache keys ────────────────────────────────────────────────────────────────

def _cache_key() -> str:
    now = datetime.now(timezone.utc)
    return f"dispatch_score_v3_{now.year}_{now.month:02d}"


# ── Arrival stall helper ──────────────────────────────────────────────────────

def _fetch_arrival_stalls(sa_ids: list) -> dict:
    """Return {sa_id: datetime} of first On Location status event per SA."""
    if not sa_ids:
        return {}
    on_loc: dict = {}
    for i in range(0, len(sa_ids), 200):
        chunk = sa_ids[i:i + 200]
        ids_str = ", ".join("'" + sid + "'" for sid in chunk)
        soql = (
            "SELECT ServiceAppointmentId, CreatedDate, NewValue "
            "FROM ServiceAppointmentHistory "
            "WHERE ServiceAppointmentId IN (" + ids_str + ") "
            "AND Field = 'Status' "
            "ORDER BY ServiceAppointmentId, CreatedDate ASC"
        )
        for h in sf_query_all(soql):
            if (h.get("NewValue") or "").strip().lower() != "on location":
                continue
            sid = h["ServiceAppointmentId"]
            if sid not in on_loc:
                dt = _parse_dt(h.get("CreatedDate"))
                if dt:
                    on_loc[sid] = dt
    return on_loc


# ── Core computation ──────────────────────────────────────────────────────────

_BATCH_SIZE = 5  # dispatchers per SF query — smaller batches appear sooner in the UI

_AR_SOQL = (
    "SELECT Id, CreatedDate, CreatedById, ServiceAppointmentId, "
    "ServiceAppointment.Status, ServiceAppointment.CreatedDate, "
    "ServiceAppointment.DueDate, ServiceAppointment.EarliestStartTime, "
    "ServiceAppointment.WorkType.Name, ServiceAppointment.RecordType.Name "
    "FROM AssignedResource "
    "WHERE CreatedDate = LAST_N_DAYS:90 "
    "AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment' "
    "AND CreatedById IN ({id_list}) "
    "ORDER BY ServiceAppointmentId, CreatedDate ASC"
)


def _init_acc() -> dict:
    return {
        "total": 0, "completed": 0,
        "weighted_complete": 0.0, "weighted_total": 0.0,
        "response_times": [], "call_types": {},
        "stall_mins": [], "rescue_count": 0, "active_days": set(),
        "pta_met": 0, "pta_eligible": 0,
    }


def _accumulate_rows(rows: list, acc: dict, sa_first: dict,
                     sa_first_dispatcher: dict, sf_to_email: dict,
                     sa_due_dates: dict):
    """Fold AR rows into per-dispatcher accumulators. Mutates acc, sa_first, sa_first_dispatcher."""
    for row in rows:
        email = sf_to_email.get(row.get("CreatedById"))
        if not email or email not in acc:
            continue
        sa_id     = row.get("ServiceAppointmentId")
        sa        = row.get("ServiceAppointment") or {}
        status    = sa.get("Status") or ""
        work_type = (sa.get("WorkType") or {}).get("Name") or ""

        is_rescue = sa_id in sa_first_dispatcher and sa_first_dispatcher[sa_id] != email
        if sa_id not in sa_first_dispatcher:
            sa_first_dispatcher[sa_id] = email

        a = acc[email]
        a["total"] += 1
        if is_rescue:
            a["rescue_count"] += 1
        a["call_types"][work_type or "Unknown"] = a["call_types"].get(work_type or "Unknown", 0) + 1

        weight = _complexity_weight(work_type)
        a["weighted_total"] += weight
        if status == "Completed":
            a["completed"] += 1
            a["weighted_complete"] += weight

        ar_created = row.get("CreatedDate")
        sa_created = sa.get("CreatedDate")
        if ar_created and sa_created:
            try:
                ar_dt = _parse_dt(ar_created)
                sa_dt = _parse_dt(sa_created)
                if ar_dt and sa_dt:
                    rt = (ar_dt - sa_dt).total_seconds() / 60
                    if rt > 0:
                        a["response_times"].append(min(rt, _RESPONSE_CAP_MIN))
                    if sa_id and sa_id not in sa_first:
                        sa_first[sa_id] = {"email": email, "dispatch_dt": ar_dt}
                        due_iso = sa.get("DueDate")
                        if due_iso:
                            sa_due_dates[sa_id] = _parse_dt(due_iso)
                    a["active_days"].add(ar_dt.date())
            except Exception:
                pass


def _score_from_acc(email: str, d: dict, a: dict) -> dict:
    """Score one dispatcher from their accumulated data. No SF calls."""
    base = {"username": email, "name": d["name"], "role": d["role"],
            "channel": d.get("channel")}
    if d.get("observer"):
        return {**base, "observer": True,  "total": 0, "score": None, "tier": None}

    total = a["total"]
    if total == 0:
        return {**base, "observer": False, "total": 0, "score": None, "tier": None}

    raw_comp_pct = round(100 * a["completed"] / total, 1)
    adj_comp_pct = round(100 * a["weighted_complete"] / a["weighted_total"], 1) \
        if a["weighted_total"] else raw_comp_pct

    rt_vals  = a["response_times"]
    median_rt = round(statistics.median(rt_vals), 1) if rt_vals else 0.0
    slow_pct  = round(100 * sum(1 for r in rt_vals if r > 30) / len(rt_vals), 1) if rt_vals else 0.0
    fast_pct  = round(100 * sum(1 for r in rt_vals if r <= 5)  / len(rt_vals), 1) if rt_vals else 0.0
    rt_buckets = {
        "le5":    sum(1 for r in rt_vals if r <= 5),
        "5_15":   sum(1 for r in rt_vals if 5  < r <= 15),
        "15_30":  sum(1 for r in rt_vals if 15 < r <= 30),
        "30_60":  sum(1 for r in rt_vals if 30 < r <= 60),
        "60_120": sum(1 for r in rt_vals if 60 < r <= 120),
    }

    rescue_pct        = round(100 * a["rescue_count"] / total, 1)
    active_days_count = len(a["active_days"])
    daily_avg         = round(total / active_days_count, 1) if active_days_count else 0.0

    s_outcome     = _score_outcome(adj_comp_pct)
    s_speed       = _score_speed(median_rt)
    s_consistency = _score_consistency(slow_pct)
    s_volume      = _score_volume(total)
    total_score   = s_outcome + s_speed + s_consistency + s_volume

    call_types_sorted = sorted(
        [{"type": k, "count": v, "pct": round(100 * v / total, 1)}
         for k, v in a["call_types"].items()],
        key=lambda x: x["count"], reverse=True,
    )

    stall_vals = a["stall_mins"]
    median_arrival  = round(statistics.median(stall_vals), 1) if stall_vals else None
    p90_arrival     = round(sorted(stall_vals)[int(len(stall_vals) * 0.9)], 1) if stall_vals else None
    late_arrival_pct = round(100 * sum(1 for s in stall_vals if s > 60) / len(stall_vals), 1) \
        if stall_vals else None

    return {
        **base,
        "observer": False, "total": total, "completed": a["completed"],
        "raw_comp_pct": raw_comp_pct, "adj_comp_pct": adj_comp_pct,
        "median_rt_min": median_rt, "slow_pct": slow_pct, "fast_pct": fast_pct,
        "rt_buckets": rt_buckets, "call_types": call_types_sorted,
        "median_arrival_min": median_arrival, "p90_arrival_min": p90_arrival,
        "late_arrival_pct": late_arrival_pct,
        "rescue_pct": rescue_pct, "rescue_count": a["rescue_count"],
        "daily_avg": daily_avg, "active_days": active_days_count,
        "score": total_score,
        "score_breakdown": {"outcome": s_outcome, "speed": s_speed,
                            "consistency": s_consistency, "volume": s_volume},
        "tier": _tier(total_score),
        "pta_rate": round(100 * a["pta_met"] / a["pta_eligible"], 1) if a["pta_eligible"] else None,
        "pta_eligible": a["pta_eligible"],
    }


# ── Background computation helpers ───────────────────────────────────────────

def _load_shells() -> list:
    """Instant DB-only load — returns all dispatcher stubs without scores."""
    try:
        dispatchers = dispatcher_registry.load_dispatchers(resolve_sf_ids=False)
    except Exception:
        return []
    return [
        {
            "username": email,
            "name":     d["name"],
            "role":     d["role"],
            "channel":  d.get("channel"),
            "observer": bool(d.get("observer")),
            "total":    None,
            "score":    None,
            "tier":     None,
            "loading":  True,
        }
        for email, d in dispatchers.items()
    ]


def _bg_compute(ck: str):
    """Batch-compute scorecard: one SF query per batch of dispatchers.

    Partial results are written to _PARTIAL_KEY after each batch so the
    frontend sees scored rows appear progressively instead of all at once.
    """
    try:
        dispatchers = dispatcher_registry.load_dispatchers()
    except Exception as e:
        log.error("Scorecard: dispatcher registry load failed: %s", e)
        cache.invalidate(_COMPUTING_KEY)
        return
    if not dispatchers:
        log.error("Dispatcher registry is empty")
        cache.invalidate(_COMPUTING_KEY)
        return

    sf_to_email = {d["sf_id"]: email for email, d in dispatchers.items() if d.get("sf_id")}
    active = [(e, d) for e, d in dispatchers.items()
              if not d.get("observer") and d.get("sf_id")]

    # Seed partial with shells immediately
    partial: dict[str, dict] = {s["username"]: s for s in _load_shells()}
    cache.put(_PARTIAL_KEY, {"dispatchers": list(partial.values())}, ttl=600)

    # Score observers now — they need no SF data
    for email, d in dispatchers.items():
        if d.get("observer"):
            partial[email] = _score_from_acc(email, d, _init_acc())
    cache.put(_PARTIAL_KEY, {"dispatchers": list(partial.values())}, ttl=600)

    all_acc:            dict[str, dict] = {e: _init_acc() for e, _ in active}
    all_sa_first:       dict[str, dict] = {}
    sa_first_dispatcher: dict[str, str] = {}
    sa_due_dates:       dict[str, object] = {}

    try:
        for i in range(0, len(active), _BATCH_SIZE):
            batch = active[i:i + _BATCH_SIZE]
            id_list = ", ".join("'" + d["sf_id"] + "'" for _, d in batch)
            rows = sf_query_all(_AR_SOQL.format(id_list=id_list))
            _accumulate_rows(rows, all_acc, all_sa_first, sa_first_dispatcher, sf_to_email, sa_due_dates)

            # Score this batch and update partial — frontend sees these immediately
            for email, d in batch:
                partial[email] = _score_from_acc(email, d, all_acc[email])
            cache.put(_PARTIAL_KEY, {"dispatchers": list(partial.values())}, ttl=600)
            log.info("Scorecard batch %d/%d done (%d dispatchers scored)",
                     i // _BATCH_SIZE + 1, -(-len(active) // _BATCH_SIZE), i + len(batch))

        # Arrival stalls — one final SF query across all SAs
        on_loc = _fetch_arrival_stalls(list(all_sa_first.keys()))
        for sid, info in all_sa_first.items():
            if sid in on_loc:
                stall = (on_loc[sid] - info["dispatch_dt"]).total_seconds() / 60
                if 0 < stall <= 240:
                    all_acc[info["email"]]["stall_mins"].append(stall)
                due = sa_due_dates.get(sid)
                if due:
                    all_acc[info["email"]]["pta_eligible"] += 1
                    if on_loc[sid] <= due:
                        all_acc[info["email"]]["pta_met"] += 1

        # Final re-score with arrival data baked in
        final: list[dict] = []
        for email, d in dispatchers.items():
            final.append(_score_from_acc(email, d, all_acc.get(email, _init_acc())))

        # ── Channel peer stats and rank ───────────────────────────────────────
        _scored_final = [d for d in final if not d.get("observer") and d.get("score") is not None]
        _ch_groups: dict[str, list] = {}
        for _d in _scored_final:
            _ch = _d.get("channel") or "Unknown"
            _ch_groups.setdefault(_ch, []).append(_d)
        for _ch, _grp in _ch_groups.items():
            _grp.sort(key=lambda x: x["score"], reverse=True)
            _avg_comp = round(statistics.mean(g["adj_comp_pct"] for g in _grp), 1) if _grp else 0.0
            _avg_rt   = round(statistics.mean(g["median_rt_min"] for g in _grp), 1) if _grp else 0.0
            for _rank, _g in enumerate(_grp, 1):
                _g["channel_rank"]           = _rank
                _g["channel_size"]           = len(_grp)
                _g["channel_avg_completion"] = _avg_comp
                _g["channel_avg_response"]   = _avg_rt

        active_sorted = sorted(
            [d for d in final if not d["observer"] and d["score"] is not None],
            key=lambda x: x["score"], reverse=True,
        )
        no_data   = [d for d in final if not d["observer"] and d["score"] is None]
        observers = [d for d in final if d["observer"]]

        result = {
            "generated_at": time.time(), "window_days": 90, "status": "ready",
            "dispatchers": active_sorted + no_data + observers,
        }
        cache.disk_put(ck, result, ttl=35 * 86400)
        cache.put(ck, result, ttl=35 * 86400)
        log.info("Scorecard computation complete — %d scored", len(active_sorted))

    except Exception as e:
        log.error("Scorecard computation failed: %s", e)
    finally:
        cache.invalidate(_COMPUTING_KEY)
        cache.invalidate(_PARTIAL_KEY)


def _start_bg_compute(ck: str):
    """Start background compute if not already running. Thread-safe."""
    with _compute_lock:
        if not cache.get(_COMPUTING_KEY):
            cache.put(_COMPUTING_KEY, True, ttl=600)
            threading.Thread(target=_bg_compute, args=(ck,), daemon=True).start()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/reporting/dispatch-score")
def api_dispatch_score(request: Request, force_refresh: bool = False):
    """Dispatcher performance scorecard — monthly cache, 90-day rolling window."""
    _require_dispatch_score_role(request)

    ck = _cache_key()

    if not force_refresh:
        hit = cache.disk_get(ck) or cache.get(ck)
        if hit:
            hit.setdefault("status", "ready")
            return hit

        # Return partial in-progress results if background compute is underway
        partial = cache.get(_PARTIAL_KEY)
        if partial:
            return {"status": "computing", "generated_at": None,
                    "window_days": 90, "dispatchers": partial["dispatchers"]}

    # Return shells immediately; score in background
    _start_bg_compute(ck)
    return {"status": "computing", "generated_at": None, "window_days": 90, "dispatchers": _load_shells()}


@router.post("/api/reporting/dispatch-score/refresh")
def api_dispatch_score_refresh(request: Request):
    """Force-flush and recompute the monthly scorecard in background."""
    _require_dispatch_score_role(request)

    ck = _cache_key()
    cache.disk_invalidate(ck)
    cache.invalidate(ck)
    cache.invalidate(_COMPUTING_KEY)
    cache.invalidate(_PARTIAL_KEY)

    _start_bg_compute(ck)
    return {"status": "computing", "generated_at": None, "window_days": 90, "dispatchers": _load_shells()}


@router.get("/api/reporting/dispatch-score/{username}/insight")
def api_dispatcher_insight(username: str, request: Request, force_refresh: bool = False):
    """AI coaching insight for one dispatcher — monthly cache, generated on demand."""
    _require_dispatch_score_role(request)

    # Verify dispatcher exists in DB
    try:
        with db_adapter.reader() as db:
            db.execute(
                "SELECT 1 FROM dispatchers WHERE email = %s AND active = TRUE",
                (username,)
            )
            if not db.fetchone():
                raise HTTPException(status_code=404, detail="Dispatcher not found")
    except HTTPException:
        raise
    except Exception as e:
        log.warning("Dispatcher lookup failed for %s: %s", username, e)
        raise HTTPException(status_code=500, detail="Could not verify dispatcher")

    ck = _cache_key()
    ick = _insight_cache_key(username)

    if not force_refresh:
        hit = cache.disk_get(ick) or cache.get(ick)
        if hit:
            return _enforce_tip_rules(hit)

    # Ensure scorecard is available — trigger background compute if missing
    scorecard = cache.disk_get(ck) or cache.get(ck)
    if not scorecard:
        _start_bg_compute(ck)
        raise HTTPException(status_code=503, detail="Scorecard is computing — please wait a moment and try again")

    dispatcher_data = next(
        (d for d in scorecard.get("dispatchers", []) if d["username"] == username), None
    )
    if not dispatcher_data or dispatcher_data.get("score") is None:
        raise HTTPException(status_code=404, detail="No dispatch data for this user in the current 90-day window")

    result = _generate_insight(username, dispatcher_data)
    if "error" not in result:
        cache.disk_put(ick, result, ttl=35 * 86400)
        cache.put(ick, result, ttl=35 * 86400)
    return result
