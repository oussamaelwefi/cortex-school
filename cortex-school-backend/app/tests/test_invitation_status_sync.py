"""Missed-webhook recovery against an isolated database; no real provider calls."""

from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from core.auth import get_current_user
from core.config import settings
from core.db import SessionLocal, db_session as session_dependency
from modules.invitations import router, services
from modules.invitations.models import Invitation, UserRoles

ORG = "org_status_sync"
EXPIRY = datetime(2030, 1, 8, tzinfo=timezone.utc)


def invitation(name="teacher", **overrides):
    return Invitation(**{
        "organization_id": ORG, "email": f"{name}@example.test",
        "role_slug": UserRoles.TEACHER, "send_status": "sent",
        "workos_invitation_id": f"invitation_{name}", "workos_state": "pending",
        "expires_at": EXPIRY, **overrides,
    })


def snapshot(record, state="accepted", **overrides):
    return NS(**{
        "id": record.workos_invitation_id, "organization_id": record.organization_id,
        "email": record.email, "state": state, "expires_at": EXPIRY,
        "token": "private-invitation-token", **overrides,
    })


@pytest_asyncio.fixture
async def sync_client(db_session, monkeypatch):
    monkeypatch.setattr(settings, "WORKOS_API_KEY", "fake-test-key")
    provider = NS()
    provider.items = []
    provider.pages = {}
    provider.before_return = None

    async def list_invitations(**kwargs):
        if provider.before_return:
            await provider.before_return()
        return provider.pages.get(kwargs["after"], NS(data=provider.items, list_metadata=NS(after=None)))

    async def get_invitation(provider_id):
        if provider.before_return:
            await provider.before_return()
        return next(item for item in provider.items if item.id == provider_id)

    provider.user_management = NS(
        list_invitations=AsyncMock(side_effect=list_invitations),
        get_invitation=AsyncMock(side_effect=get_invitation),
    )

    class FakeWorkOS:
        def __init__(self, **kwargs):
            assert kwargs["request_timeout"] == 3
            assert kwargs["max_retries"] == 0

        async def __aenter__(self): return provider
        async def __aexit__(self, *args): return False

    monkeypatch.setattr(services, "AsyncWorkOSClient", FakeWorkOS)
    enqueue = AsyncMock()
    monkeypatch.setattr(router, "enqueue_invitation_task", enqueue)
    app = FastAPI()
    app.include_router(router.router, prefix="/api")
    user = {"user_id": "user_admin", "organization_id": ORG, "claims": {"permissions": ["school:manage"]}}
    app.dependency_overrides[get_current_user] = lambda: user

    async def session_override(): yield db_session

    app.dependency_overrides[session_dependency] = session_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield NS(client=client, provider=provider, enqueue=enqueue, user=user)


@pytest.mark.asyncio
async def test_list_recovers_and_persists_acceptance_without_a_webhook(sync_client, db_session):
    record = invitation()
    db_session.add(record)
    await db_session.commit()
    sync_client.provider.items = [snapshot(record)]
    response = await sync_client.client.get("/api/invitations/")
    assert response.status_code == 200, response.text
    assert response.json()[0]["workos_state"] == "accepted"
    assert response.json()[0]["send_status"] == "sent"
    assert "private-invitation-token" not in response.text
    await db_session.refresh(record)
    assert record.workos_state == "accepted"
    sync_client.provider.user_management.list_invitations.assert_awaited_once_with(
        organization_id=ORG, limit=100, after=None,
    )
    # Accepted invitations no longer need provider reads.
    assert (await sync_client.client.get("/api/invitations/")).status_code == 200
    assert sync_client.provider.user_management.list_invitations.await_count == 1


@pytest.mark.asyncio
async def test_bulk_pagination_updates_exact_ids_without_per_row_requests(sync_client, db_session):
    first, second, foreign = invitation("first"), invitation("second"), invitation("foreign", organization_id="org_elsewhere")
    db_session.add_all([first, second, foreign])
    await db_session.commit()
    sync_client.provider.pages = {
        None: NS(data=[snapshot(first)], list_metadata=NS(after="page-2")),
        "page-2": NS(data=[snapshot(second, "revoked"), snapshot(foreign)], list_metadata=NS(after=None)),
    }
    response = await sync_client.client.get("/api/invitations/")
    assert response.status_code == 200
    assert {item["workos_state"] for item in response.json()} == {"accepted", "revoked"}
    assert len(response.json()) == 2
    assert sync_client.provider.user_management.list_invitations.await_count == 2
    sync_client.provider.user_management.get_invitation.assert_not_awaited()
    await db_session.refresh(foreign)
    assert foreign.workos_state == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["id", "organization_id", "email"])
