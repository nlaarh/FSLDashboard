"""Salesforce Canvas embed sign-in (routers/embed.py)."""

import base64
import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import embed

SECRET = "test-consumer-secret"
USER = {"username": "jdoe", "name": "Jane Doe", "role": "viewer", "email": "jdoe@nyaaa.com",
        "active": True, "department": ""}


def sign(payload: dict, secret: str = SECRET) -> str:
    body = base64.b64encode(json.dumps(payload).encode()).decode()
    sig = base64.b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()).decode()
    return f"{sig}.{body}"


def canvas_request(email="jdoe@nyaaa.com", org="00Dxx0000001gERAAY", params=None):
    return {
        "algorithm": "HMACSHA256", "issuedAt": None, "userId": "005xx000001SyyEAAS",
        "context": {
            "user": {"userId": "005xx000001SyyEAAS", "email": email, "fullName": "Jane Doe"},
            "organization": {"organizationId": org},
            "environment": {"parameters": params or {}},
        },
        "client": {"oauthToken": "redacted", "instanceUrl": "https://example.my.salesforce.com"},
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SF_CANVAS_SECRET", SECRET)
    monkeypatch.delenv("SF_CANVAS_ORG_ID", raising=False)
    monkeypatch.setattr(embed.users, "find_by_email",
                        lambda e: USER if e.lower() == USER["email"] else None)
    monkeypatch.setattr(embed.users, "create_session", lambda *a, **k: "tok123")
    app = FastAPI()
    app.include_router(embed.router)
    return TestClient(app, follow_redirects=False)


def test_valid_request_creates_session_and_partitioned_cookie(client):
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request())})
    assert r.status_code == 303
    assert r.headers["location"] == "/sa-watchlist?embed=1"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("fslapp_auth=")
    for attr in ("HttpOnly", "Secure", "SameSite=None", "Partitioned", "Path=/"):
        assert attr in cookie
    # Same cookie format the password login uses, so the auth middleware accepts it
    from routers.auth import _verify_cookie
    value = cookie.split(";")[0].split("=", 1)[1].strip('"')
    assert _verify_cookie(value) == "jdoe:viewer:tok123"


def test_email_match_is_case_insensitive(client):
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(email="JDoe@NYAAA.com"))})
    assert r.status_code == 303


def test_bad_signature_rejected(client):
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(), secret="wrong")})
    assert r.status_code == 401
    assert "set-cookie" not in r.headers


def test_tampered_payload_rejected(client):
    sig, _ = sign(canvas_request()).split(".", 1)
    forged = base64.b64encode(json.dumps(canvas_request(email="admin@nyaaa.com")).encode()).decode()
    r = client.post("/embed/canvas", data={"signed_request": f"{sig}.{forged}"})
    assert r.status_code == 401


def test_missing_signed_request_rejected(client):
    assert client.post("/embed/canvas", data={}).status_code == 401


def test_unknown_email_gets_no_access(client):
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(email="nobody@nyaaa.com"))})
    assert r.status_code == 403
    assert "No FleetPulse access" in r.text
    assert "set-cookie" not in r.headers


def test_wrong_org_rejected(client, monkeypatch):
    monkeypatch.setenv("SF_CANVAS_ORG_ID", "00Dxx0000009999")
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request())})
    assert r.status_code == 403


def test_matching_org_15_vs_18_chars(client, monkeypatch):
    monkeypatch.setenv("SF_CANVAS_ORG_ID", "00Dxx0000001gER")
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request())})
    assert r.status_code == 303


def test_no_secret_configured(client, monkeypatch):
    monkeypatch.delenv("SF_CANVAS_SECRET")
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request())})
    assert r.status_code == 503


@pytest.mark.parametrize("path,expected", [
    ("/garages", "/garages?embed=1"),
    ("/sa-watchlist?tab=manual", "/sa-watchlist?tab=manual&embed=1"),
    ("//evil.example.com", "/sa-watchlist?embed=1"),
    ("https://evil.example.com", "/sa-watchlist?embed=1"),
    ("/\\evil.example.com", "/sa-watchlist?embed=1"),
])
def test_custom_path_parameter(client, path, expected):
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(params={"path": path}))})
    assert r.headers["location"] == expected


def test_get_shows_reopen_message(client):
    r = client.get("/embed/canvas")
    assert r.status_code == 401
    assert "Open FleetPulse from Salesforce" in r.text
