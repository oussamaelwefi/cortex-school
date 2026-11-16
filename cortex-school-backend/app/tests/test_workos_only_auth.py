from time import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

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
        assert client.get("/api/healthcheck").status_code == 200
        response = client.get("/api/openapi.json", auth=("root", "root"))
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_operator_console_and_documentation_require_workos(monkeypatch, workos_token):
    operator_id = "user_test_platform_operator"
    monkeypatch.setattr(settings, "WORKOS_OPERATOR_USER_IDS", [operator_id])
    monkeypatch.setattr(settings, "ADMIN_SESSION_SECRET", "test-only-cookie-signing-secret-123456")
    monkeypatch.setattr(settings, "ENVIRONMENT", "testing")
    operator = workos_token(operator_id)
    school_admin = workos_token("user_test_school_admin")

    with TestClient(create_app(), base_url="https://testserver", follow_redirects=False) as client:
        assert client.get("/admin/").status_code == 302
        assert 'name="access_token"' in client.get("/admin/login").text
        assert client.post("/admin/login", data={"username": "root", "password": "root"}).status_code == 400
        assert client.post("/admin/login", data={"access_token": school_admin}).status_code == 400
        assert client.post("/admin/login", data={"access_token": workos_token(operator_id, expired=True)}).status_code == 400

        assert client.get("/api/openapi.json", headers={"Authorization": f"Bearer {school_admin}"}).status_code == 403
        assert client.get("/api/openapi.json", headers={"Authorization": f"Bearer {operator}"}).status_code == 200

        login = client.post("/admin/login", data={"access_token": operator})
        assert login.status_code == 302
        cookie = login.headers["Set-Cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
        assert operator not in login.headers["Set-Cookie"]
        assert client.get("/admin/").status_code == 200
        assert client.get("/api/openapi.json").status_code == 200
        assert client.get("/api/students/").status_code == 401

        assert client.get("/admin/logout").status_code == 302
        assert client.get("/api/openapi.json").status_code == 401
