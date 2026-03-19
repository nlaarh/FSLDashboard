"""Integration tests — verify all routers register correctly and key endpoints respond."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from main import app
    return TestClient(app)


# ── App loads all routers ────────────────────────────────────────────────────

def test_app_has_routes(client):
    """Verify the app loaded a reasonable number of routes (66+ endpoints)."""
    routes = [r for r in client.app.routes if hasattr(r, 'path') and r.path.startswith('/api/')]
    assert len(routes) >= 60, f"Expected 60+ API routes, got {len(routes)}"


def test_all_expected_prefixes(client):
    """Verify all router prefixes are registered."""
    paths = {r.path for r in client.app.routes if hasattr(r, 'path')}
    expected_prefixes = [
        '/api/auth/', '/api/admin/', '/api/garages', '/api/command-center',
        '/api/ops/', '/api/map/', '/api/dispatch/', '/api/issues',
        '/api/pta-advisor', '/api/chat', '/api/data-quality',
        '/api/matrix/', '/api/onroute', '/api/health',
        '/api/insights/', '/api/features',
    ]
    for prefix in expected_prefixes:
        matches = [p for p in paths if p.startswith(prefix)]
        assert len(matches) > 0, f"No routes found for prefix {prefix}"


# ── Key endpoint smoke tests ────────────────────────────────────────────────

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_features(client):
    r = client.get("/api/features")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)


def test_garages_list(client):
    r = client.get("/api/garages")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0


def test_ops_garages(client):
    r = client.get("/api/ops/garages")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_dispatch_queue(client):
    r = client.get("/api/dispatch/queue")
    assert r.status_code == 200
    data = r.json()
    assert "queue" in data


def test_login_page(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "FleetPulse" in r.text


def test_auth_me_returns_user_or_401(client):
    """In test mode (no WEBSITE_SITE_NAME), auth middleware passes through."""
    r = client.get("/api/auth/me")
    # Local dev mode: no auth required, but no cookie → returns 401 or user info
    assert r.status_code in (200, 401)


def test_admin_verify_requires_pin(client):
    r = client.post("/api/admin/verify")
    # No PIN header → should fail
    assert r.status_code in (401, 403, 422)


def test_invalid_insights_category(client):
    r = client.get("/api/insights/invalid_category")
    assert r.status_code == 400


def test_chatbot_models(client):
    r = client.get("/api/chatbot/models")
    assert r.status_code == 200


def test_map_grids(client):
    r = client.get("/api/map/grids")
    assert r.status_code == 200
    data = r.json()
    assert "features" in data
