import base64
import hashlib
import json
from time import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from workos.user_management import AsyncUserManagement

from core import operator_login
from core.auth import WORKOS_CLIENT_ID, WORKOS_ISSUER, workos_jwks
from core.config import settings
from main import create_app


@pytest.fixture
def workos_token(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    monkeypatch.setattr(workos_jwks, "get_signing_key_from_jwt", lambda _: SimpleNamespace(key=public_key))

    def token(user_id: str, *, expired: bool = False) -> str:
        now = int(time())
        return jwt.encode({
            "iss": WORKOS_ISSUER,
            "client_id": WORKOS_CLIENT_ID,
            "sub": user_id,
            "iat": now - 300,
            "exp": now - 1 if expired else now + 300,
            "org_id": "test-school",
            "permissions": ["school:manage"],
        }, private_key, algorithm="RS256")

    return token


def test_default_app_has_no_local_operator_account(monkeypatch):
    monkeypatch.setattr(settings, "WORKOS_OPERATOR_USER_IDS", [])
    with TestClient(create_app()) as client:
        assert client.get("/admin/login").status_code == 404
        assert client.get("/admin/auth/login").status_code == 404
        assert client.get("/admin/auth/callback").status_code == 404
        assert client.get("/api/healthcheck").status_code == 200
        response = client.get("/api/openapi.json", auth=("root", "root"))
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"


OPERATOR_ID = "user_test_platform_operator"


@pytest.fixture
def operator_client(monkeypatch):
    monkeypatch.setattr(settings, "WORKOS_OPERATOR_USER_IDS", [OPERATOR_ID])
    monkeypatch.setattr(settings, "ADMIN_SESSION_SECRET", "test-only-cookie-signing-secret-123456")
    monkeypatch.setattr(settings, "ADMIN_AUTH_REDIRECT_URI", "")
    monkeypatch.setattr(settings, "ENVIRONMENT", "testing")
    with TestClient(create_app(), base_url="https://testserver", follow_redirects=False) as client:
        yield client


@pytest.fixture
def workos_exchange(monkeypatch):
    response = SimpleNamespace(access_token="", calls=[], error=None)

    async def authenticate(self, **kwargs):
        response.calls.append(kwargs)
        if response.error:
            raise response.error
        return SimpleNamespace(access_token=response.access_token)

    monkeypatch.setattr(AsyncUserManagement, "authenticate_with_code", authenticate)
    return response


def _start_login(client):
    response = client.get("/admin/auth/login")
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["Location"]).query)


def _session(client):
    encoded = client.cookies.get("cortex_operator").split(".")[0]
    return json.loads(base64.b64decode(encoded))


def test_operator_console_and_documentation_require_workos(operator_client, workos_exchange, workos_token):
    client = operator_client
    operator = workos_token(OPERATOR_ID)
    school_admin = workos_token("user_test_school_admin")
    workos_exchange.access_token = operator

    assert client.get("/admin/").status_code == 302
    page = client.get("/admin/login")
    assert "Sign in with WorkOS" in page.text
    assert 'name="access_token"' not in page.text
    assert client.post("/admin/login", data={"username": "root", "password": "root"}).status_code == 400
    assert client.post("/admin/login", data={"access_token": operator}).status_code == 400

    assert client.get("/api/openapi.json", headers={"Authorization": f"Bearer {school_admin}"}).status_code == 403
    assert client.get("/api/openapi.json", headers={"Authorization": f"Bearer {operator}"}).status_code == 200

    authorization = _start_login(client)
    attempt = operator_login._login_signer().loads(client.cookies.get(operator_login.LOGIN_COOKIE))
    expected_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(attempt["verifier"].encode()).digest()
    ).rstrip(b"=").decode()
    assert authorization["client_id"] == [WORKOS_CLIENT_ID]
    assert authorization["provider"] == ["authkit"]
    assert authorization["redirect_uri"] == ["https://testserver/admin/auth/callback"]
    assert authorization["code_challenge_method"] == ["S256"]
    assert authorization["code_challenge"] == [expected_challenge]
    assert authorization["state"] == [attempt["state"]]
    assert attempt["verifier"] not in str(authorization)

    login = client.get("/admin/auth/callback", params={"code": "test-code", "state": attempt["state"]})
    assert login.status_code == 200
    assert '<meta http-equiv="refresh" content="0;url=https://testserver/admin/">' in login.text
    cookie = next(value.lower() for value in login.headers.get_list("Set-Cookie") if value.startswith("cortex_operator="))
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert client.cookies.get(operator_login.LOGIN_COOKIE) is None
    assert login.headers["Cache-Control"] == "no-store"
    assert login.headers["Referrer-Policy"] == "no-referrer"
    assert _session(client) == {"workos_operator": {"user_id": OPERATOR_ID, "expires_at": jwt.decode(operator, options={"verify_signature": False})["exp"]}}
    assert workos_exchange.calls == [{"code": "test-code", "code_verifier": attempt["verifier"]}]
    assert client.get("/admin/").status_code == 200
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/students/").status_code == 401

    assert client.get("/admin/logout").status_code == 302
    assert client.get("/api/openapi.json").status_code == 401


