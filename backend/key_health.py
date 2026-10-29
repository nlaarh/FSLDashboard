"""Key health — does each outside key (password / API key) still work?

Every hour one worker tests each key with a free call, saves the result where every worker can read it,
and emails the admins when a key breaks (and again when it works again). Admins see the result on
Admin → System Health → Keys, with a direct link to that key in the Azure Key Vault.

Salesforce is never called just to test: we use the result of the app's own last Salesforce login.
Alert emails go out only from the live site (fslapp-nyaaa), so the test site never doubles them.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

import cache

log = logging.getLogger('key_health')

VAULT = "kv-fslapp-nyaaa"
_PORTAL = "https://portal.azure.com/#@nyaaa.com"
_RG = "/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers"
VAULT_SECRETS_URL = f"{_PORTAL}{_RG}/Microsoft.KeyVault/vaults/{VAULT}/secrets"
LIVE_SITE = "fslapp-nyaaa"
RESTART_URL = f"{_PORTAL}{_RG}/Microsoft.Web/sites/{LIVE_SITE}/overview"

CHECK_EVERY_S = 3600
_STATE_KEY = "key_health:state"
_TIMEOUT = 10


def vault_name(env: str) -> str:
    """Vault secret names can't hold '_', so SF_PASSWORD lives in the vault as SF-PASSWORD."""
    return env.replace("_", "-")


def secret_url(env: str) -> str:
    return f"{_PORTAL}/asset/Microsoft_Azure_KeyVault/Secret/https://{VAULT}.vault.azure.net/secrets/{vault_name(env)}"


# ── Checks: each returns (ok, message). Only free, read-only calls. ─────────────

def _http_ok(r: requests.Response, what: str) -> tuple[bool, str]:
    if r.status_code in (401, 403):
        return False, f"{what} rejected the key (HTTP {r.status_code}) — it is wrong, expired or revoked"
    if r.status_code >= 400:
        return False, f"{what} answered HTTP {r.status_code}"
    return True, f"{what} accepted the key"


