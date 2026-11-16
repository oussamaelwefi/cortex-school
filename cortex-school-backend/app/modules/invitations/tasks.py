import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.celery_app import celery_app
from modules.invitations.models import Invitation
from modules.invitations.services import (
    enqueue_invitation,
    mark_invitation_enqueue_failed,
    process_invitation,
)


@celery_app.task(
    name="invitations.process",
    rate_limit=settings.WORKOS_INVITATION_TASK_RATE_LIMIT,
)
def process_invitation_task(invitation_id: str) -> dict:
    return asyncio.run(process_invitation(uuid.UUID(invitation_id)))


async def enqueue_invitation_task(
    session: AsyncSession,
    invitation: Invitation,
) -> Invitation:
    task_id = str(uuid.uuid4())
    await enqueue_invitation(session, invitation, task_id)
    try:
        process_invitation_task.apply_async(
            args=[str(invitation.id)],
            task_id=task_id,
        )
    except Exception as exc:
        await mark_invitation_enqueue_failed(session, invitation, str(exc))
        raise
    return invitation
