from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from workos import WorkOSClient, WorkOSError

from core.auth import WORKOS_CLIENT_ID
from core.config import settings
from core.db import db_session
from core.router import APIRouter
from modules.invitations.models import Invitation, InvitationSendStatus

PUBLIC = True

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
INVITATION_STATES = {
    "invitation.created": "pending",
    "invitation.resent": "pending",
    "invitation.accepted": "accepted",
    "invitation.revoked": "revoked",
}


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
    signature = request.headers.get("workos-signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing WorkOS signature",
        )

    try:
        with WorkOSClient(client_id=WORKOS_CLIENT_ID, is_public=True) as client:
            event = client.webhooks.verify_event(
                event_body=await request.body(),
                event_signature=signature,
                secret=settings.WORKOS_WEBHOOK_SECRET,
            )
    except (ValueError, WorkOSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid WorkOS webhook",
        ) from exc

    state = INVITATION_STATES.get(event.event)
    if state is None or not event.data.organization_id:
        return {"received": True}

    data = event.data
    match = Invitation.workos_invitation_id == data.id
    if state in {"accepted", "revoked"}:
        # Acceptance can arrive before the worker has saved the provider ID.
        match = or_(match, and_(
            Invitation.email == data.email.strip().lower(),
            Invitation.send_status == InvitationSendStatus.PROCESSING,
            Invitation.workos_invitation_id.is_(None),
        ))
    invitation = await session.scalar(
        select(Invitation).where(
            Invitation.organization_id == data.organization_id,
            match,
        ).with_for_update()
    )
    if invitation is None:
        return {"received": True}
    if invitation.workos_invitation_id != data.id:
        raise HTTPException(503, "Invitation is still being linked. Retry this event.")

    # Delayed creation or resend events must never undo acceptance or revocation.
    if invitation.workos_state == "accepted" or (
        state == "pending" and invitation.workos_state == "revoked"
    ):
        return {"received": True}

    invitation.workos_state = state
    if data.expires_at is not None and (
        state != "pending" or invitation.expires_at is None or data.expires_at >= invitation.expires_at
    ):
        invitation.expires_at = data.expires_at
    await session.commit()
    return {"received": True}
