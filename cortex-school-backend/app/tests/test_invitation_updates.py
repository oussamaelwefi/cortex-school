import asyncio
from time import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, WebSocketDisconnect
from fastapi.testclient import TestClient

from main import create_app
from modules.invitations import live, services
from modules.invitations.models import Invitation, InvitationSendStatus


PATH = "/api/invitations/ws"
SAME_ORIGIN = {"origin": "http://testserver"}


def test_websocket_subscribes_to_the_school_in_the_verified_token(monkeypatch):
    subscription = MagicMock()
    subscription.__aenter__.return_value = subscription
    subscription.subscribe = AsyncMock()
    subscription.get_message = AsyncMock(return_value={"type": "subscribe"})

    async def messages():
        yield {"type": "message", "data": live.INVITATIONS_CHANGED}
        await asyncio.Future()

    subscription.listen.side_effect = messages
    redis = MagicMock()
    redis.__aenter__.return_value = redis
    redis.pubsub.return_value = subscription
    monkeypatch.setattr(live.Redis, "from_url", lambda *args, **kwargs: redis)
    verify = MagicMock(return_value={
        "org_id": "org_verified",
        "permissions": ["school:manage"],
        "exp": time() + 60,
    })
    monkeypatch.setattr(live, "verify_workos_access_token", verify)

    with TestClient(create_app()).websocket_connect(
        f"{PATH}?organization_id=org_other", headers={
            "origin": "https://school.example",
            "x-forwarded-host": "school.example",
            "sec-fetch-site": "same-origin",
        },
    ) as socket:
        socket.send_text("workos-token")
        assert socket.receive_json() == {"type": "invitations.ready"}
        assert socket.receive_json() == {"type": "invitations.changed"}

    verify.assert_called_once_with("workos-token")
    subscription.subscribe.assert_awaited_once_with(live.invitation_channel("org_verified"))


@pytest.mark.parametrize("claims", [None, {"org_id": "org_one", "permissions": []}, {
    "permissions": ["school:manage"],
}])
def test_websocket_rejects_invalid_or_unauthorized_sessions(monkeypatch, claims):
    def verify(_token):
        if claims is None:
            raise HTTPException(401)
        return claims

    monkeypatch.setattr(live, "verify_workos_access_token", verify)
    subscribe = AsyncMock()
    monkeypatch.setattr(live, "forward_invitation_events", subscribe)

    with TestClient(create_app()).websocket_connect(PATH, headers=SAME_ORIGIN) as socket:
        socket.send_text("workos-token")
        with pytest.raises(WebSocketDisconnect) as rejected:
            socket.receive_json()
    assert rejected.value.code == 1008
    subscribe.assert_not_called()


def test_websocket_rejects_a_different_browser_origin():
    with pytest.raises(WebSocketDisconnect) as rejected:
        with TestClient(create_app()).websocket_connect(
            PATH, headers={"origin": "https://other.example"},
        ):
            pytest.fail("A different origin must not be accepted")
    assert rejected.value.code == 1008


@pytest.mark.asyncio
async def test_worker_publishes_after_the_send_result_is_visible(db_session, monkeypatch):
    invitation = Invitation(
        organization_id="org_worker",
        email="teacher@example.test",
        send_status=InvitationSendStatus.QUEUED,
    )
    db_session.add(invitation)
    await db_session.commit()
    monkeypatch.setattr(services, "_send_workos_invitation", AsyncMock(
        return_value=SimpleNamespace(id="invitation_workos", state="pending"),
    ))

    async def publish(organization_id):
        await db_session.refresh(invitation)
        assert invitation.organization_id == organization_id
        assert invitation.send_status == InvitationSendStatus.SENT
        assert invitation.workos_invitation_id == "invitation_workos"

    publisher = AsyncMock(side_effect=publish)
    monkeypatch.setattr(services, "publish_invitation_change", publisher)

    await services.process_invitation(invitation.id)

    publisher.assert_awaited_once_with("org_worker")