def _check_salesforce(env):
    import sf_client
    last = dict(sf_client._last_login)
    if not last:
        return None, "No Salesforce login yet since the app started"
    when = datetime.fromtimestamp(last["at"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if last["ok"]:
        return True, f"Last Salesforce login worked ({when})"
    return False, f"Salesforce login failed at {when}: {last['error']} — the password or security token may have expired"


def _check_microsoft(env):
    r = requests.post(f"https://login.microsoftonline.com/{env['SSO_TenantId']}/oauth2/v2.0/token", data={
        "client_id": env["SSO_UserName"], "client_secret": env["SSO_API"],
        "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}, timeout=_TIMEOUT)
    if "access_token" in r.json():
        return True, "Microsoft accepted the sign-in app password"
    err = r.json().get("error_description", "")[:160]
    if "AADSTS7000222" in err:
        return False, "The Microsoft sign-in app password has EXPIRED — make a new one in Entra ID and put it in the vault"
    return False, f"Microsoft rejected the sign-in settings: {err}"


def _check_google_maps(env):
    # An empty address is not billed: a good key answers INVALID_REQUEST, a bad one REQUEST_DENIED.
    r = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
                     params={"address": "", "key": env["GOOGLE_MAPS_API_KEY"]}, timeout=_TIMEOUT)
    status = r.json().get("status")
    if status == "REQUEST_DENIED":
        return False, f"Google rejected the Maps key: {r.json().get('error_message', '')[:160]}"
    return True, "Google accepted the Maps key"


def _check_openai(env):
    return _http_ok(requests.get("https://api.openai.com/v1/models",
                                 headers={"Authorization": f"Bearer {env['OPENAI_API_KEY']}"}, timeout=_TIMEOUT), "OpenAI")


def _check_anthropic(env):
    return _http_ok(requests.get("https://api.anthropic.com/v1/models", headers={
        "x-api-key": env["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}, timeout=_TIMEOUT), "Anthropic")


def _check_google_ai(env):
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                     params={"key": env["GOOGLE_AI_API_KEY"], "pageSize": 1}, timeout=_TIMEOUT)
    if r.status_code == 400:  # Google answers 400 API_KEY_INVALID for a bad key
        return False, "Google AI rejected the key"
    return _http_ok(r, "Google AI")


def _check_github(env):
    return _http_ok(requests.get("https://api.github.com/rate_limit",
                                 headers={"Authorization": f"Bearer {env['GITHUB_TOKEN']}"}, timeout=_TIMEOUT), "GitHub")


def _check_agentmail(env):
    r = requests.get(f"https://api.agentmail.to/v0/inboxes/{env['AGENTMAIL_INBOX']}",
                     headers={"Authorization": f"Bearer {env['AGENTMAIL_API_KEY']}"}, timeout=_TIMEOUT)
    if r.status_code == 404:
        return False, (f"The key works, but the sending mailbox {env['AGENTMAIL_INBOX']} does not exist in that "
                       "AgentMail account — emails cannot be sent")
    return _http_ok(r, "AgentMail")


# id, name, what breaks when it fails, env vars (all must be set), check, System Health node it belongs to
KEYS = [
    ("salesforce", "Salesforce login", "All Salesforce data stops refreshing",
     ["SF_CONSUMER_KEY", "SF_CONSUMER_SECRET", "SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN"], _check_salesforce, "salesforce"),
    ("microsoft_sso", "Microsoft sign-in", "The 'Sign in with Microsoft' button stops working",
     ["SSO_TenantId", "SSO_UserName", "SSO_API"], _check_microsoft, None),
    ("google_maps", "Google Maps", "Maps and drive-time estimates stop working",
     ["GOOGLE_MAPS_API_KEY"], _check_google_maps, "google_maps"),
    ("openai", "OpenAI", "AI features that use OpenAI stop working", ["OPENAI_API_KEY"], _check_openai, "openai"),
    ("anthropic", "Anthropic (Claude)", "AI features that use Claude stop working", ["ANTHROPIC_API_KEY"], _check_anthropic, "openai"),
    ("google_ai", "Google AI (Gemini)", "AI features that use Gemini stop working", ["GOOGLE_AI_API_KEY"], _check_google_ai, "openai"),
    ("github", "GitHub", "In-app issue reports stop reaching GitHub", ["GITHUB_TOKEN"], _check_github, "github"),
    ("agentmail", "Email (AgentMail)", "Password-reset and alert emails stop sending",
     ["AGENTMAIL_API_KEY", "AGENTMAIL_INBOX"], _check_agentmail, "agentmail"),
]


def _check_one(key_id, label, impact, envs, fn, node) -> dict:
    values = {e: os.environ.get(e, "").strip() for e in envs}
    row = {"id": key_id, "label": label, "impact": impact, "node": node,
           "checked_at": datetime.now(timezone.utc).isoformat(),
           "secrets": [{"env": e, "vault_name": vault_name(e), "url": secret_url(e), "set": bool(values[e])} for e in envs]}
    unreadable = [e for e, v in values.items() if v.startswith("@Microsoft.KeyVault(")]
    missing = [e for e, v in values.items() if not v]
    if unreadable:
        # Azure hands the app the raw reference text when it cannot read the vault secret.
        return {**row, "status": "broken", "message": f"The site cannot read {', '.join(unreadable)} from the Key Vault "
                                                      "(secret missing, disabled, or the site lost vault access)"}
    if missing:
        return {**row, "status": "missing", "message": f"Not set on this site: {', '.join(missing)}"}
    try:
        ok, message = fn(values)
    except Exception as exc:
        ok, message = None, f"Could not reach the service to test the key: {str(exc)[:160]}"
    return {**row, "status": {True: "ok", False: "broken", None: "unknown"}[ok], "message": message}


def run_checks() -> list[dict]:
    return [_check_one(*k) for k in KEYS]


def last_results() -> dict:
    return cache.disk_get_stale(_STATE_KEY) or {"results": [], "checked_at": None}


def broken_nodes() -> dict[str, str]:
    """System Health node → message, for nodes whose key is broken (turns the diagram node red)."""
    out = {}
    for r in last_results().get("results", []):
        if r.get("status") == "broken" and r.get("node"):
            out.setdefault(r["node"], f"{r['label']}: {r['message']}")
    return out


# ── Alerts ─────────────────────────────────────────────────────────────────────

def _admin_emails() -> list[str]:
    import users
    return sorted({u["email"] for u in users.list_users()
                   if u.get("role") == "admin" and u.get("active", True) and u.get("email")})


def _send(to: list[str], subject: str, text: str) -> bool:
    api_key, inbox = os.environ.get("AGENTMAIL_API_KEY", ""), os.environ.get("AGENTMAIL_INBOX", "fslnyaaa@agentmail.to")
    if not api_key or not to:
        log.warning("key alert not sent: no AgentMail key or no admin emails")
        return False
    r = requests.post(f"https://api.agentmail.to/v0/inboxes/{inbox}/messages/send",
                      headers={"Authorization": f"Bearer {api_key}"},
                      json={"to": to, "subject": subject, "text": text}, timeout=_TIMEOUT)
    if r.status_code >= 400:
        log.warning(f"key alert email failed: HTTP {r.status_code} {r.text[:200]}")
    return r.status_code < 400


def alert_text(broke: list[dict], fixed: list[dict]) -> tuple[str, str]:
    lines = []
    for r in broke:
        lines += [f"BROKEN: {r['label']}", f"  What happens: {r['impact']}", f"  Why: {r['message']}",
                  "  Fix it in the Key Vault:"] + [f"    {s['vault_name']}: {s['url']}" for s in r["secrets"]] + [""]
    for r in fixed:
        lines += [f"WORKING AGAIN: {r['label']}", ""]
    if broke:
        lines += ["After saving a new value in the vault, restart the site so it picks it up:", f"  {RESTART_URL}", "",
                  f"All keys: {VAULT_SECRETS_URL}", "Status page: FleetPulse → Admin → System Health → Keys"]
    names = ", ".join(r["label"] for r in broke) if broke else ", ".join(r["label"] for r in fixed)
    subject = f"FleetPulse: key not working — {names}" if broke else f"FleetPulse: key working again — {names}"
    return subject, "\n".join(lines)


def _alerts_on() -> bool:
    return os.environ.get("WEBSITE_SITE_NAME") == LIVE_SITE or os.environ.get("KEY_ALERTS", "").lower() == "on"


def check_and_alert() -> dict:
    """Test every key, save the result, email admins about anything that changed between working and broken."""
    previous = {r["id"]: r["status"] for r in last_results().get("results", [])}
    results = run_checks()
    broke = [r for r in results if r["status"] == "broken" and previous.get(r["id"]) != "broken"]
    fixed = [r for r in results if r["status"] == "ok" and previous.get(r["id"]) == "broken"]
    state = {"results": results, "checked_at": datetime.now(timezone.utc).isoformat(), "site": os.environ.get("WEBSITE_SITE_NAME", "local")}
    cache.disk_put(_STATE_KEY, state, ttl=7 * 86400)
    if (broke or fixed) and _alerts_on():
        subject, text = alert_text(broke, fixed)
        try:
            _send(_admin_emails(), subject, text)
            log.info(f"key alert sent: {subject}")
        except Exception as exc:
            log.warning(f"key alert failed: {exc}")
    return state


def run_forever():
    time.sleep(120)  # let the app finish starting (and log in to Salesforce) first
    while True:
        # The lock is left to expire, so only one worker checks per hour.
        if cache.fs_lock_acquire("key_health", max_age=CHECK_EVERY_S - 300):
            try:
                check_and_alert()
            except Exception as exc:
                log.warning(f"key health pass failed: {exc}")
        time.sleep(300)


def start():
    threading.Thread(target=run_forever, daemon=True, name="key-health").start()
