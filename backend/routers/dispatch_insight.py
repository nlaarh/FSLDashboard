"""AI coaching insight generation for the Dispatcher Scorecard.

Separated from dispatch_score.py to keep that file under the 600-line ceiling.
"""

import json as _json
import logging
from datetime import datetime, timezone

from utils import load_ai_settings as _load_ai_settings, call_openai_simple as _call_openai_simple

log = logging.getLogger('dispatch_insight')

_COMPLEXITY = {
    "tow drop-off": 0.8,
    "battery":      1.0,
    "lockout":      1.0,
    "tire":         1.1,
    "tow pick-up":  1.2,
    "locksmith":    1.3,
    "winch out":    2.0,
}

_INSIGHT_SYSTEM = """\
You are an expert ERS dispatcher performance coach at AAA roadside assistance (NYAAA).

HOW AAA DISPATCH WORKS — embed this in every tip you give:
- Dispatchers use Salesforce FSL to assign drivers to Service Appointments (SAs). The core job: \
receive an incoming SA, review which territory/grid it belongs to, select the most qualified and \
available driver, and confirm the assignment. The time from SA creation to driver assignment is \
the response time we measure.
- Grid/territory model: the service area is divided into service territories. Each SA is routed to \
a territory. Selecting a driver already positioned in that territory is faster and less likely to \
cause a reassignment. Pulling from an adjacent territory should be a deliberate decision.
- Priority Matrix (P2–P10): Salesforce generates a ranked candidate list for each SA, ordered by \
proximity, availability, and skills. Following the ranked list reduces travel time and cascade \
reassignments. Consistently bypassing top candidates without reason is a coaching signal.
- Driver tiers: Gold (highest skill/seniority), Silver, Bronze, Platform (on-platform contractors). \
Call complexity must match driver capability — assigning a Bronze driver to a Winch Out or Locksmith \
call typically causes a reassignment that counts against both completion and response time.
- Call types and complexity: Battery/Lockout = routine. Tow Pick-Up = moderate (flatbed skills often \
required). Tow Drop-Off = simpler (destination already set). Tire = slightly complex. Locksmith = \
specialized, requires certification. Winch Out = highest complexity, requires specialized equipment. \
The adjusted completion rate accounts for this weighting.
- Overnight/shift-change backlog: some dispatchers inherit queued SAs from the prior shift. Response \
times >120 minutes are capped in scoring to protect against this unfair distortion.

FSLPULSE — what's available to dispatchers (be accurate, do not invent features):
- Live Dispatch: Real-time SA status board. Shows SAs in Scheduled (waiting dispatch), Dispatched \
(driver assigned, en route), On Location, and Complete states. A dispatcher should watch for any SA \
stuck in "Scheduled" >15 minutes — those are actionable right now.
- Watchlist: Operational alerts for aging SAs and PTA (Promise Time to Arrive) violations. Shows \
SAs at risk of missing their promised arrival window. Dispatchers should check this proactively at \
the start of each shift and every 30 minutes during high-volume periods.
- Command Center: Live map with territory/grid overlay showing where active SAs are distributed and \
which drivers are currently on route. Use this before making assignment decisions to understand the \
geographic load across the grid — avoid pulling the only available driver away from a hot zone.
- Dispatch Trends: Historical UTC and completion rate trends by time period. Use to identify \
time-of-day or day-of-week patterns where slow dispatch rate spikes. If a pattern exists, it \
points to coverage gaps or high-volume windows that need process adjustment.
- SA Report: Per-SA full lifecycle timeline. Use for post-mortems on slow or cancelled dispatches \
— the timeline shows exactly where time was lost (was the SA sitting unassigned? Did the driver \
not go on-route?).
- Dispatcher Drill: Per-dispatcher breakdown of UTC rate, response time distribution, and call type \
mix. Useful for self-review and comparing against peers.

SALESFORCE FSL — what dispatchers can use (be specific, not generic):
- Dispatcher Console / SA list: Primary SF view showing incoming SAs. Filter by territory, status, \
and priority code. "Scheduled" SAs with no assigned resource are waiting for action right now.
- Priority Matrix candidate list: When creating an AssignedResource record, SF surfaces ranked \
available drivers by proximity and skills. Following the top 2–3 candidates reduces travel time \
and reassignment risk.
- Driver Skills records: Each Service Resource (driver) has a Skills list. Before assigning to a \
Locksmith, Winch Out, or Tow Pick-Up requiring a flatbed, verify the driver holds the required \
skill — unqualified assignments cause the reassignment that tanks completion rate.
- Service Territory view: Shows territory boundaries on a map. When a call sits near a territory \
boundary, check both adjacent territories for available drivers rather than defaulting to one grid.
- SA Status filter: Filter to "Scheduled" to find SAs without assignments; filter to "Dispatched" \
to find SAs where the driver was assigned but hasn't gone on-route — these sometimes need a \
follow-up call to the driver.

Respond with valid JSON only — no markdown, no commentary outside JSON.
Be specific, evidence-based, and development-focused. Reference this dispatcher's actual numbers. \
Be compassionate but direct. Tailor every tip to the dispatcher's weakest dimension.\
"""


def insight_cache_key(username: str) -> str:
    now = datetime.now(timezone.utc)
    return f"dispatch_insight_{username}_{now.year}_{now.month:02d}"


