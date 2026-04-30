"""Accounting AI helpers — audit narrative and analytics story generation."""

import json as _json
import logging
from utils import load_ai_settings as _load_ai_settings, call_openai_simple as _call_openai_simple
from routers.accounting_calc import _DEFAULT_AUDIT_PROMPT

log = logging.getLogger('accounting')

_ANALYTICS_STORY_PROMPT = (
    "You are a trusted accounting advisor speaking directly to an accountant at AAA Western & Central NY "
    "roadside assistance. You have just reviewed all open Work Order Adjustments (WOAs) — garage invoices "
    "disputing what they were paid. Your job: explain what the data is telling them in plain English. "
    "Tell the story of what is driving disputes, which garages need attention first, who is submitting the most "
    "adjustments, what the root causes are, and exactly what the accountant should do this week. "
    "\n\nProduct codes: ER=Enroute Miles, TW=Tow Miles, E1=Extrication, BA=Base Rate, TL=Tolls/Parking, "
    "MH=Medium/Heavy Duty, MI=Wait Time. "
    "\n\nBe specific — name the garages, the amounts, the patterns. Do not be vague. "
    "Prioritize by dollar impact and fraud risk. "
    "Respond ONLY with valid JSON — no markdown, no commentary outside JSON: "
    '{"headline":"one sentence summary of the situation",'
    '"story":"4-6 sentence narrative written for the accountant — what is happening and why",'
    '"top_concerns":["specific concern 1 with garage name and amount","concern 2"],'
    '"root_causes":["root cause 1","root cause 2"],'
    '"action_plan":["specific action 1 — do this today","action 2","action 3"],'
    '"watch_list":["garage or submitter name: reason to watch"]}'
)


def call_audit_ai(data_context: dict, garage_history: dict | None = None) -> dict:
    """Call GPT for a single WOA audit. Returns parsed AI fields or safe defaults."""
    _provider, api_key, model = _load_ai_settings()
    if not api_key:
        return {
            'recommendation': 'REVIEW', 'confidence': 'LOW',
            'headline': None, 'story': 'AI not configured. Go to Admin → AI Assistant to set up.',
            'fraud_signals': [], 'anomalies': [], 'what_to_do': [], 'ask_garage': [],
            'ai_summary': 'AI not configured. Go to Admin → AI Assistant to set up.',
        }

    ctx = dict(data_context)
    if garage_history:
        ctx['garage_history_90d'] = garage_history

    user_prompt = f"Audit this WOA:\n\n{_json.dumps(ctx, indent=2, default=str)}"
    raw = _call_openai_simple(api_key, model, _DEFAULT_AUDIT_PROMPT, user_prompt)

    result = {
        'recommendation': 'REVIEW', 'confidence': 'LOW',
        'headline': None, 'story': raw,
        'fraud_signals': [], 'anomalies': [], 'what_to_do': [], 'ask_garage': [],
        'ai_summary': raw,
    }

    if raw:
        try:
            clean = raw.strip()
            if clean.startswith('```'):
                clean = clean.split('\n', 1)[1] if '\n' in clean else clean[3:]
                clean = clean.rsplit('```', 1)[0]
            parsed = _json.loads(clean)
            result['recommendation'] = parsed.get('recommendation', 'REVIEW')
            result['confidence'] = parsed.get('confidence', 'LOW')
            result['headline'] = parsed.get('headline')
            result['story'] = parsed.get('story') or raw
            result['fraud_signals'] = parsed.get('fraud_signals') or []
            result['anomalies'] = parsed.get('anomalies') or []
            result['what_to_do'] = parsed.get('what_to_do') or []
            result['ask_garage'] = parsed.get('ask_garage') or []
            result['ai_summary'] = parsed.get('story') or raw
        except (_json.JSONDecodeError, AttributeError):
            pass

    return result


def build_analytics_story(analytics_data: dict) -> dict:
    """Call GPT to generate an accountant-facing narrative from analytics summary data."""
    _provider, api_key, model = _load_ai_settings()
    if not api_key:
        return {
            'headline': 'AI not configured',
            'story': 'Go to Admin → AI Assistant to set up.',
            'top_concerns': [], 'root_causes': [], 'action_plan': [], 'watch_list': [],
        }

    user_prompt = (
        "Here is the current WOA analytics summary. Generate an accountant advisory:\n\n"
        + _json.dumps(analytics_data, indent=2, default=str)
    )
    raw = _call_openai_simple(api_key, model, _ANALYTICS_STORY_PROMPT, user_prompt)

    fallback = {
        'headline': 'Analytics summary',
        'story': raw or 'Could not generate summary.',
        'top_concerns': [], 'root_causes': [], 'action_plan': [], 'watch_list': [],
    }

    if not raw:
        return fallback

    try:
        clean = raw.strip()
        if clean.startswith('```'):
            clean = clean.split('\n', 1)[1] if '\n' in clean else clean[3:]
            clean = clean.rsplit('```', 1)[0]
        parsed = _json.loads(clean)
        return {
            'headline': parsed.get('headline', ''),
            'story': parsed.get('story', ''),
            'top_concerns': parsed.get('top_concerns') or [],
            'root_causes': parsed.get('root_causes') or [],
            'action_plan': parsed.get('action_plan') or [],
            'watch_list': parsed.get('watch_list') or [],
        }
    except (_json.JSONDecodeError, AttributeError):
        return fallback


def _build_woa_audit(woa_id: str) -> dict:
    """Full audit including AI — used by recalculate."""
    from routers.accounting_audit import _build_woa_data
    data = _build_woa_data(woa_id)
    ctx = data.pop('_ai_context', {})
    gh = data.pop('_garage_history', None)
    ai = call_audit_ai(ctx, gh)
    data.update({
        'recommendation': ai['recommendation'], 'confidence': ai['confidence'],
        'ai_summary': ai['ai_summary'], 'ai_headline': ai.get('headline'),
        'ai_story': ai.get('story'), 'ai_fraud_signals': ai.get('fraud_signals') or [],
        'ai_anomalies': ai.get('anomalies') or [], 'ai_what_to_do': ai.get('what_to_do') or [],
        'ask_garage': ai.get('ask_garage') or [],
    })
    return data
