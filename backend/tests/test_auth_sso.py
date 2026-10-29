"""Sign in with Microsoft — login redirect, callback checks, and the login page button."""
import base64
import json
import time
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import auth_pages, auth_sso

TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
USER = {"username": "jdoe", "name": "Jane Doe", "role": "admin", "email": "jdoe@nyaaa.com", "department": ""}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SSO_TenantId", TENANT)
    monkeypatch.setenv("SSO_UserName", CLIENT)
    monkeypatch.setenv("SSO_API", "test-secret")
    app = FastAPI()
    app.include_router(auth_sso.router)
    app.include_router(auth_pages.router)
    return TestClient(app, base_url="https://fleet.test", follow_redirects=False)


def _id_token(**claims):
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"x.{body}.sig"


def _start(client):
    """Hit the login route; return the state and nonce we sent to Microsoft."""
    r = client.get("/api/auth/sso/login")
    q = parse_qs(urlparse(r.headers["location"]).query)
    return r, q["state"][0], q["nonce"][0]


def _callback(client, state, claims, user=USER):
    token_resp = MagicMock(json=MagicMock(return_value={"id_token": _id_token(**claims)}))
    with patch.object(auth_sso.requests, "post", return_value=token_resp) as post, \
         patch.object(auth_sso.users, "find_by_email", return_value=user), \
         patch.object(auth_sso.users, "create_session", return_value="tok123"):
        r = client.get(f"/api/auth/sso/callback?code=abc&state={state}")
    return r, post


def _good_claims(nonce):
    return {"aud": CLIENT, "tid": TENANT, "nonce": nonce, "exp": time.time() + 600,
            "preferred_username": "JDoe@nyaaa.com"}


def test_login_redirects_to_aaa_tenant(client):
    r, state, nonce = _start(client)
    loc = urlparse(r.headers["location"])
    q = parse_qs(loc.query)
    assert r.status_code == 302
    assert loc.netloc == "login.microsoftonline.com" and loc.path == f"/{TENANT}/oauth2/v2.0/authorize"
    assert q["client_id"] == [CLIENT]
    assert q["redirect_uri"] == ["https://fleet.test/api/auth/sso/callback"]
    assert state and nonce and "fslapp_sso" in r.cookies


def test_callback_signs_in_matching_user(client):
    _, state, nonce = _start(client)
    r, post = _callback(client, state, _good_claims(nonce))
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert r.cookies["fslapp_auth"].startswith("jdoe:admin:tok123.")
    assert post.call_args.kwargs["data"]["client_secret"] == "test-secret"


def test_callback_rejects_wrong_state(client):
    _, _, nonce = _start(client)
    r, post = _callback(client, "forged", _good_claims(nonce))
    assert r.headers["location"] == "/login?sso_error=expired"
    post.assert_not_called()


@pytest.mark.parametrize("bad", [{"aud": "other-app"}, {"tid": "other-tenant"}, {"nonce": "replayed"},
                                 {"exp": time.time() - 5}])
def test_callback_rejects_bad_token(client, bad):
    _, state, nonce = _start(client)
    r, _ = _callback(client, state, {**_good_claims(nonce), **bad})
    assert r.headers["location"] == "/login?sso_error=microsoft"
    assert "fslapp_auth" not in r.cookies


def test_callback_unknown_email_gets_no_access(client):
    _, state, nonce = _start(client)
    r, _ = _callback(client, state, _good_claims(nonce), user=None)
    assert r.headers["location"] == "/login?sso_error=no_account"
    assert "fslapp_auth" not in r.cookies


def test_login_page_shows_button_only_when_configured(client, monkeypatch):
    assert "Sign in with Microsoft" in client.get("/login").text
    monkeypatch.delenv("SSO_API")
    assert "Sign in with Microsoft" not in client.get("/login").text
