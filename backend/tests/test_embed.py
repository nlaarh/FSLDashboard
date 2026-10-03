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
UAT_SECRET = "test-uat-consumer-secret"
PROD_SECRET = "test-prod-consumer-secret"
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
    monkeypatch.setenv("SF_CANVAS_SECRET_TEST", SECRET)
    monkeypatch.delenv("SF_CANVAS_ORG_ID_TEST", raising=False)
    monkeypatch.delenv("SF_CANVAS_SECRET_UAT", raising=False)
    monkeypatch.delenv("SF_CANVAS_ORG_ID_UAT", raising=False)
    monkeypatch.delenv("SF_CANVAS_SECRET_PROD", raising=False)
    monkeypatch.delenv("SF_CANVAS_ORG_ID_PROD", raising=False)
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


@pytest.mark.parametrize("email", ["jdoe@nyaaa.com.invalid", "JDoe@NYAAA.com.INVALID"])
def test_sandbox_invalid_suffix_is_stripped(client, email):
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(email=email))})
    assert r.status_code == 303


def test_sandbox_email_for_unknown_user_still_rejected(client):
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(email="nobody@nyaaa.com.invalid"))})
    assert r.status_code == 403
    assert "nobody@nyaaa.com" in r.text


def test_org_lock_rejects_sandbox_even_with_valid_email(client, monkeypatch):
    monkeypatch.setenv("SF_CANVAS_ORG_ID_TEST", "00DDo000001BxM7")
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(email="jdoe@nyaaa.com.invalid",
                                                                                 org="00DSANDBOX00001"))})
    assert r.status_code == 403


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
    monkeypatch.setenv("SF_CANVAS_ORG_ID_TEST", "00Dxx0000009999")
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request())})
    assert r.status_code == 403


def test_matching_org_15_vs_18_chars(client, monkeypatch):
    monkeypatch.setenv("SF_CANVAS_ORG_ID_TEST", "00Dxx0000001gER")
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request())})
    assert r.status_code == 303


def test_no_secret_configured(client, monkeypatch):
    monkeypatch.delenv("SF_CANVAS_SECRET_TEST")
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request())})
    assert r.status_code == 503


def test_uat_key_signs_in_sandbox_user(client, monkeypatch):
    monkeypatch.setenv("SF_CANVAS_SECRET_UAT", UAT_SECRET)
    req = canvas_request(email="jdoe@nyaaa.com.invalid", org="00DUAT000000001")
    r = client.post("/embed/canvas", data={"signed_request": sign(req, secret=UAT_SECRET)})
    assert r.status_code == 303
    assert r.headers["location"] == "/sa-watchlist?embed=1"


def test_uat_key_alone_enables_sign_in(client, monkeypatch):
    monkeypatch.delenv("SF_CANVAS_SECRET_TEST")
    monkeypatch.setenv("SF_CANVAS_SECRET_UAT", UAT_SECRET)
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(), secret=UAT_SECRET)})
    assert r.status_code == 303
    # ...but the test-org key no longer works when it isn't configured
    assert client.post("/embed/canvas", data={"signed_request": sign(canvas_request())}).status_code == 401


def test_test_org_lock_does_not_block_uat_key(client, monkeypatch):
    monkeypatch.setenv("SF_CANVAS_ORG_ID_TEST", "00DTEST00000001")
    monkeypatch.setenv("SF_CANVAS_SECRET_UAT", UAT_SECRET)
    monkeypatch.setenv("SF_CANVAS_ORG_ID_UAT", "00DUAT000000001")
    uat = canvas_request(org="00DUAT000000001AAA")
    assert client.post("/embed/canvas", data={"signed_request": sign(uat, secret=UAT_SECRET)}).status_code == 303
    prod = canvas_request(org="00DTEST00000001AAA")
    assert client.post("/embed/canvas", data={"signed_request": sign(prod)}).status_code == 303


def test_uat_key_rejected_from_other_org(client, monkeypatch):
    monkeypatch.setenv("SF_CANVAS_SECRET_UAT", UAT_SECRET)
    monkeypatch.setenv("SF_CANVAS_ORG_ID_UAT", "00DUAT000000001")
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(org="00DTEST00000001"), secret=UAT_SECRET)})
    assert r.status_code == 403
    assert "set-cookie" not in r.headers


def test_test_key_rejected_from_uat_org_when_locked(client, monkeypatch):
    monkeypatch.setenv("SF_CANVAS_ORG_ID_TEST", "00DTEST00000001")
    monkeypatch.setenv("SF_CANVAS_SECRET_UAT", UAT_SECRET)
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(org="00DUAT000000001"))})
    assert r.status_code == 403


def test_all_three_orgs_sign_in_with_their_own_key(client, monkeypatch):
    monkeypatch.setenv("SF_CANVAS_ORG_ID_TEST", "00DTEST00000001")
    monkeypatch.setenv("SF_CANVAS_SECRET_UAT", UAT_SECRET)
    monkeypatch.setenv("SF_CANVAS_ORG_ID_UAT", "00DUAT000000001")
    monkeypatch.setenv("SF_CANVAS_SECRET_PROD", PROD_SECRET)
    monkeypatch.setenv("SF_CANVAS_ORG_ID_PROD", "00DDo000001BxM7")
    for secret, org in ((SECRET, "00DTEST00000001AAA"), (UAT_SECRET, "00DUAT000000001AAA"), (PROD_SECRET, "00DDo000001BxM7MAK")):
        r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(org=org), secret=secret)})
        assert r.status_code == 303, (secret, org)


def test_prod_key_cannot_be_used_from_a_sandbox(client, monkeypatch):
    monkeypatch.setenv("SF_CANVAS_SECRET_PROD", PROD_SECRET)
    monkeypatch.setenv("SF_CANVAS_ORG_ID_PROD", "00DDo000001BxM7")
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(org="00DUAT000000001"), secret=PROD_SECRET)})
    assert r.status_code == 403
    assert "set-cookie" not in r.headers


def test_prod_key_alone_enables_sign_in(client, monkeypatch):
    monkeypatch.delenv("SF_CANVAS_SECRET_TEST")
    monkeypatch.setenv("SF_CANVAS_SECRET_PROD", PROD_SECRET)
    r = client.post("/embed/canvas", data={"signed_request": sign(canvas_request(), secret=PROD_SECRET)})
    assert r.status_code == 303


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