async def test_provider_records_cannot_cross_identity_or_school_boundaries(sync_client, db_session, mismatch):
    record = invitation()
    db_session.add(record)
    await db_session.commit()
    sync_client.provider.items = [snapshot(record, **{mismatch: "someone-else"})]
    response = await sync_client.client.get("/api/invitations/")
    assert response.status_code == 200
    assert response.json()[0]["workos_state"] == "pending"


@pytest.mark.asyncio
async def test_detail_and_retry_recheck_workos_before_sending(sync_client, db_session):
    record = invitation()
    db_session.add(record)
    await db_session.commit()
    sync_client.provider.items = [snapshot(record)]
    response = await sync_client.client.post(f"/api/invitations/{record.id}/retry/")
    assert response.status_code == 409
    sync_client.enqueue.assert_not_awaited()
    detail = await sync_client.client.get(f"/api/invitations/{record.id}/")
    assert detail.json()["workos_state"] == "accepted"
    sync_client.provider.user_management.get_invitation.assert_awaited_once_with(record.workos_invitation_id)


@pytest.mark.asyncio
async def test_existing_accepted_invitation_is_not_requeued_by_create(sync_client, db_session):
    record = invitation(send_status="failed", email="teacher@example.com")
    db_session.add(record)
    await db_session.commit()
    sync_client.provider.items = [snapshot(record)]
    response = await sync_client.client.post("/api/invitations/", json={"email": record.email, "role_slug": "teacher"})
    assert response.status_code == 202, response.text
    assert response.json()["workos_state"] == "accepted"
    sync_client.enqueue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["detail", "retry"])
async def test_foreign_school_requests_are_rejected_before_provider_access(sync_client, db_session, path):
    record = invitation(organization_id="org_elsewhere")
    db_session.add(record)
    await db_session.commit()
    response = await (sync_client.client.get(f"/api/invitations/{record.id}/") if path == "detail"
                      else sync_client.client.post(f"/api/invitations/{record.id}/retry/"))
    assert response.status_code == 404
    sync_client.provider.user_management.get_invitation.assert_not_awaited()
    sync_client.enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_failure_is_visible_and_does_not_change_cached_state(sync_client, db_session):
    record = invitation()
    db_session.add(record)
    await db_session.commit()
    sync_client.provider.user_management.list_invitations.side_effect = httpx.ReadTimeout("private-invitation-token")
    response = await sync_client.client.get("/api/invitations/")
    assert response.status_code == 503
    assert "private-invitation-token" not in response.text
    await db_session.refresh(record)
    assert record.workos_state == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("update_values, expected", [
    ({"workos_state": "accepted"}, "accepted"),
    ({"workos_state": "revoked"}, "revoked"),
    ({"workos_state": None, "workos_invitation_id": "invitation_replacement"}, None),
])
async def test_delayed_provider_read_cannot_undo_a_concurrent_event_or_new_link(sync_client, db_session, update_values, expected):
    record = invitation()
    db_session.add(record)
    await db_session.commit()
    sync_client.provider.items = [snapshot(record, "pending")]

    async def concurrent_event():
        async with SessionLocal() as other:
            await other.execute(update(Invitation).where(Invitation.id == record.id).values(**update_values))
            await other.commit()

    sync_client.provider.before_return = concurrent_event
    response = await sync_client.client.get("/api/invitations/")
    assert response.status_code == 200, response.text
    assert response.json()[0]["workos_state"] == expected


@pytest.mark.asyncio
async def test_repeated_provider_cursor_fails_without_applying_partial_updates(sync_client, db_session):
    first, second = invitation("first"), invitation("second")
    db_session.add_all([first, second])
    await db_session.commit()
    page = NS(data=[snapshot(first)], list_metadata=NS(after="same-cursor"))
    sync_client.provider.pages = {None: page, "same-cursor": page}
    response = await sync_client.client.get("/api/invitations/")
    assert response.status_code == 503
    assert sync_client.provider.user_management.list_invitations.await_count == 2
    await db_session.refresh(first)
    assert first.workos_state == "pending"
