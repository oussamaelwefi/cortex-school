"""Workspace identity with fake dependencies; no database or provider access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from core.db import db_session
from modules.schools import router as schools


@pytest.fixture
def workspace(monkeypatch):
    monkeypatch.setattr(schools.settings, "WORKOS_API_KEY", "")
    session = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(organization_id="org-school")),
        scalar=AsyncMock(return_value="École Les Oliviers"),
    )
    user = {"organization_id": "org-school", "claims": {"roles": ["teacher"], "permissions": []}}
    app = FastAPI()
    app.include_router(schools.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[db_session] = lambda: session
    with TestClient(app) as client:
        yield client, session, user


@pytest.mark.parametrize("role", ["school_admin", "teacher", "guardian"])
def test_context_is_shared_and_scoped_to_authenticated_school(workspace, role, monkeypatch):
    client, session, user = workspace
    user["claims"]["roles"] = [role]
    monkeypatch.setattr(schools, "AsyncWorkOSClient", lambda **kwargs: pytest.fail("Local school name needs no provider call"))
    response = client.get("/school/context?organization_id=org-someone-else")
    assert response.status_code == 200
    assert response.json() == {"organization_id": "org-school", "name": "École Les Oliviers"}
    session.get.assert_awaited_once_with(schools.School, "org-school")
    query = session.scalar.await_args.args[0]
    filters = query.compile().params.values()
    assert "org-school" in filters
    assert "approved" in filters
    assert "org-someone-else" not in filters


def test_missing_school_returns_404(workspace):
    client, session, _ = workspace
    session.get.return_value = None
    assert client.get("/school/context").status_code == 404
    session.scalar.assert_not_awaited()


@pytest.mark.parametrize("method", ["GET", "PUT"])
@pytest.mark.parametrize("path", ["attendance-settings", "ai-settings"])
def test_shared_context_does_not_open_admin_settings(workspace, method, path):
    client, session, _ = workspace
    response = client.request(method, f"/school/{path}", json={})
    assert response.status_code == 403
    session.get.assert_not_awaited()


def test_settings_remain_available_to_school_administrators(workspace):
    client, session, user = workspace
    user["claims"]["permissions"] = ["school:manage"]
    session.get.return_value = SimpleNamespace(
        ai_teacher_draft_enabled=False, ai_teacher_draft_default_language="auto",
        ai_guardian_weekly_explanation_enabled=False,
        ai_guardian_weekly_explanation_default_language="auto",
    )
    assert client.get("/school/ai-settings").status_code == 200


@pytest.mark.parametrize("available", [True, False])
def test_legacy_school_name_and_provider_failure(workspace, monkeypatch, available):
    client, session, _ = workspace
    session.scalar.return_value = None
    monkeypatch.setattr(schools.settings, "WORKOS_API_KEY", "test-only-key")
    get_organization = AsyncMock(return_value=SimpleNamespace(name="Legacy school"))
    if not available:
        get_organization.side_effect = httpx.ReadTimeout("Provider is temporarily unavailable")

    class FakeWorkOS:
        def __init__(self, **kwargs):
            assert kwargs["request_timeout"] == 3
            assert kwargs["max_retries"] == 0
            self.organizations = SimpleNamespace(get_organization=get_organization)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(schools, "AsyncWorkOSClient", FakeWorkOS)
    response = client.get("/school/context")
    assert response.status_code == 200
    assert response.json()["name"] == ("Legacy school" if available else None)
    get_organization.assert_awaited_once_with("org-school")


def test_unauthenticated_context_is_rejected():
    app = FastAPI()
    app.include_router(schools.router)
    with TestClient(app) as client:
        assert client.get("/school/context").status_code == 401
