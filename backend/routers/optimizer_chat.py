"""Optimizer chat endpoint — domain-grounded AI with DuckDB tool calling."""

import json, re, logging
import requests as _requests
from fastapi import APIRouter, HTTPException, Request

import optimizer_db
import database

router = APIRouter(tags=['optimizer'])
log = logging.getLogger('optimizer_chat')

_ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
_ANTHROPIC_VERSION = '2023-06-01'
_DEFAULT_MODEL = 'claude-sonnet-4-6'
_MAX_TOKENS = 4096
_MAX_TOOL_ROUNDS = 5

_SYSTEM_PROMPT = """You are an expert FSL (Field Service Lightning) dispatch analyst for AAA WCNY.
You help dispatchers understand why the optimizer made specific assignment decisions.

## Your Domain Knowledge

**Dispatch channels:**
- Fleet (Field Services): ~26% of calls. THE OPTIMIZER ONLY TOUCHES FLEET SAs.
  ERS_Dispatch_Method__c = 'Field Services'
- Towbook: ~74% of calls. External contractors, NOT in optimizer scope.
If asked about Towbook decisions — explain the optimizer doesn't control those.

**Optimizer cadence:** Runs every 15 minutes, 3 territories simultaneously (WNY Fleet, 076DO, 089DO).

**Scheduling Policy in this org:** "Closest Driver" (Travel-heavy) — travel time is the dominant
scoring factor. Verified from 349 real assignments: closest driver wins 69% vs soonest 31%.

**Driver exclusion rules (a driver failing any rule is EXCLUDED):**
- territory: Driver's ServiceTerritories doesn't include this SA's territory
- skill: Driver lacks a required skill for this work type
- absent: Driver has an approved ResourceAbsence overlapping the SA's scheduled window
- capacity: Driver's shift window fully booked (eligible = passed all 3 above, not winner)

**Common unscheduled reason:** "Failed to reschedule a rule violating task" means the SA
was previously assigned to a driver who now violates a rule (skill removed, absence added,
territory changed) and no valid replacement was found in this run.

**Travel time:** Winner's travel time is exact (from optimizer). Non-winner eligible drivers
show estimated (~) travel times based on straight-line distance ÷ 25 mph mean speed.

**Key facts:**
- Pinned SAs (FSL__Pinned__c=true) are locked to their current driver — optimizer skips them
- Time-dependency pairs must stay with the same driver
- ERS_Dynamic_Priority__c affects scheduling order, not driver eligibility
- 5 scheduling policies exist: Closest Driver (active), Highest Priority, Emergency, DF TEST

**What you can answer:**
- Why a specific driver was/wasn't assigned to a specific SA
- Which work rule excluded a driver
- Patterns in exclusions over time (skill gaps, capacity overload, territory mismatches)
- Before/after KPI changes from an optimization run
- Which drivers get excluded most and why

**What you cannot answer:**
- Internal optimizer scoring weights (black box — you only see inputs and outputs)
- Towbook dispatcher decisions (completely different system)
- Future predictions (you only see historical runs stored in DuckDB)

Always be specific and cite the actual data. If data doesn't support a conclusion, say so.
When you have decision tree data for a specific SA, structure your response with the driver
breakdown clearly: winner first, then eligible (sorted by travel time), then excluded by reason.

## Visualization Output (emit when you have data)

After your prose explanation, if you have relevant structured data, emit a JSON visualization block
inside a triple-backtick json fence. The block MUST contain `visualization_type`.

**Decision tree** (when you have get_sa_decision data — use the most recent run's verdicts):
```json
{
  "visualization_type": "decision_tree",
  "sa_number": "SA-XXXXXXXX",
  "sa_work_type": "Battery",
  "territory_name": "WNY Fleet",
  "run_at": "2026-04-27T14:30:00",
  "action": "Scheduled",
  "unscheduled_reason": null,
  "winner": {"driver_name": "John Smith", "travel_time_min": 12.5},
  "eligible": [{"driver_name": "Jane Doe", "travel_time_min": null}],
  "excluded": {"territory": ["Bob Wilson"], "skill": [], "absent": [], "capacity": ["Sarah Johnson"]}
}
```

**KPI comparison** (when you have get_run_detail data with pre/post KPIs):
```json
{
  "visualization_type": "kpi_comparison",
  "run_name": "WNY Fleet 14:15",
  "before": {"scheduled": 6, "unscheduled": 2, "travel_s": 1200},
  "after":  {"scheduled": 8, "unscheduled": 0, "travel_s": 900}
}
```

**Exclusion chart** (when you have get_exclusion_patterns data):
```json
{
  "visualization_type": "exclusion_chart",
  "days": 7,
  "territory": "WNY Fleet",
  "patterns": [{"reason": "territory", "fires": 234, "drivers_affected": 18}]
}
```

Build the JSON from the actual tool results. Use null for unknown values. Eligible drivers come
from verdicts with status='eligible'; excluded from status='excluded' grouped by exclusion_reason.
Only emit ONE visualization block per response (the most relevant one).
"""

