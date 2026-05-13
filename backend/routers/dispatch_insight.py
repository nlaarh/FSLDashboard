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

YOUR PRIMARY RULE — READ THIS BEFORE ANYTHING ELSE:
The manager already sees all the numbers in the scorecard. They do NOT need you to repeat them.
Your job is to interpret the numbers — tell the manager what the PATTERN MEANS about this \
dispatcher's behavior, habits, and decision-making, and what to do about it.

ANTI-PATTERNS (never do these):
- Do not start sentences with a metric: "Her 27.5% late dispatch rate..." — banned.
- Do not restate the scorecard as prose: "She has a high completion rate of 89.6%" — banned.
- Do not give generic advice that applies to any dispatcher: "She should check the queue more often" \
without connecting it to her specific data pattern.
- Do not write vague coaching questions like "How do you feel about your performance?" — useless.

WHAT GOOD COACHING INSIGHT LOOKS LIKE:
- Interpret behavior: "Her response time distribution shows she handles the queue well under normal \
load but hits resistance at peak hours — this is not a motivation issue, it is a prioritization \
and workflow issue."
- Explain member impact: "When assignment spikes above 30 minutes, the member has already been \
waiting 30+ minutes from the call's start — that is the point where experience turns negative."
- Make coaching questions specific and exploratory: "Walk me through how you decide which SA to \
touch first when three come in at the same time." — this surfaces the actual decision-making habit.
- Make development steps concrete and tool-referenced: "Pull your Dispatch Trends for last month \
and identify the 2-hour window where your slow dispatch rate is highest — that is the shift \
segment to target first."

HOW AAA DISPATCH WORKS:
- Dispatchers use Salesforce FSL to assign drivers to Service Appointments (SAs). Core job: \
receive an incoming SA, review which territory/grid it belongs to, select the best qualified \
available driver, and confirm the assignment. Time from SA creation to driver assignment = \
response time we score.
- Grid/territory model: service area is divided into territories. Selecting a driver already in \
that territory is faster and reduces reassignment risk. Pulling from adjacent territory is a \
deliberate judgment call, not a default.
- Priority Matrix (P2–P10): SF surfaces ranked candidates by proximity, availability, and skills. \
Consistently bypassing top candidates signals a coaching opportunity on driver selection.
- Driver tiers: Gold (highest skill/seniority), Silver, Bronze, Platform (on-platform contractors). \
Mismatching driver tier to call complexity is the single biggest cause of reassignments.
- Call complexity weights: Battery/Lockout = 1.0x. Tire = 1.1x. Tow Pick-Up = 1.2x. Locksmith = \
1.3x. Winch Out = 2.0x. Tow Drop-Off = 0.8x. The adjusted completion rate uses these weights.
- Overnight/shift-change backlog: response times >120 min are capped in scoring to protect against \
inherited queues.

FSLPULSE tools (be accurate — do not invent features):
- Live Dispatch: real-time SA board. Scheduled SAs with no driver are waiting for action now.
- Watchlist: aging SA alerts and PTA violation alerts. Should be checked proactively each shift.
- Command Center: live map with territory overlay and driver positions. Use before assigning to \
understand geographic load.
- Dispatch Trends: time-of-day and day-of-week breakdown of response time and completion rate.
- SA Report: per-SA lifecycle timeline for post-mortems on specific slow or cancelled dispatches.

Respond with valid JSON only — no markdown, no commentary outside JSON.\
"""


def insight_cache_key(username: str) -> str:
    now = datetime.now(timezone.utc)
    return f"dispatch_insight_v3_{username}_{now.year}_{now.month:02d}"


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

    rescue_pct   = data.get("rescue_pct", 0) or 0
    rescue_count = data.get("rescue_count", 0) or 0
    active_days  = data.get("active_days") or 0
    daily_avg    = data.get("daily_avg") or 0

    channel      = data.get("channel") or "Unknown"
    chan_rank     = data.get("channel_rank")
    chan_size     = data.get("channel_size")
    chan_avg_comp = data.get("channel_avg_completion")
    chan_avg_rt   = data.get("channel_avg_response")
    pta_rate      = data.get("pta_rate")
    pta_elig      = data.get("pta_eligible", 0)

    peer_ctx = ""
    if chan_rank and chan_size:
        peer_ctx = (
            f"\n## Peer Benchmarking ({channel} channel, {chan_size} dispatchers)\n"
            f"- Channel rank: #{chan_rank} of {chan_size} by overall score\n"
            f"- Channel avg completion: {chan_avg_comp}%  (this dispatcher: {data.get('adj_comp_pct', 0)}%)\n"
            f"- Channel avg response:   {chan_avg_rt}m    (this dispatcher: {data.get('median_rt_min', 0):.1f}m)\n"
        )

    pta_ctx = ""
    if pta_rate is not None:
        pta_ctx = (
            f"\n## PTA Compliance (Promise Time to Arrive)\n"
            f"- PTA met rate: {pta_rate}% of {pta_elig} calls where arrival data is available\n"
            f"- PTA = % of calls where driver arrived On Location before the territory's promised time window\n"
            f"- Below 75% is a significant concern — members are waiting longer than promised\n"
        )

    user_prompt = f"""Generate a dispatcher performance coaching insight for a manager's 1:1 conversation.

