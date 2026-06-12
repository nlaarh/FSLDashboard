"""System health admin endpoint tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    from routers import admin, system_health

    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=sk-test-secret-value\n"
        "GOOGLE_MAPS_API_KEY=maps-secret-value\n"
        "SF_USERNAME=sf-user@example.com\n"
    )

    monkeypatch.setattr(admin, "_ADMIN_PIN", "1234")
    monkeypatch.setattr(system_health, "_env_file_paths", lambda: [env_file])
    monkeypatch.setattr(system_health.cache, "stats", lambda: {
        "l1_total": 2,
        "l1_alive": 2,
        "l1_stale": 0,
        "l1_pending": 0,
        "l2_total": 10,
        "l2_alive": 8,
        "l2_stale": 2,
    })
    monkeypatch.setattr(system_health.db_adapter, "health_check", lambda: {
        "primary": "postgres",
        "postgres": True,
    })
    monkeypatch.setattr(system_health, "sf_stats", lambda: {
        "total_calls": 7,
        "errors": 0,
        "breaker_open": False,
        "calls_last_60s": 0,
        "rate_limit": 60,
    })
    monkeypatch.setattr(system_health, "sf_recent_slow_queries", lambda: [
        {
            "kind": "SOQL",
            "seconds": 7.2,
            "detail": "SELECT COUNT(Id) cnt FROM ServiceAppointment",
            "recorded_at": "2026-06-05T18:00:00Z",
        }
    ])
    monkeypatch.setattr(system_health, "_backup_recovery_report", lambda: {
        "configured": True,
        "items": [{
            "id": "db-backups/fslapp_20260523_120000.json",
            "file_name": "fslapp_20260523_120000.json",
            "source": "Azure Blob",
            "size_bytes": 1024,
            "last_modified": "2026-05-23T12:00:00+00:00",
            "open_url": "https://example.blob.core.windows.net/optimizer-files/db-backups/fslapp.json",
            "recoverable": True,
        }],
    })

    app = FastAPI()
    app.include_router(system_health.router)
    return TestClient(app)


def test_system_health_requires_admin_pin(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.get("/api/admin/system/health")

    assert response.status_code == 403


def test_system_health_returns_expected_shape(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.get(
        "/api/admin/system/health",
        headers={"X-Admin-Pin": "1234"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["quota_safe"] is True
    assert data["status"] in {"healthy", "degraded", "unhealthy"}
    assert data["services"]["salesforce"]["details"]["quota_safe"].startswith("No live ping")
    assert data["services"]["salesforce_diagnostics"]["status"] == "degraded"
    assert data["services"]["salesforce_diagnostics"]["details"]["slow_queries"][0]["seconds"] == 7.2
    assert data["services"]["salesforce_diagnostics"]["details"]["query_plan_checks"][0]["name"] == "data-quality-total"
    assert data["services"]["google_maps"]["details"]["quota_safe"].startswith("No live ping")
    assert data["services"]["openai"]["details"]["quota_safe"].startswith("No live ping")
    assert data["services"]["salesforce"]["host_link"].startswith("https://")
    assert data["services"]["openai"]["logs"]
    assert data["logs"]
    assert data["backup_recovery"]["items"][0]["file_name"].startswith("fslapp_")
    assert data["backup_recovery"]["items"][0]["open_url"].startswith("https://")
    assert "environment" in data


def test_system_health_masks_env_values(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.get(
        "/api/admin/system/health",
        headers={"X-Admin-Pin": "1234"},
    )

    variables = {item["name"]: item for item in response.json()["environment"]["variables"]}
    assert variables["OPENAI_API_KEY"]["configured"] is True
    assert variables["OPENAI_API_KEY"]["masked"] != "sk-test-secret-value"
    assert "secret" not in variables["GOOGLE_MAPS_API_KEY"]["masked"]


def test_system_health_ping_is_quota_safe(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/admin/system/health/ping/openai",
        headers={"X-Admin-Pin": "1234"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "openai"
    assert data["live_ping"] is False
    assert "external live ping disabled" in data["message"]