@pytest.mark.parametrize("state", [None, "incorrect-state", "\u062d\u0627\u0644\u0629"])
def test_callback_requires_browser_bound_state(operator_client, workos_exchange, state):
    _start_login(operator_client)
    params = {"code": "test-code"}
    if state is not None:
        params["state"] = state
    response = operator_client.get("/admin/auth/callback", params=params)
    assert response.headers["Location"].endswith("/admin/login?error=expired")
    assert workos_exchange.calls == []
    assert operator_client.get("/api/openapi.json").status_code == 401


def test_callback_without_login_cookie_is_rejected(operator_client, workos_exchange):
    response = operator_client.get("/admin/auth/callback", params={"code": "test-code", "state": "state"})
    assert response.headers["Location"].endswith("error=expired")
    assert workos_exchange.calls == []


def test_tampered_login_cookie_is_rejected(operator_client, workos_exchange):
    operator_client.cookies.set(operator_login.LOGIN_COOKIE, "tampered", path=operator_login.LOGIN_COOKIE_PATH)
    response = operator_client.get("/admin/auth/callback", params={"code": "test-code", "state": "state"})
    assert response.headers["Location"].endswith("error=expired")
    assert workos_exchange.calls == []


def test_temporary_cookie_is_restricted_to_login_routes(operator_client):
    response = operator_client.get("/admin/auth/login")
    cookie = response.headers["Set-Cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert "path=/admin/auth" in cookie and "max-age=600" in cookie
    assert operator_client.cookies.get("cortex_operator") is None


def test_expired_login_attempt_is_rejected(operator_client, workos_exchange, monkeypatch):
    state = _start_login(operator_client)["state"][0]
    monkeypatch.setattr(operator_login, "time", lambda: time() + operator_login.LOGIN_MAX_AGE_SECONDS + 1)
    response = operator_client.get("/admin/auth/callback", params={"code": "test-code", "state": state})
    assert response.headers["Location"].endswith("error=expired")
    assert workos_exchange.calls == []


@pytest.mark.parametrize("params", [{}, {"error": "access_denied", "error_description": "untrusted text"}])
def test_cancelled_or_incomplete_login_does_not_exchange_code(operator_client, workos_exchange, params):
    state = _start_login(operator_client)["state"][0]
    response = operator_client.get("/admin/auth/callback", params={"state": state, **params})
    assert response.headers["Location"].endswith("error=failed")
    assert workos_exchange.calls == []
    assert "untrusted text" not in operator_client.get(response.headers["Location"]).text


@pytest.mark.parametrize("failure", ["school-admin", "expired-token", "invalid-token", "network"])
def test_callback_denies_unauthorized_or_invalid_authentication(operator_client, workos_exchange, workos_token, failure):
    if failure == "school-admin":
        workos_exchange.access_token = workos_token("user_test_school_admin")
    elif failure == "expired-token":
        workos_exchange.access_token = workos_token(OPERATOR_ID, expired=True)
    elif failure == "invalid-token":
        workos_exchange.access_token = "invalid-token"
    else:
        workos_exchange.error = httpx.ConnectError("WorkOS unavailable")
    state = _start_login(operator_client)["state"][0]
    response = operator_client.get("/admin/auth/callback", params={"code": "test-code", "state": state})
    error = "forbidden" if failure == "school-admin" else "failed"
    assert response.headers["Location"].endswith(f"error={error}")
    assert operator_client.get("/api/openapi.json").status_code == 401
    assert operator_client.cookies.get(operator_login.LOGIN_COOKIE) is None
    assert operator_client.cookies.get("cortex_operator") is None


def test_callback_cannot_be_replayed(operator_client, workos_exchange, workos_token):
    workos_exchange.access_token = workos_token(OPERATOR_ID)
    state = _start_login(operator_client)["state"][0]
    params = {"code": "test-code", "state": state}
    assert operator_client.get("/admin/auth/callback", params=params).status_code == 200
    assert operator_client.get("/admin/auth/callback", params=params).headers["Location"].endswith("error=expired")
    assert len(workos_exchange.calls) == 1


def test_operator_allowlist_is_checked_for_existing_sessions(operator_client, workos_exchange, workos_token, monkeypatch):
    workos_exchange.access_token = workos_token(OPERATOR_ID)
    state = _start_login(operator_client)["state"][0]
    operator_client.get("/admin/auth/callback", params={"code": "test-code", "state": state})
    monkeypatch.setattr(settings, "WORKOS_OPERATOR_USER_IDS", [])
    assert operator_client.get("/admin/").status_code == 302
    assert operator_client.get("/api/openapi.json").status_code == 401


def test_callback_url_can_be_set_for_railway_proxy(operator_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_AUTH_REDIRECT_URI", "https://backend.example.com/admin/auth/callback")
    assert _start_login(operator_client)["redirect_uri"] == ["https://backend.example.com/admin/auth/callback"]