## Dispatcher: {data.get('name')} | Role: {data.get('role', '').replace('ers-', '')} | Channel: {channel} | 90-Day Window

## Overall Score: {data.get('score', 0)}/100 — Tier: {data.get('tier', 'N/A')}
Score breakdown:
- Outcome (completion quality): {breakdown.get('outcome', 0)}/40 pts
- Speed (median response time): {breakdown.get('speed', 0)}/25 pts
- Consistency (slow dispatch rate): {breakdown.get('consistency', 0)}/20 pts
- Volume (total dispatches): {breakdown.get('volume', 0)}/15 pts
{peer_ctx}
## Key Metrics
- Total dispatches: {data.get('total', 0)}
- Complexity-adjusted completion: {data.get('adj_comp_pct', 0)}% (harder calls weighted more)
- Median response time: {data.get('median_rt_min', 0):.1f} min (SA created → driver assigned)
- Slow dispatch rate (>30 min): {data.get('slow_pct', 0)}%
- Fast dispatch rate (≤5 min): {data.get('fast_pct', 0)}%
{pta_ctx}{arrival_ctx}
## Engagement Metrics
- Active dispatch days (in 90-day window): {active_days}
- Daily avg dispatches: {daily_avg:.1f} per active day
- Rescue ratio: {rescue_pct}% ({rescue_count} calls) — calls inherited after a different dispatcher's earlier assignment on the same SA

## Response Time Distribution (times capped at 120 min)
{rt_context}

## Call Type Mix (with complexity weights)
{call_type_context if call_type_context else '  (no call type data)'}

## COACHING FOCUS — Weakest Dimension
This dispatcher's lowest-scoring dimension is **{weakest_dim}** at {weakest_pct}% of maximum.
Use this to focus your gap and development plan. Do NOT mention other areas as additional gaps.

## Required JSON Response (no markdown, no extra text):
{{
  "headline": "One sentence (≤20 words). State a behavioral observation or interpretation — NOT a metric. \
Example: 'Deonna handles routine queue load well but struggles to recover when two or more hard calls arrive simultaneously.'",

  "what_works": [
    {{
      "title": "Name the behavior or habit, not the metric",
      "detail": "Interpret what this tells you about the dispatcher's skill or judgment. Why does this matter for the member experience? \
Use the number as supporting evidence mid-sentence, not as the lead."
    }},
    {{
      "title": "Second distinct strength",
      "detail": "Same rule — behavioral interpretation, not a metric restatement."
    }}
  ],

  "the_gap": {{
    "title": "Name the behavioral gap, not the metric",
    "detail": "What is this dispatcher likely DOING or NOT DOING that produces this pattern? \
Connect it to a specific habit, workflow choice, or situational trigger. What does it cost the member?",
    "root_cause": "The single most specific, testable root cause — a concrete habit or trigger, not a restatement of the number. \
Example: 'Likely not checking the queue proactively at shift transitions — inheriting a backlog and then catching up rather than staying current.'"
  }},

  "coaching_starters": [
    "An open, non-leading question that invites this dispatcher to reflect on what they do WELL — reinforces the strength. \
Example: 'What do you do when a Winch Out comes in during a busy period — walk me through your process.'",
    "An open, non-leading question that explores the GAP without assuming blame. \
Example: 'What's typically happening around your desk when you notice an SA has been sitting for 20+ minutes without being assigned?'"
  ],

  "development_plan": "2–3 numbered concrete steps for the next 30 days. Each step must reference a specific tool (Live Dispatch, \
Watchlist, Dispatch Trends, SA Report) or a specific behavior change. Make the first step something they can do on their \
next shift. Example: '1. At the start of each shift, open Dispatch Trends and identify your two slowest dispatch hours from \
last week — that is your target window. 2. Set a personal rule: if an SA sits in your queue unseen for more than 10 minutes, \
it gets worked next, regardless of what else is happening. 3. End-of-week: pull 3 of your longest-wait SAs in SA Report and \
identify what interrupted you each time.'",

  "manager_action": "One specific action the manager takes THIS WEEK. Start with an action verb (Schedule, Pull, Review, Ask, Shadow). \
Reference a specific tool or data point. Example: 'Pull Deonna's Dispatch Trends for the past 4 weeks and identify which \
specific 2-hour window has the highest slow-dispatch spike — bring that chart to your next 1:1.'"
}}
Include exactly 2 items in what_works. Exactly 2 items in coaching_starters. One the_gap object. One development_plan string. \
One manager_action string. NEVER start any field value by restating a raw metric."""

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
