import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.celery_app import celery_app
from core.db import DATABASE_URI, utcnow
from modules.reminders.models import ReminderDelivery, ReminderProposal
from modules.reminders.services import pending_guardians, proposal_deliveries
from modules.student_updates.models import (
    StudentUpdateActorRole,
    StudentUpdateEvent,
    StudentUpdateEventType,
    StudentUpdateNotification,
    StudentUpdateNotificationType,
    StudentUpdateRecipient,
)


logger = logging.getLogger(__name__)


async def deliver_queued_proposal(session: AsyncSession) -> bool:
    async with session.begin():
        proposal = await session.scalar(
            select(ReminderProposal)
            .where(ReminderProposal.status == "queued")
            .order_by(ReminderProposal.approved_at, ReminderProposal.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if proposal is None:
            return False

        deliveries = await proposal_deliveries(session, proposal.id)
        reviewed_ids = {
            uuid.UUID(student["recipient_id"])
            for delivery in deliveries for student in delivery.students
        }
        # Acknowledgements lock these same recipient rows. Read guardian state after
        # taking the locks so an acknowledgement that won the race prevents delivery.
        await session.execute(
            select(StudentUpdateRecipient.id)
            .where(StudentUpdateRecipient.id.in_(reviewed_ids))
            .order_by(StudentUpdateRecipient.id)
            .with_for_update()
        )
        current = await pending_guardians(session, proposal.organization_id, proposal.update_id)
        for delivery in deliveries:
            eligible_ids = {student["recipient_id"] for student in current.get(delivery.guardian_id, [])}
            recipient_id = next((
                uuid.UUID(student["recipient_id"])
                for student in delivery.students
                if student["recipient_id"] in eligible_ids
            ), None)
            if recipient_id is None:
                delivery.status = "skipped"
                delivery.outcome_reason = "The guardian no longer has a pending acknowledgement in the reviewed audience."
                continue
            await create_reminder_notification(session, proposal, delivery, recipient_id)

        proposal.status = "completed"
        proposal.completed_at = utcnow()
        return True


async def create_reminder_notification(
    session: AsyncSession, proposal: ReminderProposal, delivery: ReminderDelivery, recipient_id: uuid.UUID
) -> None:
    try:
        async with session.begin_nested():
            event = StudentUpdateEvent(
                recipient_id=recipient_id,
                event_type=StudentUpdateEventType.REMINDER_SENT,
                actor_workos_user_id=proposal.approved_by,
                actor_role=StudentUpdateActorRole.ADMIN,
            )
            session.add(event)
            await session.flush()
            session.add(StudentUpdateNotification(
                organization_id=proposal.organization_id,
                guardian_workos_user_id=delivery.guardian_id,
                recipient_id=recipient_id,
                event_id=event.id,
                notification_type=StudentUpdateNotificationType.ACKNOWLEDGEMENT_REMINDER,
                message=proposal.approved_message,
            ))
            await session.flush()
    except (DataError, IntegrityError):
        logger.exception("reminder_delivery_failed", extra={"delivery_id": str(delivery.id)})
        delivery.status = "failed"
        delivery.outcome_reason = "The in-app notification could not be stored."
    else:
        delivery.status = "sent"


async def drain_approved_reminders() -> int:
    engine = create_async_engine(DATABASE_URI, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            processed = 0
            while processed < 20 and await deliver_queued_proposal(session):
                processed += 1
            return processed
    finally:
        await engine.dispose()


@celery_app.task(name="reminders.deliver_approved")
def deliver_approved_reminders() -> int:
    return asyncio.run(drain_approved_reminders())
