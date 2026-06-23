"""Admin-only Salesforce diagnostics endpoint tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(monkeypatch):
    from routers import admin, salesforce_diagnostics

    monkeypatch.setattr(admin, "_ADMIN_PIN", "1234")
    app = FastAPI()
    app.include_router(salesforce_diagnostics.router)
    return TestClient(app)


def test_query_plan_requires_admin_pin(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/api/admin/salesforce/query-plan/data-quality-total")

    assert response.status_code == 403


def test_query_plan_uses_named_read_only_soql(monkeypatch):
    from routers import salesforce_diagnostics

    captured = {}

    def fake_explain(soql):
        captured["soql"] = soql
        return {"plans": [{"cardinality": 100, "leadingOperationType": "Index"}]}

    monkeypatch.setattr(salesforce_diagnostics, "sf_query_explain", fake_explain)
    client = _client(monkeypatch)

    response = client.get(
        "/api/admin/salesforce/query-plan/data-quality-total",
        headers={"X-Admin-Pin": "1234"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "data-quality-total"
    assert "SELECT COUNT(Id) cnt" in captured["soql"]
    assert "FROM ServiceAppointment" in captured["soql"]
    assert "WorkType.Name != 'Tow Drop-Off'" in captured["soql"]
    assert data["plan"]["plans"][0]["leadingOperationType"] == "Index"


def test_query_plan_rejects_unknown_named_query(monkeypatch):
    client = _client(monkeypatch)

    response = client.get(
        "/api/admin/salesforce/query-plan/not-real",
        headers={"X-Admin-Pin": "1234"},
    )

    assert response.status_code == 404
