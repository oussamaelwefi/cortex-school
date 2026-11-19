import logging

import httpx
from core.auth import Permission, get_current_user, require_permission
from core.config import settings
from core.db import db_session
from core.router import APIRouter
from fastapi import Depends, HTTPException, Response, status
from modules.ai.chat_access import save_preference
from modules.ai.chat_data import selected_role
from modules.ai.schemas import ChatDataAccessResponse, ChatDataPreferenceRequest
from modules.onboarding.models import SchoolRequest, SchoolRequestStatus
from modules.publications.services import _active_viewer
from modules.schools.models import School
from modules.schools.schemas import (
    SchoolAISettingsRequest,
    SchoolAISettingsResponse,
    SchoolAttendanceSettingsRequest,
    SchoolAttendanceSettingsResponse,
    SchoolContextResponse,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from workos import AsyncWorkOSClient, WorkOSError

router = APIRouter(
    prefix="/school",
    tags=["School Settings"],
)
logger = logging.getLogger(__name__)
manage_school = [Depends(require_permission(Permission.SCHOOL_MANAGE))]


@router.put(
    "/chat-data-settings",
    response_model=ChatDataAccessResponse,
    dependencies=manage_school,
)
async def set_school_chat_data_access(
    payload: ChatDataPreferenceRequest,
    response: Response,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    selected_role(current_user, "admin")
    await _active_viewer(current_user, "school_admin")
    return await save_preference(
        session, current_user, enabled=payload.enabled, personal=False
    )


async def _get_current_school(
    session: AsyncSession,
    current_user: dict,
) -> School:
    school = await session.get(School, current_user.get("organization_id"))
    if school is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="School not found",
        )
    return school


@router.get("/context", response_model=SchoolContextResponse)
async def get_school_context(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    school = await _get_current_school(session, current_user)
    name = await session.scalar(
        select(SchoolRequest.school_name).where(
            SchoolRequest.organization_id == school.organization_id,
            SchoolRequest.status == SchoolRequestStatus.APPROVED,
        )
    )
    # Older schools may predate the onboarding workflow. Resolve their display
    # name without making the workspace depend on WorkOS availability.
    if not name and settings.WORKOS_API_KEY:
        try:
            async with AsyncWorkOSClient(
                api_key=settings.WORKOS_API_KEY,
                base_url=settings.WORKOS_API_BASE_URL,
                request_timeout=3,
                max_retries=0,
            ) as client:
                organization = await client.organizations.get_organization(
                    school.organization_id
                )
                name = organization.name
        except (WorkOSError, httpx.HTTPError):
            logger.warning("School display name is temporarily unavailable")
    return SchoolContextResponse(organization_id=school.organization_id, name=name)


@router.get(
    "/attendance-settings",
    response_model=SchoolAttendanceSettingsResponse,
    dependencies=manage_school,
)
async def get_school_attendance_settings(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await _get_current_school(session, current_user)


@router.put(
    "/attendance-settings",
    response_model=SchoolAttendanceSettingsResponse,
    dependencies=manage_school,
)
async def replace_school_attendance_settings(
    payload: SchoolAttendanceSettingsRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    school = await _get_current_school(session, current_user)
    school.timezone = payload.timezone
    school.instructional_weekdays = sorted(payload.instructional_weekdays)
    school.attendance_cutoff_time = payload.attendance_cutoff_time
    school.validate_attendance_settings()
    await session.commit()
    await session.refresh(school)
    return school


@router.get(
    "/ai-settings",
    response_model=SchoolAISettingsResponse,
    dependencies=manage_school,
)
async def get_school_ai_settings(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await _get_current_school(session, current_user)


@router.put(
    "/ai-settings",
    response_model=SchoolAISettingsResponse,
    dependencies=manage_school,
)
async def replace_school_ai_settings(
    payload: SchoolAISettingsRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    school = await _get_current_school(session, current_user)
    school.ai_teacher_draft_enabled = payload.ai_teacher_draft_enabled
    school.ai_teacher_draft_default_language = (
        payload.ai_teacher_draft_default_language.value
    )
    school.ai_guardian_weekly_explanation_enabled = (
        payload.ai_guardian_weekly_explanation_enabled
    )
    school.ai_guardian_weekly_explanation_default_language = (
        payload.ai_guardian_weekly_explanation_default_language.value
    )
    await session.commit()
    await session.refresh(school)
    return school