def generate_insight(username: str, data: dict) -> dict:
    """Call AI to generate coaching insight for one dispatcher. Returns parsed JSON dict."""
    _provider, api_key, model = _load_ai_settings()
    if not api_key:
        return {"error": "AI not configured — go to Admin → AI Assistant to set up."}

    breakdown = data.get("score_breakdown", {})

    dim_pcts = {
        "Outcome": breakdown.get("outcome", 0) / 40,
        "Speed": breakdown.get("speed", 0) / 25,
        "Consistency": breakdown.get("consistency", 0) / 20,
        "Volume": breakdown.get("volume", 0) / 15,
    }
    weakest_dim = min(dim_pcts, key=dim_pcts.get)
    weakest_pct = round(dim_pcts[weakest_dim] * 100)

    call_type_lines = []
    for ct in data.get("call_types", [])[:6]:
        w = _COMPLEXITY.get(ct["type"].lower(), 1.0)
        call_type_lines.append(
            f"  - {ct['type']}: {ct['count']} dispatches ({ct['pct']}%) [complexity {w}x]"
        )
    call_type_context = "\n".join(call_type_lines)

    bk = data.get("rt_buckets", {})
    total = data.get("total", 1) or 1
    rt_context = (
        f"≤5 min: {bk.get('le5',0)} ({round(bk.get('le5',0)/total*100)}%)  |  "
        f"5–15 min: {bk.get('5_15',0)} ({round(bk.get('5_15',0)/total*100)}%)  |  "
        f"15–30 min: {bk.get('15_30',0)} ({round(bk.get('15_30',0)/total*100)}%)  |  "
        f"30–60 min: {bk.get('30_60',0)} ({round(bk.get('30_60',0)/total*100)}%)  |  "
        f"60–120 min: {bk.get('60_120',0)} ({round(bk.get('60_120',0)/total*100)}%)"
    )

    arrival = data.get("median_arrival_min")
    late_arr = data.get("late_arrival_pct")
    arrival_ctx = ""
    if arrival is not None:
        arrival_ctx = (
            f"\n## Driver Arrival (dispatch → On Location)\n"
            f"- Typical arrival time: {arrival} min after driver assignment\n"
            f"- Late arrivals (>60 min): {late_arr}% of calls\n"
        )

    user_prompt = f"""Generate a dispatcher performance coaching insight for a manager's 1:1 conversation.

## Dispatcher: {data.get('name')} | Role: {data.get('role', '').replace('ers-', '')} | Channel: {data.get('channel', 'Unknown')} | 90-Day Window

## Overall Score: {data.get('score', 0)}/100 — Tier: {data.get('tier', 'N/A')}
Score breakdown:
- Outcome (completion quality): {breakdown.get('outcome', 0)}/40 pts
- Speed (median response time): {breakdown.get('speed', 0)}/25 pts
- Consistency (slow dispatch rate): {breakdown.get('consistency', 0)}/20 pts
- Volume (total dispatches): {breakdown.get('volume', 0)}/15 pts

## Key Metrics
- Total dispatches: {data.get('total', 0)}
- Raw completion rate: {data.get('raw_comp_pct', 0)}% (completed / all dispatches)
- Complexity-adjusted completion: {data.get('adj_comp_pct', 0)}% (harder calls weighted more)
- Median response time: {data.get('median_rt_min', 0):.1f} min (SA created → driver assigned)
- Slow dispatch rate (>30 min): {data.get('slow_pct', 0)}%
- Fast dispatch rate (≤5 min): {data.get('fast_pct', 0)}%
{arrival_ctx}
## Response Time Distribution (times capped at 120 min)
{rt_context}

## Call Type Mix (with complexity weights)
{call_type_context if call_type_context else '  (no call type data)'}

## COACHING FOCUS — Weakest Dimension
This dispatcher's lowest-scoring dimension is **{weakest_dim}** at {weakest_pct}% of maximum.
- If Outcome is weak: focus on driver qualification matching, territory selection, call type complexity awareness
- If Speed is weak: focus on queue monitoring, reducing time between SA arrival and assignment
- If Consistency is weak: focus on time-of-day patterns, shift handoff management, identifying slow-dispatch spikes
- If Volume is weak: note if this is an observer/part-time role, acknowledge context before coaching

## Required JSON Response (no markdown, no extra text):
{{
  "summary": "2-3 sentences: overall performance picture, key pattern, and trajectory — be direct with specific numbers",
  "strengths": [
    {{"title": "strength name", "detail": "specific evidence with numbers — why this matters for the team and members"}}
  ],
  "development_areas": [
    {{"title": "area name", "detail": "the specific gap, the likely root cause given their call type mix and response time distribution, and one concrete action to take"}}
  ],
  "coaching_starters": [
    "Open-ended question the manager can ask in a 1:1 — tied to a specific metric or pattern in their data"
  ]
}}
Include exactly 2–3 items per section. Every item must be actionable and tied to this dispatcher's actual data."""

    raw = _call_openai_simple(api_key, model, _INSIGHT_SYSTEM, user_prompt, max_tokens=2500, temperature=0.3)
    if not raw:
        return {"error": "AI call failed — check API key configuration."}

    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:])
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3]
        result = _json.loads(cleaned)
        result.pop("sf_tips", None)
        result.pop("fslpulse_tips", None)
        return result
    except Exception:
        log.warning("dispatch insight JSON parse failed for %s; returning raw", username)
        return {
            "summary": raw,
            "strengths": [], "development_areas": [], "coaching_starters": [],
        }


def _enforce_tip_rules(result: dict) -> dict:
    """Remove tip sections — AI cannot reliably name correct tool names."""
    result.pop("sf_tips", None)
    result.pop("fslpulse_tips", None)
    return result
