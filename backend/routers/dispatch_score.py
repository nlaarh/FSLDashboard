"""Dispatcher Performance Scorecard — monthly-cached, AI-powered coaching insights.

Scores active ERS dispatchers on outcome quality, response speed, consistency,
and volume over a rolling 90-day window. Cache key rotates monthly so each
month gets its own snapshot. Managers can force-refresh at any time.
"""

import logging
import statistics
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

import cache
import users
from sf_client import sf_query_all
from utils import parse_dt as _parse_dt
from routers.dispatch_insight import generate_insight as _generate_insight, insight_cache_key as _insight_cache_key, _enforce_tip_rules

router = APIRouter()
log = logging.getLogger('dispatch_score')

# ── Dispatcher registry ───────────────────────────────────────────────────────
# Maps FSL App username → SF UserId. Excludes tingraham and dfisher per spec.
# observer=True: account exists but dispatches 0 SAs — shown as no-data cards.
_DISPATCHERS = {
    "jharrington@nyaaa.com":  {"sf_id": "005Pb0000009r4FIAQ", "name": "Jeremy Harrington",  "role": "ers-manager",    "channel": "Fleet"},
    "jcarroll@nyaaa.com":     {"sf_id": "005Pb0000009r4LIAQ", "name": "Jon Carroll",         "role": "ers-manager",    "channel": "Fleet"},
    "calger@nyaaa.com":       {"sf_id": "005Pb0000009qjBIAQ", "name": "Catherine Alger",     "role": "ers-supervisor", "channel": "Towbook"},
    "khartman@nyaaa.com":     {"sf_id": "005Pb0000009qjDIAQ", "name": "Kristen Hartman",     "role": "ers-supervisor", "channel": "Towbook"},
    "sgancasz@nyaaa.com":     {"sf_id": "005Pb0000009r4CIAQ", "name": "Shawn Gancasz",       "role": "ers-supervisor", "channel": "Mixed"},
    "dkalenda@nyaaa.com":     {"sf_id": "005Pb0000009qjGIAQ", "name": "Deborah Kalenda",     "role": "ers-supervisor", "channel": "Towbook"},
    "mtrichilo@nyaaa.com":    {"sf_id": "005Pb0000009qjUIAQ", "name": "Mary Trichilo",       "role": "ers-supervisor", "channel": "Supervisor"},
    "cmacneil@nyaaa.com":     {"sf_id": "005Pb0000009qjbIAA", "name": "Chris Macneil",       "role": "ers-manager",    "channel": "Overnight"},
    "shorn@nyaaa.com":        {"sf_id": "005Pb0000009qjaIAA", "name": "Stephen Horn",        "role": "ers-manager",    "channel": "Overnight"},
    "rprendergast@nyaaa.com": {"sf_id": "005Pb0000009qjgIAA", "name": "Robert Prendergast", "role": "ers-manager",    "channel": None, "observer": True},
    "tcoulter@nyaaa.com":     {"sf_id": "005Pb0000009qjXIAQ", "name": "Todd Coulter",        "role": "ers-manager",    "channel": None, "observer": True},
    "mmika@nyaaa.com":        {"sf_id": "005Pb0000009qjcIAA", "name": "Mark Mika",           "role": "ers-manager",    "channel": None, "observer": True},
    "rlyle@nyaaa.com":        {"sf_id": "005Pb00000qNc6gIAC", "name": "Robert Lyle",         "role": "ers-manager",    "channel": None, "observer": True},
}

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
    return f"dispatch_score_v2_{now.year}_{now.month:02d}"


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

