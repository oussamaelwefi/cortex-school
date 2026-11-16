from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from workos import WorkOSClient

from core.config import settings
from core.db import db_session
from modules.invitations.models import Invitation

PUBLIC = True

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/workos/", include_in_schema=False)
async def handle_workos_webhook(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict[str, bool]:
    if not settings.WORKOS_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WORKOS_WEBHOOK_SECRET is not configured",
        )
    if not settings.WORKOS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WORKOS_API_KEY is not configured",
        )

    signature = request.headers.get("workos-signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing WorkOS signature",
        )

    try:
        with WorkOSClient(api_key=settings.WORKOS_API_KEY) as client:
            event = client.webhooks.verify_event(
                event_body=await request.body(),
                event_signature=signature,
                secret=settings.WORKOS_WEBHOOK_SECRET,
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid WorkOS signature",
        ) from exc

    if event.event in {
        "invitation.created",
        "invitation.resent",
        "invitation.accepted",
        "invitation.revoked",
    }:
        values: dict[str, object] = {}
        state = getattr(event.data, "state", None)
        values["workos_state"] = state or {
            "invitation.accepted": "accepted",
            "invitation.revoked": "revoked",
        }.get(event.event, "pending")
        expires_at = getattr(event.data, "expires_at", None)
        if expires_at is not None:
            values["expires_at"] = expires_at
        if values:
            await session.execute(
                update(Invitation)
                .where(Invitation.workos_invitation_id == event.data.id)
                .values(**values)
            )
        await session.commit()

    return {"received": True}
