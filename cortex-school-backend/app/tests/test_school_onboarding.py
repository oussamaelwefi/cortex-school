"""School onboarding against an isolated test database; all WorkOS calls are fake."""

import asyncio
import base64
import json
import re
import uuid
from time import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner
from sqlalchemy import func, select

from core.auth import get_current_user
from core.config import settings
from core.db import SessionLocal, db_session as session_dependency
from main import create_app
from modules.onboarding import admin, router, services, tasks
from modules.onboarding.models import SchoolRequest
from modules.onboarding.schemas import SchoolRequestCreate
from modules.schools.models import Country, School


OPERATOR = "user_platform_operator"
APPLICANT = "user_school_requester"
PAYLOAD = {"school_name": "Cortex Primary", "country_code": "TN", "timezone": "Africa/Tunis", "notes": "I manage this school."}


class FakeWorkOS:
    def __init__(self):
        self.users = {}
        self.orgs = {}
        self.memberships = {}
        self.created_orgs = 0
        self.created_memberships = 0
        self.lose_org_response = False
        self.lose_membership_response = False
        self.fail_membership = False
        self.started = None
        self.resume = None
        self.user_management = SimpleNamespace(get_user=self.get_user)
        self.organizations = SimpleNamespace(get_organization_by_external_id=self.get_org_by_external_id,
                                              get_organization=self.get_org, create_organization=self.create_org)
        self.organization_membership = SimpleNamespace(list_organization_memberships=self.list_memberships,
            create_organization_membership=self.create_membership, update_organization_membership=self.update_membership)

    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False

    async def get_user(self, user_id):
        return self.users.setdefault(user_id, SimpleNamespace(id=user_id, email=f"{user_id}@example.test", email_verified=True, first_name="Amira", last_name="Ben Ali"))

    async def get_org_by_external_id(self, external_id):
        if external_id not in self.orgs:
            raise services.NotFoundError("Not found")
        return self.orgs[external_id]

    async def get_org(self, organization_id):
        return next(org for org in self.orgs.values() if org.id == organization_id)

    async def create_org(self, **kwargs):
        self.created_orgs += 1
        org = SimpleNamespace(id=f"org_school_{self.created_orgs}", **kwargs)
        self.orgs[kwargs["external_id"]] = org
        if self.started:
            self.started.set()
            await self.resume.wait()
        if self.lose_org_response:
            self.lose_org_response = False
            raise httpx.ReadTimeout("Sensitive provider error must not be displayed")
        return org

    async def list_memberships(self, user_id, organization_id):
        item = self.memberships.get((user_id, organization_id))
        return SimpleNamespace(data=[item] if item else [])

    async def create_membership(self, user_id, organization_id, role):
        if self.fail_membership:
            raise httpx.ConnectError("Sensitive provider error must not be displayed")
        self.created_memberships += 1
        item = SimpleNamespace(id=f"om_school_{self.created_memberships}", status="active", role=SimpleNamespace(slug=role.role_slug))
        self.memberships[(user_id, organization_id)] = item
        if self.lose_membership_response:
            self.lose_membership_response = False
            raise httpx.ReadTimeout("Response lost after membership was created")
        return item

    async def update_membership(self, membership_id, role):
        item = next(item for item in self.memberships.values() if item.id == membership_id)
        item.role.slug = role.role_slug
        return item


@pytest.fixture
def workos(monkeypatch):
    client = FakeWorkOS()
    monkeypatch.setattr(services, "workos_client", lambda: client)
    monkeypatch.setattr(settings, "WORKOS_OPERATOR_USER_IDS", [OPERATOR])
    return client


@pytest_asyncio.fixture
async def onboarding_client(db_session, workos, monkeypatch):
    db_session.add(Country(code="TN", name="Tunisia", calling_code="+216"))
    await db_session.commit()
    app = FastAPI()
    app.include_router(router.router, prefix="/api")

    def identity(request: Request):
        user_id = request.headers.get("X-Test-User")
        if not user_id:
            raise HTTPException(401, "Sign in first")
        return {"user_id": user_id, "organization_id": "org_existing_school", "claims": {"permissions": ["school:manage"]}}

    async def session_override(): yield db_session
    app.dependency_overrides[get_current_user] = identity
    app.dependency_overrides[session_dependency] = session_override
    monkeypatch.setattr(router, "enqueue_school_provisioning", Mock())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        yield client