def _compute_scorecard() -> dict:
    """Query SF AssignedResource (last 90 days) and compute scores for all dispatchers."""
    active_sf_ids = [d["sf_id"] for uname, d in _DISPATCHERS.items() if not d.get("observer")]
    id_list = ", ".join(f"'{sid}'" for sid in active_sf_ids)

    soql = (
        "SELECT Id, CreatedDate, CreatedById, ServiceAppointmentId, "
        "ServiceAppointment.Status, ServiceAppointment.CreatedDate, "
        "ServiceAppointment.WorkType.Name, ServiceAppointment.RecordType.Name "
        "FROM AssignedResource "
        "WHERE CreatedDate = LAST_N_DAYS:90 "
        "AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment' "
        f"AND CreatedById IN ({id_list}) "
        "ORDER BY ServiceAppointmentId, CreatedDate ASC"
    )

    rows = sf_query_all(soql)

    # Map SF UserId → username for quick lookup
    sf_to_username = {d["sf_id"]: uname for uname, d in _DISPATCHERS.items()}

    # Initialize accumulator per dispatcher
    acc: dict[str, dict] = {}
    for uname, d in _DISPATCHERS.items():
        acc[uname] = {
            "total": 0,
            "completed": 0,
            "weighted_complete": 0.0,
            "weighted_total": 0.0,
            "response_times": [],
            "call_types": {},
            "stall_mins": [],   # dispatch → On Location
        }

    sa_first: dict[str, dict] = {}  # sa_id → {uname, dispatch_dt} for stall computation

    for row in rows:
        uname = sf_to_username.get(row.get("CreatedById"))
        if not uname:
            continue
        sa = row.get("ServiceAppointment") or {}
        status = sa.get("Status") or ""
        work_type = (sa.get("WorkType") or {}).get("Name") or ""

        a = acc[uname]
        a["total"] += 1
        a["call_types"][work_type or "Unknown"] = a["call_types"].get(work_type or "Unknown", 0) + 1

        weight = _complexity_weight(work_type)
        a["weighted_total"] += weight
        if status == "Completed":
            a["completed"] += 1
            a["weighted_complete"] += weight

        ar_created = row.get("CreatedDate")
        sa_created = sa.get("CreatedDate")
        sa_id = row.get("ServiceAppointmentId")
        if ar_created and sa_created:
            try:
                ar_dt = _parse_dt(ar_created)
                sa_dt = _parse_dt(sa_created)
                if ar_dt and sa_dt:
                    rt = (ar_dt - sa_dt).total_seconds() / 60
                    if rt > 0:
                        a["response_times"].append(min(rt, _RESPONSE_CAP_MIN))
                    # Track first human-dispatcher assignment per SA for stall computation
                    if sa_id and sa_id not in sa_first and ar_dt:
                        sa_first[sa_id] = {"uname": uname, "dispatch_dt": ar_dt}
            except Exception:
                pass

    # Fetch On Location times and compute stall (dispatch → driver arrived)
    on_loc = _fetch_arrival_stalls(list(sa_first.keys()))
    for sid, info in sa_first.items():
        if sid in on_loc:
            stall = (on_loc[sid] - info["dispatch_dt"]).total_seconds() / 60
            if 0 < stall <= 240:  # cap at 4h to exclude multi-day inherited SAs
                uname = info["uname"]
                if uname in acc:
                    acc[uname]["stall_mins"].append(stall)

    # Score each dispatcher
    scored = []
    for uname, d in _DISPATCHERS.items():
        if d.get("observer"):
            scored.append({
                "username": uname, "name": d["name"], "role": d["role"],
                "channel": d.get("channel"), "observer": True, "total": 0, "score": None, "tier": None,
            })
            continue

        a = acc[uname]
        total = a["total"]

        if total == 0:
            scored.append({
                "username": uname, "name": d["name"], "role": d["role"],
                "channel": d.get("channel"), "observer": False, "total": 0, "score": None, "tier": None,
            })
            continue

        raw_comp_pct = round(100 * a["completed"] / total, 1)
        adj_comp_pct = round(100 * a["weighted_complete"] / a["weighted_total"], 1) if a["weighted_total"] else raw_comp_pct

        rt_vals = a["response_times"]
        median_rt = round(statistics.median(rt_vals), 1) if rt_vals else 0.0
        slow_pct = round(100 * sum(1 for r in rt_vals if r > 30) / len(rt_vals), 1) if rt_vals else 0.0
        fast_pct = round(100 * sum(1 for r in rt_vals if r <= 5) / len(rt_vals), 1) if rt_vals else 0.0

        rt_buckets = {
            "le5":   sum(1 for r in rt_vals if r <= 5),
            "5_15":  sum(1 for r in rt_vals if 5 < r <= 15),
            "15_30": sum(1 for r in rt_vals if 15 < r <= 30),
            "30_60": sum(1 for r in rt_vals if 30 < r <= 60),
            "60_120": sum(1 for r in rt_vals if 60 < r <= 120),
        }

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
        median_arrival = round(statistics.median(stall_vals), 1) if stall_vals else None
        p90_arrival = round(sorted(stall_vals)[int(len(stall_vals) * 0.9)], 1) if stall_vals else None
        late_arrival_pct = round(100 * sum(1 for s in stall_vals if s > 60) / len(stall_vals), 1) if stall_vals else None

        scored.append({
            "username": uname,
            "name": d["name"],
            "role": d["role"],
            "channel": d.get("channel"),
            "observer": False,
            "total": total,
            "completed": a["completed"],
            "raw_comp_pct": raw_comp_pct,
            "adj_comp_pct": adj_comp_pct,
            "median_rt_min": median_rt,
            "slow_pct": slow_pct,
            "fast_pct": fast_pct,
            "rt_buckets": rt_buckets,
            "call_types": call_types_sorted,
            "median_arrival_min": median_arrival,
            "p90_arrival_min": p90_arrival,
            "late_arrival_pct": late_arrival_pct,
            "score": total_score,
            "score_breakdown": {
                "outcome": s_outcome,
                "speed": s_speed,
                "consistency": s_consistency,
                "volume": s_volume,
            },
            "tier": _tier(total_score),
        })

    active   = sorted([d for d in scored if not d["observer"] and d["score"] is not None],
                      key=lambda x: x["score"], reverse=True)
    no_data  = [d for d in scored if not d["observer"] and d["score"] is None]
    observers = [d for d in scored if d["observer"]]

    return {
        "generated_at": time.time(),
        "window_days": 90,
        "dispatchers": active + no_data + observers,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/reporting/dispatch-score")
def api_dispatch_score(request: Request, force_refresh: bool = False):
    """Dispatcher performance scorecard — monthly cache, 90-day rolling window."""
    _require_dispatch_score_role(request)

    ck = _cache_key()

    if not force_refresh:
        hit = cache.disk_get(ck) or cache.get(ck)
        if hit:
            return hit

    result = _compute_scorecard()
    cache.disk_put(ck, result, ttl=35 * 86400)
    cache.put(ck, result, ttl=35 * 86400)
    return result


@router.post("/api/reporting/dispatch-score/refresh")
def api_dispatch_score_refresh(request: Request):
    """Force-flush and recompute the monthly scorecard."""
    _require_dispatch_score_role(request)

    ck = _cache_key()
    cache.disk_invalidate(ck)
    cache.invalidate(ck)

    result = _compute_scorecard()
    cache.disk_put(ck, result, ttl=35 * 86400)
    cache.put(ck, result, ttl=35 * 86400)
    return result


@router.get("/api/reporting/dispatch-score/{username}/insight")
def api_dispatcher_insight(username: str, request: Request, force_refresh: bool = False):
    """AI coaching insight for one dispatcher — monthly cache, generated on demand."""
    _require_dispatch_score_role(request)

    if username not in _DISPATCHERS:
        raise HTTPException(status_code=404, detail="Dispatcher not found")

    ck = _cache_key()
    ick = _insight_cache_key(username)

    if not force_refresh:
        hit = cache.disk_get(ick) or cache.get(ick)
        if hit:
            # Re-apply tip rules on read — cleans any pre-filter cached results
            return _enforce_tip_rules(hit)

    # Ensure scorecard is available
    scorecard = cache.disk_get(ck) or cache.get(ck)
    if not scorecard:
        scorecard = _compute_scorecard()
        cache.disk_put(ck, scorecard, ttl=35 * 86400)
        cache.put(ck, scorecard, ttl=35 * 86400)

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
