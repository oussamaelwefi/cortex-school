import asyncio
import logging
import uuid

from fastapi import HTTPException
from openai import APIError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.llm import LLMNotConfiguredError
from core.db import utcnow
from modules.members.services import load_member_summaries
from modules.reminders.agent import InvalidReminderDraft, PolicyNotFound, draft_reminder
from modules.reminders.models import ReminderDelivery, ReminderProposal
from modules.reminders.schemas import ReminderProposalResponse, ReminderReviewResponse
from modules.student_updates.acknowledgements import overdue_guardian_acknowledgements
from modules.student_updates.models import StudentUpdate, StudentUpdateRecipient
from modules.students.models import GuardianStudent, Student


logger = logging.getLogger(__name__)


async def get_notice(session: AsyncSession, organization_id: str, update_id: uuid.UUID, *, lock=False):
    query = select(StudentUpdate).where(
        StudentUpdate.id == update_id, StudentUpdate.organization_id == organization_id
    )
    if lock:
        query = query.with_for_update()
    notice = await session.scalar(query)
    if notice is None:
        raise HTTPException(404, "School notice not found.")
    return notice


async def pending_guardians(session: AsyncSession, organization_id: str, update_id: uuid.UUID):
    query = overdue_guardian_acknowledgements(
        select(
            GuardianStudent.guardian_workos_user_id,
            StudentUpdateRecipient.id,
            Student.first_name,
            Student.last_name,
        ).select_from(StudentUpdate),
        organization_id,
        utcnow(),
    ).where(StudentUpdate.id == update_id).order_by(
        GuardianStudent.guardian_workos_user_id, StudentUpdateRecipient.id
    )
    recipients: dict[str, list[dict]] = {}
    for guardian_id, recipient_id, first_name, last_name in (await session.execute(query)).all():
        recipients.setdefault(guardian_id, []).append({
            "recipient_id": str(recipient_id),
            "name": f"{first_name} {last_name}",
        })
    return recipients


async def get_proposal(session: AsyncSession, notice: StudentUpdate):
    return await session.scalar(select(ReminderProposal).where(
        ReminderProposal.update_id == notice.id,
        ReminderProposal.organization_id == notice.organization_id,
    ))


async def proposal_deliveries(session: AsyncSession, proposal_id: uuid.UUID):
    return (await session.scalars(select(ReminderDelivery).where(
        ReminderDelivery.proposal_id == proposal_id
    ).order_by(
        ReminderDelivery.guardian_name, ReminderDelivery.guardian_id
    ))).all()


async def review_response(session: AsyncSession, notice: StudentUpdate) -> ReminderReviewResponse:
    proposal = await get_proposal(session, notice)
    audience = await pending_guardians(session, notice.organization_id, notice.id)
    return ReminderReviewResponse(
        update_id=notice.id,
        title=notice.title,
        due_at=notice.due_at,
        needs_reminder=bool(
            notice.requires_acknowledgement and notice.due_at and notice.due_at < utcnow()
        ),
        pending_guardian_count=len(audience),
        proposal=ReminderProposalResponse(
            id=proposal.id,
            status=proposal.status,
            message=proposal.approved_message or proposal.draft_message,
            sources=proposal.sources,
            recipients=await proposal_deliveries(session, proposal.id),
            approved_at=proposal.approved_at,
            completed_at=proposal.completed_at,
        ) if proposal is not None else None,
    )


async def prepare_reminder(
    session: AsyncSession, organization_id: str, update_id: uuid.UUID, message: str | None = None
) -> ReminderReviewResponse:
    async with session.begin():
        notice = await get_notice(session, organization_id, update_id)
        if await get_proposal(session, notice) is not None:
            return await review_response(session, notice)
        audience = await pending_guardians(session, organization_id, update_id)
        if not audience:
            raise HTTPException(409, "No overdue guardian acknowledgements remain for this notice.")
        context = {
            "title": notice.title,
            "notice": (notice.body or "")[:2000],
            "due_at": notice.due_at.isoformat(),
            "pending_guardian_count": len(audience),
        }

    sources = []
    if message is None:
        try:
            message, sources = await draft_reminder(session, organization_id, context)
        except PolicyNotFound as exc:
            raise HTTPException(422, "No relevant school policy was found. Add a policy for this notice and try again.") from exc
        except LLMNotConfiguredError as exc:
            raise HTTPException(503, "The reminder assistant is not configured.") from exc
        except (APIError, InvalidReminderDraft, ValidationError, TimeoutError) as exc:
            logger.warning("reminder_draft_failed", extra={"error_type": type(exc).__name__})
            raise HTTPException(502, "The assistant could not produce a cited reminder. Try again.") from exc

    try:
        members = await asyncio.wait_for(
            load_member_summaries(organization_id, set(audience), tolerate_errors=True), timeout=3
        )
    except TimeoutError:
        members = {}

    async with session.begin():
        notice = await get_notice(session, organization_id, update_id, lock=True)
        if await get_proposal(session, notice) is not None:
            return await review_response(session, notice)
        audience = await pending_guardians(session, organization_id, update_id)
        if not audience:
            raise HTTPException(409, "No overdue guardian acknowledgements remain for this notice.")
        proposal = ReminderProposal(
            organization_id=organization_id,
            update_id=update_id,
            draft_message=message,
            sources=[source.model_dump(mode="json") for source in sources],
        )
        session.add(proposal)
        await session.flush()
        session.add_all([
            ReminderDelivery(
                proposal_id=proposal.id,
                guardian_id=guardian_id,
                guardian_name=members[guardian_id].name[:255] if guardian_id in members else None,
                students=students,
            )
            for guardian_id, students in audience.items()
        ])
        return await review_response(session, notice)


async def approve_reminder(
    session: AsyncSession, organization_id: str, proposal_id: uuid.UUID, user_id: str,
    message: str, *, include_policy_sources: bool = True,
) -> ReminderReviewResponse:
    async with session.begin():
        proposal = await session.scalar(select(ReminderProposal).where(
            ReminderProposal.id == proposal_id, ReminderProposal.organization_id == organization_id
        ).with_for_update())
        if proposal is None:
            raise HTTPException(404, "Reminder proposal not found.")
        if proposal.status == "draft":
            proposal.status = "queued"
            proposal.approved_at = utcnow()
            proposal.approved_by = user_id
            proposal.approved_message = message
            if not include_policy_sources:
                proposal.sources = []
        elif proposal.approved_message != message:
            raise HTTPException(409, "This proposal has already been approved with a different message.")
        notice = await get_notice(session, organization_id, proposal.update_id)
        return await review_response(session, notice)
