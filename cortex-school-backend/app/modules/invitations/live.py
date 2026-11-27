import asyncio
import logging
from time import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from core.auth import Permission, verify_workos_access_token
from core.config import settings

router = APIRouter(prefix="/api/invitations")
logger = logging.getLogger(__name__)
INVITATIONS_CHANGED = "invitations.changed"


def invitation_channel(organization_id: str) -> str:
    return f"cortex:{settings.ENVIRONMENT}:invitations:{organization_id}"


async def publish_invitation_change(organization_id: str) -> None:
    try:
        async with asyncio.timeout(1), Redis.from_url(settings.CELERY_BROKER_URL) as redis:
            await redis.publish(invitation_channel(organization_id), INVITATIONS_CHANGED)
    except (RedisError, TimeoutError):
        logger.warning("Could not publish an invitation status update")


def matches_origin(socket: WebSocket) -> bool:
    # The frontend proxy replaces X-Forwarded-Host with the public request host.
    host = socket.headers.get("x-forwarded-host") or socket.headers.get("host", "")
    try:
        origin = urlsplit(socket.headers.get("origin", ""))
    except ValueError:
        return False
    return (
        origin.scheme in {"http", "https"}
        and bool(host)
        and origin.netloc.casefold() == host.casefold()
        and socket.headers.get("sec-fetch-site", "same-origin") == "same-origin"
    )


async def forward_invitation_events(socket: WebSocket, organization_id: str) -> None:
    async with Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True) as redis:
        async with redis.pubsub() as subscription:
            async with asyncio.timeout(3):
                await subscription.subscribe(invitation_channel(organization_id))
                await subscription.get_message(timeout=None)
            await socket.send_json({"type": "invitations.ready"})
            async for message in subscription.listen():
                if message["type"] == "subscribe":
                    # Redis may reconnect and resubscribe after missing events.
                    await socket.send_json({"type": "invitations.ready"})
                elif message["type"] == "message" and message["data"] == INVITATIONS_CHANGED:
                    await socket.send_json({"type": INVITATIONS_CHANGED})


@router.websocket("/ws")
async def invitation_updates(socket: WebSocket) -> None:
    if not matches_origin(socket):
        await socket.close(code=1008)
        return

    await socket.accept()
    try:
        async with asyncio.timeout(5):
            frame = await socket.receive()
            if frame["type"] == "websocket.disconnect":
                return
            token = frame.get("text")
            if not token or len(token) > 16384:
                await socket.close(code=1008)
                return
            claims = await run_in_threadpool(verify_workos_access_token, token)
    except (HTTPException, TimeoutError):
        await socket.close(code=1008)
        return

    organization_id = claims.get("org_id")
    permissions = claims.get("permissions")
    if not (
        isinstance(organization_id, str)
        and organization_id
        and isinstance(permissions, list)
        and Permission.SCHOOL_MANAGE in permissions
    ):
        await socket.close(code=1008)
        return

    events = asyncio.create_task(forward_invitation_events(socket, organization_id))
    disconnect = asyncio.create_task(socket.receive())
    try:
        async with asyncio.timeout(max(0, float(claims["exp"]) - time())):
            done, _ = await asyncio.wait({events, disconnect}, return_when=asyncio.FIRST_COMPLETED)
            if disconnect in done and disconnect.result()["type"] == "websocket.disconnect":
                return
            if events in done:
                events.result()
    except WebSocketDisconnect:
        return
    except RedisError:
        await socket.close(code=1013)
    except TimeoutError:
        await socket.close(code=1013 if events.done() else 1008)
    else:
        await socket.close(code=1000)
    finally:
        for task in (events, disconnect):
            task.cancel()
        await asyncio.gather(events, disconnect, return_exceptions=True)
