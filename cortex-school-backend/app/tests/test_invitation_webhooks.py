import hashlib
import hmac
import json
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from core.auth import get_current_user
from core.config import settings
from main import create_app
from modules.invitations.models import Invitation, InvitationSendStatus


SECRET = "test-workos-endpoint-secret"
ORG_ID = "org_invitation_school"
WORKOS_ID = "invitation_from_workos"
EMAIL = "teacher@example.test"


@pytest_asyncio.fixture
async def webhook_client(db_session, monkeypatch):
    monkeypatch.setattr(settings, "WORKOS_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(settings, "WORKOS_API_KEY", "")
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "user_admin",
        "organization_id": ORG_ID,
        "claims": {"permissions": ["school:manage"]},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
        yield client


def _invitation(**overrides):
    return Invitation(**{
        "organization_id": ORG_ID,
        "email": EMAIL,
        "send_status": InvitationSendStatus.SENT,
        "workos_invitation_id": WORKOS_ID,
        "workos_state": "pending",
        **overrides,
    })


async def _deliver(client, state="accepted", *, organization_id=ORG_ID,
                   workos_id=WORKOS_ID, signing_secret=SECRET, trailing_slash=True):
    event_type = {"accepted": "accepted", "pending": "created", "revoked": "revoked"}
    occurred_at = "2025-01-03T12:00:00.000Z" if state != "pending" else "2025-01-01T12:00:00.000Z"
    body = json.dumps({
        "event": f"invitation.{event_type[state]}",
        "id": f"event_{state}",
        "created_at": occurred_at,
        "data": {
            "object": "invitation",
            "id": workos_id,
            "email": EMAIL,
            "state": state,
            "accepted_at": occurred_at if state == "accepted" else None,
            "revoked_at": occurred_at if state == "revoked" else None,
            "expires_at": "2025-01-08T12:00:00.000Z",
            "organization_id": organization_id,
            "inviter_user_id": "user_admin",
            "accepted_user_id": "user_teacher" if state == "accepted" else None,
            "role_slug": "teacher",
            "created_at": "2025-01-01T12:00:00.000Z",
            "updated_at": occurred_at,
        },
    }).encode()
    timestamp = str(int(time.time() * 1000))
    digest = hmac.new(signing_secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return await client.post(
        "/api/webhooks/workos" + ("/" if trailing_slash else ""),
        content=body,
        headers={"Content-Type": "application/json", "WorkOS-Signature": f"t={timestamp}, v1={digest}"},
    )


@pytest.mark.asyncio
async def test_signed_acceptance_survives_duplicate_and_delayed_creation(webhook_client, db_session):
    invitation = _invitation()
    db_session.add(invitation)
    await db_session.commit()

    response = await _deliver(webhook_client, trailing_slash=False)
    assert response.status_code == 200, response.text
    await db_session.refresh(invitation)
    accepted_updated_at = invitation.updated_at
    assert invitation.workos_state == "accepted"
    assert invitation.send_status == InvitationSendStatus.SENT

    assert (await _deliver(webhook_client)).status_code == 200
    assert (await _deliver(webhook_client, "pending")).status_code == 200
    await db_session.refresh(invitation)
    assert invitation.updated_at == accepted_updated_at

    invitations = await webhook_client.get("/api/invitations/")
    assert invitations.json()[0]["workos_state"] == "accepted"
    retry = await webhook_client.post(f"/api/invitations/{invitation.id}/retry/")
    assert retry.status_code == 409


@pytest.mark.asyncio
async def test_invalid_signature_and_mismatched_organization_cannot_update_invitation(webhook_client, db_session):
    invitation = _invitation()
    db_session.add(invitation)
    await db_session.commit()

    assert (await webhook_client.post("/api/webhooks/workos/", json={})).status_code == 400
    assert (await _deliver(webhook_client, signing_secret="wrong-secret")).status_code == 400
    assert (await _deliver(webhook_client, organization_id="org_other_school")).status_code == 200
    assert (await _deliver(webhook_client, workos_id="invitation_old_id")).status_code == 200
    await db_session.refresh(invitation)
    assert invitation.workos_state == "pending"


@pytest.mark.asyncio
async def test_early_acceptance_retries_after_sender_links_provider_id(webhook_client, db_session):
    invitation = _invitation(send_status=InvitationSendStatus.PROCESSING, workos_invitation_id=None, workos_state=None)
    db_session.add(invitation)
    await db_session.commit()

    assert (await _deliver(webhook_client)).status_code == 503
    await db_session.refresh(invitation)
    assert invitation.workos_state is None

    invitation.workos_invitation_id = WORKOS_ID
    invitation.send_status = InvitationSendStatus.SENT
    invitation.workos_state = "pending"
    await db_session.commit()

    assert (await _deliver(webhook_client)).status_code == 200
    await db_session.refresh(invitation)
    assert invitation.workos_state == "accepted"
