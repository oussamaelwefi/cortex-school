import csv
import io
import uuid
from dataclasses import dataclass
from datetime import timedelta
from email.utils import parseaddr
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from workos import AsyncWorkOSClient
from workos.user_management.models import UserInvite

from core.config import settings
from core.db import SessionLocal, utcnow
from modules.invitations.models import (
    Invitation,
    InvitationCsvRoleMode,
    InvitationSendStatus,
    UserRoles,
)

INVITATION_EXPIRES_IN_DAYS = 7
NON_REQUEUEABLE_SEND_STATUSES = {
    InvitationSendStatus.QUEUED,
    InvitationSendStatus.PROCESSING,
    InvitationSendStatus.SENT,
}


def _ensure_same_organization(
    invitation_organization_id: str, current_user: dict
) -> None:
    if invitation_organization_id != current_user.get("organization_id"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found",
        )


@dataclass(frozen=True)
class CsvInvitation:
    email: str
    first_name: str | None = None
    last_name: str | None = None
    role_slug: UserRoles | None = None


class InvitationCsvError(ValueError):
    pass


@dataclass(frozen=True)
class InvitationCsvUpsertResult:
    invitations: list[Invitation]
    created_count: int
    updated_count: int


def parse_invitation_csv(
    csv_content: str,
    *,
    role_mode: InvitationCsvRoleMode | None = None,
) -> list[CsvInvitation]:
    reader = csv.DictReader(io.StringIO(csv_content))
    if not reader.fieldnames:
        raise InvitationCsvError("CSV must include a header row")

    fieldnames = [field.strip().lower() for field in reader.fieldnames if field]
    if "email" not in fieldnames:
        raise InvitationCsvError("CSV must include an email column")
    if role_mode == InvitationCsvRoleMode.MIXED and "role_slug" not in fieldnames:
        raise InvitationCsvError("Mixed imports require a role_slug column.")

    invitations: list[CsvInvitation] = []
    seen_emails: set[str] = set()

    for row_number, raw_row in enumerate(reader, start=2):
        row: dict[str, str] = {}
        for key, value in raw_row.items():
            if key is None:
                continue
            row[key.strip().lower()] = (value or "").strip()

        if not any(row.values()):
            continue

        email = row.get("email", "").lower()
        if not _is_valid_email(email):
            raise InvitationCsvError(f"Row {row_number} has an invalid email")
        if email in seen_emails:
            raise InvitationCsvError(f"Row {row_number} duplicates {email}")
        seen_emails.add(email)

        if role_mode is not None and role_mode != InvitationCsvRoleMode.MIXED:
            role_slug = UserRoles(role_mode)
        else:
            if role_mode == InvitationCsvRoleMode.MIXED and not row.get("role_slug"):
                raise InvitationCsvError(
                    f"Row {row_number} must include a role_slug in mixed mode."
                )
            role_slug = _parse_optional_user_role(row.get("role_slug"), row_number)

        invitations.append(
            CsvInvitation(
                email=email,
                first_name=row.get("first_name") or None,
                last_name=row.get("last_name") or None,
                role_slug=role_slug,
            )
        )

    if not invitations:
        raise InvitationCsvError("CSV does not contain any invitation rows")

    return invitations


async def create_invitations_from_csv(
    session: AsyncSession,
    *,
    csv_content: str,
    organization_id: str,
    created_by_user_id: str | None,
    role_mode: InvitationCsvRoleMode | None = None,
) -> InvitationCsvUpsertResult:
    csv_invitations = parse_invitation_csv(csv_content, role_mode=role_mode)
    existing_by_email = await _get_existing_invitations(
        session,
        organization_id=organization_id,
        emails=[invitation.email for invitation in csv_invitations],
    )

    # Validate the entire batch before changing records. A worker must not see
    # a queued invitation's role change underneath it, nor should sent roles
    # diverge from the role already handed to WorkOS.
    for row in csv_invitations:
        existing = existing_by_email.get(row.email)
        if existing is not None and not should_enqueue_invitation(existing) and (
            existing.role_slug or UserRoles.GUARDIAN
        ) != row.role_slug:
            raise InvitationCsvError(
                f"{row.email} already has a queued or sent invitation with a different role."
            )

    invitations: list[Invitation] = []
    created_count = 0
    updated_count = 0
    for csv_invitation in csv_invitations:
        invitation = existing_by_email.get(csv_invitation.email)
        if invitation is None:
            invitation = Invitation(
                organization_id=organization_id,
                created_by_user_id=created_by_user_id,
                email=csv_invitation.email,
                send_status=InvitationSendStatus.PENDING,
            )
            session.add(invitation)
            created_count += 1
        else:
            if not should_enqueue_invitation(invitation):
                invitations.append(invitation)
                continue
            updated_count += 1

        invitation.created_by_user_id = created_by_user_id
        invitation.first_name = csv_invitation.first_name
        invitation.last_name = csv_invitation.last_name
        invitation.role_slug = csv_invitation.role_slug
        invitation.expires_in_days = INVITATION_EXPIRES_IN_DAYS

        if should_enqueue_invitation(invitation):
            invitation.send_status = InvitationSendStatus.PENDING
            invitation.celery_task_id = None
            invitation.workos_invitation_id = None
            invitation.workos_state = None
            invitation.error_message = None
            invitation.expires_at = None
            invitation.sent_at = None

        invitations.append(invitation)

    await session.commit()
    for invitation in invitations:
        await session.refresh(invitation)
    return InvitationCsvUpsertResult(
        invitations=invitations,
        created_count=created_count,
        updated_count=updated_count,
    )


