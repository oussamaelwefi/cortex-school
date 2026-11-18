import logging
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from workos import AsyncWorkOSClient, ConflictError, NotFoundError, WorkOSError
from workos.organization_membership import RoleSingle

from core.auth import WORKOS_CLIENT_ID, is_workos_operator
from core.config import settings
from core.db import SessionLocal, utcnow
from modules.onboarding.models import SchoolRequest, SchoolRequestStatus as Status
from modules.onboarding.schemas import SchoolRequestCreate
from modules.schools.models import Country, School


logger = logging.getLogger(__name__)
OPEN_STATUSES = [Status.PENDING, Status.PROVISIONING, Status.FAILED]


def workos_client() -> AsyncWorkOSClient:
    if not settings.WORKOS_API_KEY:
        raise HTTPException(503, "School onboarding is not configured. Contact the platform operator.")
    return AsyncWorkOSClient(
        api_key=settings.WORKOS_API_KEY, client_id=WORKOS_CLIENT_ID,
        base_url=settings.WORKOS_API_BASE_URL, request_timeout=20, max_retries=0,
    )


def require_operator(user_id: str) -> None:
    if not is_workos_operator(user_id):
        raise HTTPException(403, "WorkOS operator access is required")


async def create_school_request(session: AsyncSession, payload: SchoolRequestCreate, user_id: str) -> SchoolRequest:
    existing = await session.scalar(select(SchoolRequest).where(
        SchoolRequest.requester_user_id == user_id, SchoolRequest.status.in_(OPEN_STATUSES),
    ))
    if existing:
        raise HTTPException(409, "You already have a school request awaiting completion.")
    if await session.get(Country, payload.country_code) is None:
        raise HTTPException(422, "Choose one of the available countries.")
    try:
        async with workos_client() as client:
            user = await client.user_management.get_user(user_id)
    except (WorkOSError, httpx.HTTPError) as exc:
        raise HTTPException(503, "Unable to verify your account. Please try again.") from exc
    if not user.email_verified:
        raise HTTPException(403, "Verify your email address before requesting a school.")
    school_request = SchoolRequest(
        requester_user_id=user_id, requester_email=user.email,
        requester_name=(" ".join(filter(None, [user.first_name, user.last_name])) or user.email)[:255],
        **payload.model_dump(),
    )
    session.add(school_request)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "You already have a school request awaiting completion.") from exc
    await session.refresh(school_request)
    return school_request


async def review_school_request(session: AsyncSession, request_id: uuid.UUID, operator_id: str,
                                *, approve: bool, reason: str = "") -> SchoolRequest:
    require_operator(operator_id)
    school_request = await session.scalar(select(SchoolRequest).where(SchoolRequest.id == request_id).with_for_update())
    if school_request is None:
        raise HTTPException(404, "School request not found")
    if approve:
        if school_request.status in (Status.APPROVED, Status.PROVISIONING):
            return school_request
        if school_request.status not in (Status.PENDING, Status.FAILED):
            raise HTTPException(409, "This request has already been rejected.")
        school_request.status = Status.PROVISIONING
        school_request.last_error = None
    else:
        if school_request.status != Status.PENDING:
            raise HTTPException(409, "Only pending requests can be rejected.")
        if not reason.strip():
            raise HTTPException(422, "Provide a reason for rejecting the request.")
        school_request.status = Status.REJECTED
        school_request.rejection_reason = reason.strip()[:1000]
    # Preserve the original approval audit record when retrying provisioning.
    if school_request.reviewed_at is None:
        school_request.reviewed_by = operator_id
        school_request.reviewed_at = utcnow()
    await session.commit()
    await session.refresh(school_request)
    return school_request


async def _ensure_organization(client, school_request: SchoolRequest):
    external_id = f"cortex-school:{school_request.id}"
    if school_request.organization_id:
        organization = await client.organizations.get_organization(school_request.organization_id)
    else:
        try:
            organization = await client.organizations.get_organization_by_external_id(external_id)
        except NotFoundError:
            try:
                organization = await client.organizations.create_organization(
                    name=school_request.school_name, external_id=external_id,
                    metadata={"cortex_school_request_id": str(school_request.id)},
                )
            except ConflictError:
                organization = await client.organizations.get_organization_by_external_id(external_id)
    if organization.external_id != external_id:
        raise ValueError("Organization external ID does not match this request")
    return organization


async def _ensure_admin_membership(client, school_request: SchoolRequest):
    memberships = await client.organization_membership.list_organization_memberships(
        user_id=school_request.requester_user_id, organization_id=school_request.organization_id,
    )
    membership = next(iter(memberships.data), None)
    if membership is None:
        return await client.organization_membership.create_organization_membership(
            user_id=school_request.requester_user_id, organization_id=school_request.organization_id,
            role=RoleSingle(role_slug="school_admin"),
        )
    if membership.status != "active":
        raise ValueError("The requester's membership is not active; review it in WorkOS before retrying")
    if membership.role.slug != "school_admin":
        return await client.organization_membership.update_organization_membership(
            membership.id, role=RoleSingle(role_slug="school_admin"),
        )
    return membership


async def process_school_request(request_id: uuid.UUID) -> str:
    async with SessionLocal() as session:
        # Hold this row lock through the external calls. Other workers skip it;
        # a crashed worker releases the lock and the scheduled sweep resumes it.
        school_request = await session.scalar(select(SchoolRequest).where(
            SchoolRequest.id == request_id, SchoolRequest.status == Status.PROVISIONING,
        ).with_for_update(skip_locked=True))
        if school_request is None:
            return "skipped"
        school_request.attempt_count += 1
        school_request.last_attempt_at = utcnow()
        try:
            async with workos_client() as client:
                user = await client.user_management.get_user(school_request.requester_user_id)
                if not user.email_verified or user.email.lower() != school_request.requester_email.lower():
                    raise ValueError("Requester email must still match the verified request")
                organization = await _ensure_organization(client, school_request)
                school_request.organization_id = organization.id
                membership = await _ensure_admin_membership(client, school_request)
                school_request.membership_id = membership.id
        except (WorkOSError, httpx.HTTPError, HTTPException, ValueError) as exc:
            school_request.status = Status.FAILED
            school_request.last_error = (
                f"Provisioning failed ({type(exc).__name__}). Check the WorkOS account, API key, "
                "and school_admin role, then retry."
            )
            # Persist any organization ID already obtained, so retries resume it.
            await session.commit()
            logger.warning("School provisioning failed request_id=%s error_type=%s", request_id, type(exc).__name__)
            return "failed"
        school = await session.get(School, organization.id)
        if school is None:
            session.add(School(organization_id=organization.id, country_code=school_request.country_code,
                               timezone=school_request.timezone))
        school_request.status = Status.APPROVED
        school_request.last_error = None
        school_request.completed_at = utcnow()
        await session.commit()
        return "approved"