def headers(user_id=APPLICANT): return {"X-Test-User": user_id}


async def submit(client, user_id=APPLICANT):
    response = await client.post("/api/school-requests/", json=PAYLOAD, headers=headers(user_id))
    assert response.status_code == 201, response.text
    return response.json()


async def approve(client, request_id):
    return await client.post(f"/api/school-requests/{request_id}/approve", headers=headers(OPERATOR))


@pytest.mark.asyncio
async def test_request_requires_authentication_and_verified_identity(onboarding_client, workos):
    assert (await onboarding_client.get("/api/school-requests/countries")).status_code == 401
    assert (await onboarding_client.post("/api/school-requests/", json=PAYLOAD)).status_code == 401
    user = await workos.get_user(APPLICANT)
    user.email_verified = False
    assert (await onboarding_client.post("/api/school-requests/", json=PAYLOAD, headers=headers())).status_code == 403
    assert workos.created_orgs == 0


@pytest.mark.asyncio
async def test_request_stores_authoritative_identity_and_does_not_provision(onboarding_client, db_session, workos):
    result = await submit(onboarding_client)
    record = await db_session.get(SchoolRequest, uuid.UUID(result["id"]))
    assert record.requester_user_id == APPLICANT
    assert record.requester_email == f"{APPLICANT}@example.test"
    assert record.status == "pending" and record.organization_id is None
    assert workos.created_orgs == workos.created_memberships == 0
    assert "requester_email" not in result and "last_error" not in result
    duplicate = await onboarding_client.post("/api/school-requests/", json=PAYLOAD, headers=headers())
    assert duplicate.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"school_name": "  "}, {"timezone": "Not/A_Zone"}, {"country_code": "ZZ"}, {"requester_user_id": OPERATOR}, {"organization_id": "org_other_school"}, {"status": "approved"}])
async def test_invalid_or_privilege_injecting_requests_are_rejected(onboarding_client, change):
    response = await onboarding_client.post("/api/school-requests/", json={**PAYLOAD, **change}, headers=headers())
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_requester_only_sees_their_own_requests(onboarding_client):
    first = await submit(onboarding_client)
    await submit(onboarding_client, "user_other_requester")
    response = await onboarding_client.get("/api/school-requests/mine", headers=headers())
    assert [item["id"] for item in response.json()] == [first["id"]]


@pytest.mark.asyncio
async def test_school_admin_cannot_approve_and_rejection_cannot_be_approved(onboarding_client, workos):
    item = await submit(onboarding_client)
    path = f"/api/school-requests/{item['id']}"
    assert (await onboarding_client.post(path + "/approve", headers=headers())).status_code == 403
    assert (await onboarding_client.post(path + "/reject", headers=headers(), json={"reason": "No"})).status_code == 403
    response = await onboarding_client.post(path + "/reject", headers=headers(OPERATOR), json={"reason": "Please confirm your school affiliation."})
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert (await approve(onboarding_client, item["id"])).status_code == 409
    assert await services.process_school_request(uuid.UUID(item["id"])) == "skipped"
    assert workos.created_orgs == 0
    assert (await onboarding_client.post("/api/school-requests/", json=PAYLOAD, headers=headers())).status_code == 201


@pytest.mark.asyncio
async def test_approval_provisions_school_and_exact_admin_role_once(onboarding_client, db_session, workos):
    item = await submit(onboarding_client)
    request_id = uuid.UUID(item["id"])
    assert (await approve(onboarding_client, request_id)).json()["status"] == "provisioning"
    assert await services.process_school_request(request_id) == "approved"
    await db_session.rollback()
    record = await db_session.get(SchoolRequest, request_id, populate_existing=True)
    school = await db_session.get(School, record.organization_id)
    assert record.reviewed_by == OPERATOR and record.reviewed_at and record.completed_at
    assert school.country_code == "TN" and school.timezone == "Africa/Tunis"
    membership = workos.memberships[(APPLICANT, school.organization_id)]
    assert membership.role.slug == "school_admin"
    assert (await approve(onboarding_client, request_id)).json()["status"] == "approved"
    assert await services.process_school_request(request_id) == "skipped"
    assert workos.created_orgs == workos.created_memberships == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["organization_response", "membership_response", "membership_failure"])