def should_enqueue_invitation(invitation: Invitation) -> bool:
    return invitation.send_status not in NON_REQUEUEABLE_SEND_STATUSES


async def enqueue_invitation(
    session: AsyncSession, invitation: Invitation, task_id: str
) -> Invitation:
    invitation.celery_task_id = task_id
    invitation.send_status = InvitationSendStatus.QUEUED
    invitation.error_message = None
    await session.commit()
    await session.refresh(invitation)
    return invitation


async def mark_invitation_enqueue_failed(
    session: AsyncSession, invitation: Invitation, error_message: str
) -> Invitation:
    invitation.send_status = InvitationSendStatus.FAILED
    invitation.error_message = error_message
    await session.commit()
    await session.refresh(invitation)
    return invitation


async def get_invitation(session: AsyncSession, invitation_id: uuid.UUID) -> Invitation:
    result = await session.execute(
        select(Invitation).where(Invitation.id == invitation_id)
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise LookupError("Invitation not found")
    return invitation


async def list_invitations(
    session: AsyncSession,
    *,
    organization_id: str,
) -> list[Invitation]:
    result = await session.execute(
        select(Invitation)
        .where(Invitation.organization_id == organization_id)
        .order_by(Invitation.created_at.desc())
    )
    return list(result.scalars().all())


async def process_invitation(invitation_id: uuid.UUID) -> dict[str, Any]:
    async with SessionLocal() as session:
        invitation = await get_invitation(session, invitation_id)
        invitation.send_status = InvitationSendStatus.PROCESSING
        invitation.error_message = None
        invitation.attempt_count += 1
        await session.commit()

        try:
            workos_invitation = await _send_workos_invitation(invitation)
            invitation.send_status = InvitationSendStatus.SENT
            invitation.workos_invitation_id = workos_invitation.id
            invitation.workos_state = workos_invitation.state
            invitation.sent_at = utcnow()
            invitation.expires_at = getattr(
                workos_invitation,
                "expires_at",
                None,
            ) or invitation.sent_at + timedelta(days=invitation.expires_in_days)
        except Exception as exc:
            invitation.send_status = InvitationSendStatus.FAILED
            invitation.error_message = str(exc)

        await session.commit()
        await session.refresh(invitation)
        return {
            "id": str(invitation.id),
            "email": invitation.email,
            "send_status": invitation.send_status,
            "attempt_count": invitation.attempt_count,
        }


async def _send_workos_invitation(invitation: Invitation) -> UserInvite:
    if not settings.WORKOS_API_KEY:
        raise RuntimeError("WORKOS_API_KEY is not configured")

    async with AsyncWorkOSClient(api_key=settings.WORKOS_API_KEY) as client:
        return await client.user_management.send_invitation(
            email=invitation.email,
            organization_id=invitation.organization_id,
            role_slug=(invitation.role_slug or UserRoles.GUARDIAN).value,
            expires_in_days=invitation.expires_in_days,
            request_options={
                "base_url": settings.WORKOS_API_BASE_URL,
                "timeout": 20,
                "max_retries": 0,
            },
        )


async def _get_existing_invitations(
    session: AsyncSession,
    *,
    organization_id: str,
    emails: list[str],
) -> dict[str, Invitation]:
    result = await session.execute(
        select(Invitation).where(
            Invitation.organization_id == organization_id,
            Invitation.email.in_(emails),
        )
    )
    return {invitation.email: invitation for invitation in result.scalars().all()}


def _parse_optional_user_role(value: str | None, row_number: int) -> UserRoles | None:
    if not value:
        return UserRoles.GUARDIAN

    try:
        return UserRoles(value)
    except ValueError as exc:
        valid_roles = ", ".join(role.value for role in UserRoles)
        raise InvitationCsvError(
            f"Row {row_number} has an invalid role_slug. Use one of: {valid_roles}"
        ) from exc


def _is_valid_email(email: str) -> bool:
    parsed_email = parseaddr(email)[1]
    return parsed_email == email and "@" in email
