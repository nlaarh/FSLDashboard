"""Chatbot router — AI assistant status, models, and chat endpoint."""

import os, re as _re, time
import requests as _requests
from datetime import datetime, timezone
from collections import defaultdict as _defaultdict
from fastapi import APIRouter, HTTPException, Request, Response
from utils import _ET
import cache
import users

from routers.chatbot_providers import _call_openai, _call_anthropic, _call_google
from routers.chatbot_context import (
    _classify_and_fetch_context, _sanitize_response, CHATBOT_SYSTEM_BASE,
)

router = APIRouter()

# ── Shared helpers (duplicated to avoid circular imports from main) ───────────
import hashlib, hmac, secrets

_AUTH_SECRET = os.environ.get("AUTH_SECRET", secrets.token_hex(32))


_AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
_AGENTMAIL_INBOX = os.environ.get("AGENTMAIL_INBOX", "fslnyaaa@agentmail.to")


def _verify_cookie(cookie: str) -> str | None:
    if not cookie or "." not in cookie:
        return None
    payload, sig = cookie.rsplit(".", 1)
    expected = hmac.new(_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return payload
    return None


def _load_settings():
    try:
        import database
        return database.get_all_settings()
    except Exception:
        return {}


def _send_issue_email(to_email: str, subject: str, body_text: str):
    """Send email via AgentMail API (fire-and-forget, never raises)."""
    if not _AGENTMAIL_API_KEY or not to_email:
        return
    try:
        _requests.post(
            f"https://api.agentmail.to/v0/inboxes/{_AGENTMAIL_INBOX}/messages/send",
            headers={"Authorization": f"Bearer {_AGENTMAIL_API_KEY}", "Content-Type": "application/json"},
            json={"to": [to_email], "subject": subject, "text": body_text},
            timeout=10,
        )
    except Exception:
        pass


# ── Model catalog ────────────────────────────────────────────────────────────
_CHATBOT_MODELS = {
    'openai': [
        {'id': 'gpt-4o-mini', 'label': 'GPT-4o Mini', 'tier': 'fast'},
        {'id': 'gpt-4o', 'label': 'GPT-4o', 'tier': 'balanced'},
        {'id': 'o3-mini', 'label': 'O3 Mini', 'tier': 'reasoning'},
    ],
    'anthropic': [
        {'id': 'claude-haiku-4-5-20251001', 'label': 'Claude Haiku 4.5', 'tier': 'fast'},
        {'id': 'claude-sonnet-4-6', 'label': 'Claude Sonnet 4.6', 'tier': 'balanced'},
        {'id': 'claude-opus-4-6', 'label': 'Claude Opus 4.6', 'tier': 'reasoning'},
    ],
    'google': [
        {'id': 'gemini-2.0-flash-lite', 'label': 'Gemini 2.0 Flash Lite', 'tier': 'fast'},
        {'id': 'gemini-2.0-flash', 'label': 'Gemini 2.0 Flash', 'tier': 'balanced'},
        {'id': 'gemini-2.5-pro', 'label': 'Gemini 2.5 Pro', 'tier': 'reasoning'},
    ],
}

# ── Chatbot Security Layer ───────────────────────────────────────────────────

_SECURITY_ALERT_EMAIL = "nlaaroubi@nyaaa.com"

# Rate limiter: {session_token: [timestamps]}
_chat_rate = _defaultdict(list)
# Threat tracker: {session_token: threat_score}
_chat_threats = _defaultdict(int)

# Prompt injection patterns (case-insensitive)
_INJECTION_PATTERNS = [
    r'ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|rules|prompts)',
    r'you\s+are\s+now\s+a',
    r'pretend\s+(you|to)\s+(are|be)',
    r'act\s+as\s+(if|a)',
    r'disregard\s+(your|all|the)',
    r'new\s+instructions?\s*:',
    r'system\s*:\s*',
    r'<\s*system\s*>',
    r'override\s+(your|safety|rules|mode)',
    r'jailbreak',
    r'DAN\s+mode',
    r'developer\s+mode',
    r'(do\s+)?anything\s+now',
    r'bypass\s+(filter|safety|restriction|rule)',
]
_INJECTION_RX = _re.compile('|'.join(_INJECTION_PATTERNS), _re.IGNORECASE)

# Exfiltration / off-topic patterns
_BLOCKED_KEYWORDS = [
    r'\b(export|download|dump|extract|csv|excel|spreadsheet)\b',
    r'\b(all\s+members?|all\s+customers?|full\s+list|everything)\b',
    r'\bsocket\b', r'\bwebsocket\b', r'\bbackend\b', r'\bserver\b', r'\bapi\s*key\b',
    r'\b(ssh|shell|terminal|bash|cmd|exec|eval|subprocess)\b',
    r'\b(password|credential|secret|token)\b',
    r'\b(delete|drop|truncate|update\s+table|alter\s+table)\b',
    r'\b(SELECT\s+\*?\s+FROM|INSERT\s+INTO|DELETE\s+FROM)\b',
    r'\b(database|schema|migration|sql\s+inject)\b',
]
_BLOCKED_RX = _re.compile('|'.join(_BLOCKED_KEYWORDS), _re.IGNORECASE)

# Historical request patterns
_HISTORICAL_PATTERNS = [
    r'\b(last\s+(week|month|year|quarter)|previous\s+(week|month|year))\b',
    r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\b',
    r'\b(20\d{2}[-/]\d{1,2}|Q[1-4]\s*20\d{2})\b',
    r'\b(historical|history|trend|over\s+time|past\s+\d+\s+(days?|weeks?|months?))\b',
]
_HISTORICAL_RX = _re.compile('|'.join(_HISTORICAL_PATTERNS), _re.IGNORECASE)

# Email pattern
_EMAIL_RX = _re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# Off-topic detection: must mention at least one FSL-related term
_FSL_TERMS = _re.compile(
    r'\b(garage|territor|driver|sas?\b|service\s*appointment|dispatch|queue|pta|ata|sla|'
    r'response\s*time|score|grade|metric|calls?|tow|winch|battery|lockout|flat|'
    r'fleet|towbook|contractor|member|roadside|fsl|field\s*service|'
    r'schedule|forecast|matrix|command\s*center|accept|decline|'
    r'work\s*type|skill|resource|shift|appointment|zone|cascade|'
    r'open|assigned|completed|canceled|status|today|yesterday|'
    r'list|show|count|average|total|top|worst|best|summary|overview|ops|'
    r'over\s*cap|capacity|gps|closest|utiliz|active|breach|urgent|wait|'
    r'how\s+(is|does|do|are|many)|what\s+(is|does|are)|explain|calculate|mean|'
    r'give\s+me|tell\s+me|quick|right\s+now)',
    _re.IGNORECASE
)


def _get_session_from_request(request) -> str:
    """Extract session token from request cookie."""
    cookie = request.cookies.get("fslapp_auth", "")
    payload = _verify_cookie(cookie) if cookie else None
    return payload or "anonymous"


def _get_username_from_request(request) -> str:
    """Extract username from request."""
    cookie = request.cookies.get("fslapp_auth", "")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        return payload.split(":")[0]
    return "anonymous"


def _check_rate_limit(session: str) -> bool:
    """Returns True if rate limited (too many requests)."""
    import time
    now = time.time()
    window = [t for t in _chat_rate[session] if now - t < 60]
    _chat_rate[session] = window
    if len(window) >= 10:  # max 10 per minute
        return True
    _chat_rate[session].append(now)
    return False


def _security_scan(question: str, history: list, session: str) -> dict:
    """
    Scan question for threats. Returns:
    {'ok': True} or {'ok': False, 'level': 'low|medium|critical', 'reason': str}
    """
    q = question.strip()

    # 1. Prompt injection -> CRITICAL (logout + email)
    if _INJECTION_RX.search(q):
        return {'ok': False, 'level': 'critical', 'reason': 'Prompt injection attempt detected'}

    # Also scan conversation history for injection in accumulated context
    for h in (history or [])[-5:]:
        if h.get('role') == 'user' and _INJECTION_RX.search(h.get('content', '')):
            return {'ok': False, 'level': 'critical', 'reason': 'Prompt injection in conversation history'}

    # 2. Dangerous keywords only (SQL injection, backend probing, credential harvesting) -> MEDIUM
    _DANGEROUS_RX = _re.compile(
        r'\b(SELECT\s+\*?\s+FROM|INSERT\s+INTO|DELETE\s+FROM|DROP\s+TABLE|ALTER\s+TABLE)\b|'
        r'\b(ssh|shell|bash|exec|eval|subprocess)\b|'
        r'\b(password|credential|secret|api\s*key|token)\b|'
        r'\b(export|download|dump|csv|excel|spreadsheet)\b.*\b(all|everything|full)\b',
        _re.IGNORECASE
    )
    dangerous_match = _DANGEROUS_RX.search(q)
    if dangerous_match:
        return {'ok': False, 'level': 'medium', 'reason': f'That type of request is not supported.'}

    # 3. Email addresses in question -> MEDIUM
    if _EMAIL_RX.search(q):
        return {'ok': False, 'level': 'medium', 'reason': 'Email addresses not allowed in questions'}

    # Everything else -> let the LLM handle it. The system prompt already tells it to:
    # - Only answer FSL operations questions
    # - Redirect historical requests to Performance/Scorecard pages
    # - Refuse off-topic questions gracefully

    # 6. Suspicious velocity — cumulative threat score
    _chat_threats[session] += 0  # no increment for clean question
    if _chat_threats[session] >= 5:
        return {'ok': False, 'level': 'critical', 'reason': 'Too many suspicious requests in this session'}

    return {'ok': True}


def _increment_threat(session: str, level: str):
    """Increase threat score based on severity."""
    if level == 'critical':
        _chat_threats[session] += 5
    elif level == 'medium':
        _chat_threats[session] += 2
    elif level == 'low':
        _chat_threats[session] += 1


def _send_security_alert(username: str, question: str, reason: str, level: str):
    """Fire-and-forget email alert to admin on critical threats."""
    subject = f"[FSL SECURITY ALERT] {level.upper()} — chatbot threat from {username}"
    body = (
        f"Security alert from FSL App chatbot.\n\n"
        f"User: {username}\n"
        f"Threat level: {level}\n"
        f"Reason: {reason}\n"
        f"Question: {question[:500]}\n"
        f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        f"Action taken: {'Session terminated — user logged out' if level == 'critical' else 'Request blocked'}"
    )
    _send_issue_email(_SECURITY_ALERT_EMAIL, subject, body)


def _force_logout(request, response):
    """Destroy user session and clear cookie."""
    cookie = request.cookies.get("fslapp_auth", "")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        parts = payload.split(":")
        if len(parts) > 2:
            users.destroy_session(parts[2])
    response.delete_cookie("fslapp_auth")


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/chatbot/status")
def chatbot_status():
    """Check if chatbot is enabled (admin toggle + feature flag). Default: off."""
    settings = _load_settings()
    cb = settings.get("chatbot", {})
    feat = settings.get("features", {})
    # Both the AI config toggle AND the feature flag must be on
    enabled = cb.get("enabled", False) and feat.get("chat", True)
    return {"enabled": enabled}


@router.get("/api/chatbot/models")
def chatbot_models():
    """Return available chatbot model catalog."""
    return _CHATBOT_MODELS


@router.post("/api/chat")
def chatbot_ask(request: Request, response: Response, body: dict = None):
    """Security-hardened FSL operations chatbot with live data injection."""
    if body is None:
        body = {}
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
    if len(question) > 2000:
        raise HTTPException(status_code=400, detail="Question too long (max 2000 characters)")
    history = body.get("history", [])

    session = _get_session_from_request(request)
    username = _get_username_from_request(request)

    # ── Layer 1: Rate limit ──
    if _check_rate_limit(session):
        raise HTTPException(status_code=429, detail="Too many questions. Please wait a moment.")

    # ── Layer 2: Security scan ──
    scan = _security_scan(question, history, session)
    if not scan['ok']:
        level = scan['level']
        reason = scan['reason']
        _increment_threat(session, level)

        if level == 'critical':
            # LOGOUT + EMAIL ALERT
            _force_logout(request, response)
            _send_security_alert(username, question, reason, level)
            raise HTTPException(status_code=403, detail="security_violation")

        if level == 'medium':
            _send_security_alert(username, question, reason, level)
            raise HTTPException(status_code=400, detail=reason)

        # Low: just return the reason as a friendly message
        return {"answer": reason, "model": "guardrail", "provider": "system", "blocked": True}

    # ── Layer 3: Load AI config (env var takes priority over SQLite settings) ──
    settings = _load_settings()
    cb_settings = settings.get("chatbot", {})
    env_key = os.environ.get('OPENAI_API_KEY', '')
    provider = 'openai' if env_key else cb_settings.get("provider", "")
    api_key = env_key or cb_settings.get("api_key", "")

    if not provider or not api_key:
        raise HTTPException(status_code=400, detail="Chatbot not configured. Go to Admin → AI Assistant to set up a provider and API key.")

    primary_model = cb_settings.get("primary_model", "")
    fallback_model = cb_settings.get("fallback_model", "")
    if not primary_model and "models" in cb_settings:
        old = cb_settings["models"]
        primary_model = old.get("mid") or old.get("high") or old.get("low") or ""
    if not primary_model:
        catalog = _CHATBOT_MODELS.get(provider, [])
        primary_model = catalog[1]["id"] if len(catalog) > 1 else (catalog[0]["id"] if catalog else "")
    if not primary_model:
        raise HTTPException(status_code=400, detail="No model configured. Go to Admin → AI Assistant to select a primary model.")

    # ── Layer 4: Fetch live operational data based on question ──
    live_context = _classify_and_fetch_context(question)

    # ── Layer 5: Build prompt with system rules + dictionary + live data ──
    system_prompt = CHATBOT_SYSTEM_BASE
    if live_context:
        system_prompt += "\n\n--- LIVE OPERATIONAL DATA (today only) ---\n" + live_context
    else:
        system_prompt += "\n\nNo live data was fetched for this question. Answer from the data dictionary or direct the user to the appropriate page."

    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-10:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": question})

    def _call(model_id):
        if provider == "openai":
            return _call_openai(api_key, model_id, messages)
        elif provider == "anthropic":
            return _call_anthropic(api_key, model_id, messages)
        elif provider == "google":
            return _call_google(api_key, model_id, messages)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    # ── Layer 6: Call LLM with fallback ──
    used_model = primary_model
    try:
        answer = _call(primary_model)
    except Exception as primary_err:
        if fallback_model and fallback_model != primary_model:
            try:
                used_model = fallback_model
                answer = _call(fallback_model)
            except Exception as fallback_err:
                detail = str(fallback_err)
                try:
                    detail = fallback_err.response.json().get("error", {}).get("message", str(fallback_err))
                except Exception:
                    pass
                raise HTTPException(status_code=502, detail=f"Both primary and fallback models failed. Last error: {detail}")
        else:
            detail = str(primary_err)
            try:
                detail = primary_err.response.json().get("error", {}).get("message", str(primary_err))
            except Exception:
                pass
            raise HTTPException(status_code=502, detail=f"AI provider error: {detail}")

    # ── Layer 7: Sanitize response ──
    answer = _sanitize_response(answer)

    return {"answer": answer, "model": used_model, "provider": provider}