async def test_retry_recovers_partial_work_without_duplicates(onboarding_client, db_session, workos, failure):
    item = await submit(onboarding_client)
    request_id = uuid.UUID(item["id"])
    await approve(onboarding_client, request_id)
    workos.lose_org_response = failure == "organization_response"
    workos.lose_membership_response = failure == "membership_response"
    workos.fail_membership = failure == "membership_failure"
    assert await services.process_school_request(request_id) == "failed"
    await db_session.rollback()
    record = await db_session.get(SchoolRequest, request_id, populate_existing=True)
    assert "Sensitive provider error" not in record.last_error
    assert await db_session.scalar(select(func.count()).select_from(School)) == 0
    original_review = record.reviewed_at
    workos.fail_membership = False
    await approve(onboarding_client, request_id)
    assert await services.process_school_request(request_id) == "approved"
    await db_session.rollback()
    await db_session.refresh(record)
    assert record.reviewed_at == original_review and record.attempt_count == 2
    assert workos.created_orgs == workos.created_memberships == 1


@pytest.mark.asyncio
async def test_duplicate_workers_skip_a_locked_request(onboarding_client, workos):
    item = await submit(onboarding_client)
    request_id = uuid.UUID(item["id"])
    await approve(onboarding_client, request_id)
    workos.started, workos.resume = asyncio.Event(), asyncio.Event()
    first = asyncio.create_task(services.process_school_request(request_id))
    try:
        await asyncio.wait_for(workos.started.wait(), timeout=5)
        assert await asyncio.wait_for(services.process_school_request(request_id), timeout=5) == "skipped"
    finally:
        workos.resume.set()
    assert await first == "approved"
    assert workos.created_orgs == workos.created_memberships == 1


@pytest.mark.asyncio
async def test_changed_or_unverified_requester_cannot_gain_admin_access(onboarding_client, workos):
    item = await submit(onboarding_client)
    await approve(onboarding_client, item["id"])
    (await workos.get_user(APPLICANT)).email = "changed@example.test"
    assert await services.process_school_request(uuid.UUID(item["id"])) == "failed"
    assert workos.created_orgs == workos.created_memberships == 0


@pytest.mark.asyncio
async def test_scheduler_recovers_broker_handoff_failure(onboarding_client, workos, monkeypatch):
    item = await submit(onboarding_client)
    await approve(onboarding_client, item["id"])
    monkeypatch.setattr(tasks.provision_school_task, "apply_async", Mock(side_effect=RuntimeError("Broker down")))
    tasks.enqueue_school_provisioning(uuid.UUID(item["id"]))
    await tasks.drain_school_requests()
    assert workos.created_orgs == workos.created_memberships == 1


@pytest.mark.asyncio
async def test_console_requires_operator_session_and_csrf_for_review(onboarding_client, db_session, monkeypatch):
    item = await submit(onboarding_client)
    monkeypatch.setattr(settings, "ADMIN_SESSION_SECRET", "onboarding-test-only-secret-at-least-32-characters")
    monkeypatch.setattr(settings, "ENVIRONMENT", "testing")
    monkeypatch.setattr(admin, "enqueue_school_provisioning", Mock())
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver", follow_redirects=False) as client:
        assert (await client.get("/admin/school-requests")).status_code == 302
        session = {"workos_operator": {"user_id": OPERATOR, "expires_at": int(time()) + 600}}
        value = base64.b64encode(json.dumps(session).encode())
        client.cookies.set("cortex_operator", TimestampSigner(settings.ADMIN_SESSION_SECRET).sign(value).decode())
        page = await client.get("/admin/school-requests")
        assert page.status_code == 200, page.text
        assert PAYLOAD["school_name"] in page.text and "Approve school" in page.text
        assert (await client.get("/admin/school-requests", params={"decision": "approve", "request_id": item["id"]})).status_code == 200
        response = await client.post("/admin/school-requests", data={"decision": "approve", "request_id": item["id"]})
        assert response.status_code == 403
        token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        response = await client.post("/admin/school-requests", data={"csrf": token, "decision": "approve", "request_id": item["id"]})
        assert response.status_code == 303
    await db_session.rollback()
    record = await db_session.get(SchoolRequest, uuid.UUID(item["id"]), populate_existing=True)
    assert record.status == "provisioning" and record.reviewed_by == OPERATOR
