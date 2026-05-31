"""PIN-protected system health for the admin panel.

This endpoint is intentionally read-only and quota-safe. It does not ping
Salesforce, Google Maps, OpenAI, GitHub, or AgentMail; those services are
reported from runtime config and existing in-process stats only.
"""

from __future__ import annotations

import os
import platform
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException, Request

import cache
import db_adapter
from routers.admin import _check_pin, _start_time
from sf_client import get_stats as sf_stats

router = APIRouter()

CONFIG_KEYS = [
    "ADMIN_PIN",
    "SF_TOKEN_URL",
    "SF_CONSUMER_KEY",
    "SF_CONSUMER_SECRET",
    "SF_USERNAME",
    "SF_PASSWORD",
    "SF_SECURITY_TOKEN",
    "GOOGLE_MAPS_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_AI_API_KEY",
    "GITHUB_TOKEN",
    "AGENTMAIL_API_KEY",
    "AGENTMAIL_INBOX",
    "FSLAPP_PG_HOST",
    "FSLAPP_PG_DATABASE",
    "FSLAPP_PG_USER",
    "FSLAPP_PG_DR_HOST",
    "FSLAPP_PG_SCHEMA",
    "DB_PRIMARY",
]

SERVICE_KEY_GROUPS = {
    "salesforce": ["SF_TOKEN_URL", "SF_CONSUMER_KEY", "SF_CONSUMER_SECRET", "SF_USERNAME", "SF_PASSWORD"],
    "google_maps": ["GOOGLE_MAPS_API_KEY"],
    "openai": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_AI_API_KEY"],
    "github": ["GITHUB_TOKEN"],
    "agentmail": ["AGENTMAIL_API_KEY", "AGENTMAIL_INBOX"],
    "postgres": ["FSLAPP_PG_HOST", "FSLAPP_PG_DATABASE", "FSLAPP_PG_USER"],
    "dr_postgres": ["FSLAPP_PG_DR_HOST"],
}

_AZ_BASE = "https://portal.azure.com/#@nyaaa.com/resource/subscriptions/e287db16-b6ae-415e-bd52-41c8ec5a8f08/resourceGroups/rg-nlaaroubi-sbx-eus2-001/providers"
_AZ_PG   = f"{_AZ_BASE}/Microsoft.DBforPostgreSQL/flexibleServers"

_AZ_SITES = f"{_AZ_BASE}/Microsoft.Web/sites"

SERVICE_LINKS = {
    "app":           "https://fslapp-nyaaa.azurewebsites.net",
    "app_dr":        "https://fslapp-nyaaa-dr.azurewebsites.net",
    "salespulse":    "https://salespulse-nyaaa.azurewebsites.net",
    "salespulse_dr": "https://salespulse-nyaaa-dr.azurewebsites.net",
    "azure":         f"{_AZ_SITES}/fslapp-nyaaa/overview",
    "postgres":      f"{_AZ_PG}/fslapp-pg/overview",
    "dr_postgres":   f"{_AZ_PG}/fslapp-pg-dr/overview",
    "salesforce":    "https://aaawcny.lightning.force.com",
    "google_maps":   "https://console.cloud.google.com/apis/library",
    "openai":        "https://platform.openai.com/usage",
    "github":        "https://github.com/nlaarh/FSLDashboard",
    "agentmail":     "https://agentmail.to/",
    "cache":         "",
    "duckdb":        "",
}


def _env_file_paths() -> list[Path]:
    backend_dir = Path(__file__).resolve().parents[1]
    app_root = backend_dir.parent
    return [
        app_root / ".env",
        backend_dir / ".env",
        app_root.parent / ".env",
    ]


def _mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    if len(value) <= 8:
        return f"{value[:1]}***{value[-1:]}"
    return f"{value[:2]}***{value[-4:]}"


def _safe_call(fn, fallback: dict) -> dict:
    try:
        return fn()
    except Exception as exc:
        result = dict(fallback)
        result["error"] = str(exc)
        return result