_TOOLS = [
    {
        "name": "list_runs",
        "description": "List optimization runs in a time window. Use to show the run timeline or find recent runs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_dt": {"type": "string", "description": "ISO datetime start (e.g. '2026-04-28T00:00:00Z')"},
                "to_dt": {"type": "string", "description": "ISO datetime end"},
                "territory": {"type": "string", "description": "Optional territory filter (partial name match)"},
            },
        },
    },
    {
        "name": "get_run_detail",
        "description": "Get full detail of one optimization run: KPIs and all SA decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "OptimizationRequest SF Id (starts with a1u)"},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "get_sa_decision",
        "description": "Get the decision tree for a specific SA — winner, eligible drivers, excluded drivers with reasons. Use when dispatcher asks about a specific SA number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sa_number": {"type": "string", "description": "SA number e.g. 'SA-04799070' or '04799070'"},
                "limit": {"type": "integer", "description": "Number of recent runs to include (default 1, max 5)"},
            },
            "required": ["sa_number"],
        },
    },
    {
        "name": "get_driver_analysis",
        "description": "Analyze a driver's optimizer history — how often assigned, eligible, or excluded and why.",
        "input_schema": {
            "type": "object",
            "properties": {
                "driver_name": {"type": "string", "description": "Driver name or partial name (e.g. '076DO')"},
                "days": {"type": "integer", "description": "Days to analyze (default 7)"},
            },
            "required": ["driver_name"],
        },
    },
    {
        "name": "get_unscheduled_analysis",
        "description": "Show all SAs the optimizer failed to schedule in a specific run, with reasons.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "OptimizationRequest SF Id"},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "get_exclusion_patterns",
        "description": "Aggregate patterns — which exclusion reasons fire most, how many drivers affected. Use for 'what patterns do you see?' questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "territory": {"type": "string", "description": "Optional territory filter"},
                "days": {"type": "integer", "description": "Days to analyze (default 7)"},
            },
        },
    },
    {
        "name": "query_optimizer",
        "description": "Run a read-only SQL query against DuckDB. Tables: opt_runs, opt_sa_decisions, opt_driver_verdicts. Use for novel analytical questions not covered by other tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT query only. No DDL/DML."},
            },
            "required": ["sql"],
        },
    },
]


def _execute_tool(name: str, inputs: dict) -> str:
    try:
        if name == 'list_runs':
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            from_dt = inputs.get('from_dt') or (now - timedelta(hours=24)).isoformat()
            to_dt = inputs.get('to_dt') or now.isoformat()
            result = optimizer_db.list_runs(from_dt, to_dt, inputs.get('territory'))
        elif name == 'get_run_detail':
            result = optimizer_db.get_run_detail(inputs['run_id'])
        elif name == 'get_sa_decision':
            result = optimizer_db.get_sa_decision(inputs['sa_number'], inputs.get('limit', 1))
        elif name == 'get_driver_analysis':
            result = optimizer_db.get_driver_analysis(inputs['driver_name'], inputs.get('days', 7))
        elif name == 'get_unscheduled_analysis':
            result = optimizer_db.get_unscheduled_analysis(inputs['run_id'])
        elif name == 'get_exclusion_patterns':
            result = optimizer_db.get_exclusion_patterns(inputs.get('territory'), inputs.get('days', 7))
        elif name == 'query_optimizer':
            result = optimizer_db.query_optimizer_sql(inputs['sql'])
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


_OAI_URL = 'https://api.openai.com/v1/chat/completions'
_DEFAULT_OAI_MODEL = 'gpt-4o'

# OpenAI uses different tool schema — convert once at import time
_OAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        }
    }
    for t in _TOOLS
]


def _call_anthropic(api_key: str, model: str, system: str, messages: list) -> dict:
    headers = {
        'x-api-key': api_key,
        'anthropic-version': _ANTHROPIC_VERSION,
        'content-type': 'application/json',
    }
    r = _requests.post(_ANTHROPIC_URL, headers=headers, timeout=60, json={
        'model': model, 'max_tokens': _MAX_TOKENS,
        'system': system, 'messages': messages, 'tools': _TOOLS,
    })
    r.raise_for_status()
    return r.json()