def _read_env_files() -> tuple[list[dict], dict[str, list[str]], dict[str, str]]:
    files = []
    sources: dict[str, list[str]] = {}
    file_values: dict[str, str] = {}
    for path in _env_file_paths():
        exists = path.exists()
        keys = []
        if exists:
            values = dotenv_values(path)
            keys = sorted(k for k, v in values.items() if k and v is not None)
            for key in keys:
                sources.setdefault(key, []).append(str(path))
                if key not in file_values:
                    file_values[key] = str(values.get(key) or "")
        files.append({"path": str(path), "exists": exists, "keys_count": len(keys), "keys": keys})
    return files, sources, file_values


def _env_report() -> dict:
    files, sources, file_values = _read_env_files()
    variables = []
    for key in CONFIG_KEYS:
        runtime_value = os.environ.get(key)
        file_value = file_values.get(key)
        configured = bool(runtime_value or file_value)
        variables.append({
            "name": key,
            "configured": configured,
            "runtime": bool(runtime_value),
            "source_files": sources.get(key, []),
            "masked": _mask(runtime_value or file_value),
        })
    return {"files": files, "variables": variables}


def _config_value(key: str) -> str:
    runtime_value = os.environ.get(key)
    if runtime_value:
        return runtime_value
    for path in _env_file_paths():
        if path.exists():
            value = dotenv_values(path).get(key)
            if value:
                return str(value)
    return ""


def _config_status(keys: list[str], require_all: bool = True) -> tuple[str, str]:
    configured = [key for key in keys if _config_value(key)]
    if not require_all:
        if configured:
            return "healthy", f"{len(configured)} provider key(s) configured"
        return "unhealthy", "No provider configuration found"
    if len(configured) == len(keys):
        return "healthy", "Required configuration is present"
    if configured:
        missing = sorted(set(keys) - set(configured))
        return "degraded", f"Missing: {', '.join(missing)}"
    return "unhealthy", "No required configuration found"


def _log(level: str, message: str) -> str:
    return f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {level} - {message}"


def _service(label: str, status: str, summary: str, details: dict | None = None, key: str = "") -> dict:
    details = details or {}
    logs = [_log("CONFIG CHECK", f"{summary} | live_ping=false")]
    return {
        "label": label,
        "name": label.upper(),
        "status": status,
        "summary": summary,
        "host_link": SERVICE_LINKS.get(key, ""),
        "live_ping": False,
        "logs": logs,
        "details": details,
        **details,
    }


def _app_service() -> dict:
    uptime_seconds = round(time.time() - _start_time)
    return _service("Application", "healthy", "FastAPI process is running", {
        "uptime_seconds": uptime_seconds,
        "pid": os.getpid(),
        "python": platform.python_version(),
        "host": socket.gethostname(),
        "server_url": SERVICE_LINKS["app"],
    }, key="app")


def _azure_service() -> dict:
    site = os.environ.get("WEBSITE_SITE_NAME")
    if not site:
        return _service("Azure App Service", "degraded", "Running outside Azure App Service", {
            "environment": "local",
            "server_url": SERVICE_LINKS["azure"],
        }, key="azure")
    return _service("Azure App Service", "healthy", f"Running as {site}", {
        "site_name": site,
        "instance_id": os.environ.get("WEBSITE_INSTANCE_ID", "")[:12],
        "region": os.environ.get("REGION_NAME", ""),
        "server_url": SERVICE_LINKS["azure"],
    }, key="azure")


def _app_dr_service() -> dict:
    site = os.environ.get("WEBSITE_SITE_NAME")
    if site == "fslapp-nyaaa-dr":
        return _service("FleetPulse DR App", "healthy", f"Running as DR instance: {site}", {
            "site_name": site,
            "region": "West US 2",
            "server_url": SERVICE_LINKS["app_dr"],
        }, key="app_dr")
    return _service("FleetPulse DR App", "degraded", "DR App Service — standby (not active instance)", {
        "region": "West US 2",
        "environment": "standby",
        "server_url": SERVICE_LINKS["app_dr"],
    }, key="app_dr")


def _salespulse_service() -> dict:
    return _service("SalesPulse App", "degraded", "Co-tenant app — shares fslapp-pg (schema: sales)", {
        "region": "West US 2",
        "schema": "sales",
        "server_url": SERVICE_LINKS["salespulse"],
    }, key="salespulse")


def _salespulse_dr_service() -> dict:
    return _service("SalesPulse DR App", "degraded", "SalesPulse DR — standby (not active)", {
        "region": "West US 2",
        "environment": "standby",
        "server_url": SERVICE_LINKS["salespulse_dr"],
    }, key="salespulse_dr")


def _cache_service() -> dict:
    stats = _safe_call(cache.stats, {"l1_total": 0, "l2_total": 0, "l1_pending": 0})
    pending = int(stats.get("l1_pending") or 0)
    status = "degraded" if pending > 10 else "healthy"
    return _service("Shared Cache", status, "L1 memory and L2 database cache stats", stats, key="cache")


def _postgres_service() -> dict:
    health = _safe_call(db_adapter.health_check, {"primary": os.environ.get("DB_PRIMARY", "postgres"), "postgres": False})
    ok = bool(health.get("postgres"))
    status = "healthy" if ok else "unhealthy"
    summary = "PostgreSQL connection succeeded" if ok else "PostgreSQL connection failed"
    pg_host = _config_value("FSLAPP_PG_HOST")
    short_host = pg_host.replace(".postgres.database.azure.com", "") if pg_host else "fslapp-pg"
    return _service("PostgreSQL", status, summary, {
        **health,
        "host": short_host,
        "region": "East US",
        "server_url": SERVICE_LINKS["postgres"],
    }, key="postgres")


def _dr_postgres_service() -> dict:
    dr_host = _config_value("FSLAPP_PG_DR_HOST") or "fslapp-pg-dr.postgres.database.azure.com"
    short_host = dr_host.replace(".postgres.database.azure.com", "")
    base_details = {"host": short_host, "region": "East US 2", "server_url": SERVICE_LINKS["dr_postgres"]}
    if not _config_value("FSLAPP_PG_DR_HOST"):
        return _service("DR PostgreSQL", "degraded",
                        "FSLAPP_PG_DR_HOST not configured",
                        base_details, key="dr_postgres")
    import time as _time
    started = _time.perf_counter()
    try:
        import psycopg
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        token_obj = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
        token = token_obj.token
        pg_user = _config_value("FSLAPP_PG_USER") or "fslapp-nyaaa"
        conn = psycopg.connect(
            host=dr_host, dbname="fslapp",
            user=pg_user,
            password=token, sslmode="require", connect_timeout=5
        )
        conn.close()
        latency = round((_time.perf_counter() - started) * 1000, 1)
        return _service("DR PostgreSQL", "healthy",
                        f"DR DB reachable — {latency}ms",
                        {**base_details, "latency_ms": latency}, key="dr_postgres")
    except Exception as exc:
        return _service("DR PostgreSQL", "unhealthy",
                        f"DR DB unreachable: {exc}",
                        {**base_details, "error": str(exc)}, key="dr_postgres")


def _duckdb_service() -> dict:
    db_path = Path(os.path.expanduser("~/.fslapp/fsl_data.duckdb"))
    details = {
        "path": str(db_path),
        "exists": db_path.exists(),
        "size_mb": round(db_path.stat().st_size / 1024 / 1024, 2) if db_path.exists() else 0,
    }
    status = "healthy" if details["exists"] else "degraded"
    summary = "DuckDB cache file exists" if details["exists"] else "DuckDB cache file not created yet"
    return _service("DuckDB Local Cache", status, summary, details, key="duckdb")


def _salesforce_service() -> dict:
    config_status, config_summary = _config_status(SERVICE_KEY_GROUPS["salesforce"])
    stats = _safe_call(sf_stats, {})
    status = "unhealthy" if stats.get("breaker_open") else config_status
    summary = "Circuit breaker is open; serving cached data" if stats.get("breaker_open") else config_summary
    return _service("Salesforce", status, summary, {
        **stats,
        "quota_safe": "No live ping; existing client stats only",
        "server_url": SERVICE_LINKS["salesforce"],
    }, key="salesforce")