def _call_openai(api_key: str, model: str, system: str, messages: list) -> dict:
    headers = {'Authorization': f'Bearer {api_key}', 'content-type': 'application/json'}
    r = _requests.post(_OAI_URL, headers=headers, timeout=60, json={
        'model': model, 'max_tokens': _MAX_TOKENS,
        'messages': [{'role': 'system', 'content': system}, *messages],
        'tools': _OAI_TOOLS,
    })
    r.raise_for_status()
    return r.json()


def _anthropic_loop(api_key: str, model: str, system: str, messages: list) -> tuple[str, list]:
    """Run Anthropic tool loop. Returns (final_text, messages_state)."""
    for _ in range(_MAX_TOOL_ROUNDS):
        resp = _call_anthropic(api_key, model, system, messages)
        content = resp.get('content', [])
        stop_reason = resp.get('stop_reason', '')
        text_parts = [b['text'] for b in content if b.get('type') == 'text']
        tool_calls = [b for b in content if b.get('type') == 'tool_use']

        if stop_reason == 'end_turn' or not tool_calls:
            return '\n'.join(text_parts), messages

        messages = messages + [{'role': 'assistant', 'content': content}]
        messages = messages + [{'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': tc['id'],
             'content': _execute_tool(tc['name'], tc.get('input', {}))}
            for tc in tool_calls
        ]}]
    return 'Reached maximum tool calls. Try a more specific question.', messages


def _openai_loop(api_key: str, model: str, system: str, messages: list) -> tuple[str, list]:
    """Run OpenAI tool loop. Returns (final_text, messages_state)."""
    for _ in range(_MAX_TOOL_ROUNDS):
        resp = _call_openai(api_key, model, system, messages)
        choice = resp['choices'][0]
        msg = choice['message']
        finish = choice.get('finish_reason', '')
        tool_calls = msg.get('tool_calls') or []
        text = msg.get('content') or ''

        if finish == 'stop' or not tool_calls:
            return text, messages

        messages = messages + [msg]
        tool_results = []
        for tc in tool_calls:
            fn = tc['function']
            try:
                args = json.loads(fn['arguments'])
            except Exception:
                args = {}
            tool_results.append({
                'role': 'tool',
                'tool_call_id': tc['id'],
                'content': _execute_tool(fn['name'], args),
            })
        messages = messages + tool_results
    return 'Reached maximum tool calls. Try a more specific question.', messages


def _extract_visualization(text: str) -> dict | None:
    match = re.search(r'```json\n([\s\S]*?)\n```', text)
    if match:
        try:
            data = json.loads(match.group(1))
            if 'visualization_type' in data:
                return data
        except Exception:
            pass
    return None


@router.post('/api/optimizer/chat')
async def optimizer_chat(request: Request):
    body = await request.json()
    messages = body.get('messages', [])
    run_context = body.get('run_context')

    if not messages:
        raise HTTPException(400, "messages required")

    import os as _os
    settings = database.get_all_settings()
    oc = settings.get('optimizer_chat', {})
    provider = oc.get('provider', 'anthropic')
    model = oc.get('model', '')

    if provider == 'openai':
        api_key = (settings.get('openai_api_key', '')
                   or _os.environ.get('OPENAI_API_KEY', ''))
        model = model or _DEFAULT_OAI_MODEL
        if not api_key:
            raise HTTPException(503, "OpenAI API key not configured — set it in Admin > AI Settings")
    else:
        # Default: Anthropic
        provider = 'anthropic'
        chatbot_key = settings.get('chatbot', {}).get('api_key', '') \
                      if settings.get('chatbot', {}).get('provider') == 'anthropic' else ''
        api_key = (settings.get('anthropic_api_key', '')
                   or chatbot_key
                   or _os.environ.get('ANTHROPIC_API_KEY', ''))
        model = model or _DEFAULT_MODEL
        if not api_key:
            raise HTTPException(503, "Anthropic API key not configured — set it in Admin > AI Settings")

    system = _SYSTEM_PROMPT
    if run_context:
        system += (
            f"\n\n## Current Context\nThe dispatcher is looking at run "
            f"{run_context.get('run_name', '')} "
            f"(ID: {run_context.get('run_id', '')}, "
            f"Territory: {run_context.get('territory_name', '')}, "
            f"Time: {run_context.get('run_at', '')}). "
            f"Prioritize data from this run when answering."
        )

    try:
        if provider == 'openai':
            text, _ = _openai_loop(api_key, model, system, list(messages))
        else:
            text, _ = _anthropic_loop(api_key, model, system, list(messages))
    except _requests.RequestException as e:
        log.error(f"{provider} API error: {e}")
        status = e.response.status_code if hasattr(e, 'response') and e.response is not None else 0
        raise HTTPException(502, f"{provider} API unreachable: {status or 'connection error'}")

    return {'text': text, 'visualization': _extract_visualization(text)}