def _configured_service(key: str, label: str, require_all: bool = True) -> dict:
    status, summary = _config_status(SERVICE_KEY_GROUPS[key], require_all=require_all)
    return _service(label, status, summary, {
        "quota_safe": "No live ping; configuration presence only",
        "server_url": SERVICE_LINKS.get(key, ""),
        "keys": [
            {"name": name, "configured": bool(_config_value(name))}
            for name in SERVICE_KEY_GROUPS[key]
        ],
    }, key=key)


_AGGREGATE_EXCLUDED = {"salespulse", "salespulse_dr"}


def _aggregate_status(services: dict[str, dict]) -> str:
    statuses = [svc.get("status") for key, svc in services.items() if key not in _AGGREGATE_EXCLUDED]
    if "unhealthy" in statuses:
        return "unhealthy"
    if "degraded" in statuses:
        return "degraded"
    return "healthy"


def _backup_recovery_report() -> dict:
    azure = _safe_call(
        lambda: __import__("db_backup").list_backups(),
        {"configured": False, "items": [], "error": "Backup module unavailable"},
    )
    user_info = _safe_call(
        lambda: __import__("user_backup").backup_info(),
        {"postgres": {}, "file": {"ok": False, "exists": False}},
    )
    items = list(azure.get("items") or [])
    file_info = user_info.get("file") or {}
    if file_info.get("ok") and file_info.get("path"):
        items.append({
            "id": file_info["path"],
            "name": "Encrypted user fallback backup",
            "file_name": Path(file_info["path"]).name,
            "source": "Local encrypted file",
            "path": file_info["path"],
            "size_bytes": int(file_info.get("size_bytes") or 0),
            "last_modified": datetime.fromtimestamp(
                Path(file_info["path"]).stat().st_mtime,
                timezone.utc,
            ).isoformat() if Path(file_info["path"]).exists() else "",
            "recoverable": True,
        })
    return {
        "configured": bool(azure.get("configured")) or bool(file_info.get("ok")),
        "azure": azure,
        "user_backup": user_info,
        "items": items,
    }


def _build_services() -> dict[str, dict]:
    return {
        "app": _app_service(),
        "app_dr": _app_dr_service(),
        "salespulse": _salespulse_service(),
        "salespulse_dr": _salespulse_dr_service(),
        "azure": _azure_service(),
        "postgres": _postgres_service(),
        "dr_postgres": _dr_postgres_service(),
        "duckdb": _duckdb_service(),
        "cache": _cache_service(),
        "salesforce": _salesforce_service(),
        "google_maps": _configured_service("google_maps", "Google Maps"),
        "openai": _configured_service("openai", "AI Providers", require_all=False),
        "github": _configured_service("github", "GitHub"),
        "agentmail": _configured_service("agentmail", "AgentMail"),
    }


@router.get("/api/admin/system/health")
def system_health(request: Request):
    """Return quota-safe system health and masked environment configuration."""
    _check_pin(request)
    services = _build_services()
    return {
        "status": _aggregate_status(services),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "quota_safe": True,
        "services": services,
        "logs": [
            _log("OK", "System health queried"),
            _log("OK", "External provider live pings disabled by default"),
        ],
        "backup_recovery": _backup_recovery_report(),
        "environment": _env_report(),
    }


@router.post("/api/admin/system/health/backup")
def trigger_backup(request: Request):
    """Run a Postgres backup now. Writes to Azure Blob if configured, local fallback otherwise."""
    _check_pin(request)
    try:
        import db_backup
        result = db_backup.backup_now()
        return {"ok": True, "result": result, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/admin/system/health/ping/{service_key}")
def ping_system_health(service_key: str, request: Request):
    """Run a manual quota-safe check for one service without external API pings."""
    _check_pin(request)
    services = _build_services()
    service = services.get(service_key)
    if not service:
        raise HTTPException(status_code=404, detail="Unknown system health service")
    return {
        "service": service_key,
        "status": service["status"],
        "live_ping": False,
        "message": "Safe configuration check only; external live ping disabled to protect quota and cost.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "logs": service.get("logs", []),
    }
