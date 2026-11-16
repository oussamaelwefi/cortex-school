from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.schools.models import School
from modules.schools.schemas import (
    SchoolAISettingsRequest,
    SchoolAISettingsResponse,
    SchoolAttendanceSettingsRequest,
    SchoolAttendanceSettingsResponse,
)


router = APIRouter(
    prefix="/school",
    tags=["School Settings"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
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


@router.get(
    "/attendance-settings",
    response_model=SchoolAttendanceSettingsResponse,
)
async def get_school_attendance_settings(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await _get_current_school(session, current_user)


@router.put(
    "/attendance-settings",
    response_model=SchoolAttendanceSettingsResponse,
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
)
async def get_school_ai_settings(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await _get_current_school(session, current_user)


@router.put(
    "/ai-settings",
    response_model=SchoolAISettingsResponse,
)
async def replace_school_ai_settings(
    payload: SchoolAISettingsRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    school = await _get_current_school(session, current_user)
    school.ai_teacher_draft_enabled = payload.ai_teacher_draft_enabled
    school.ai_teacher_draft_default_language = payload.ai_teacher_draft_default_language.value
    school.ai_guardian_weekly_explanation_enabled = (
        payload.ai_guardian_weekly_explanation_enabled
    )
    school.ai_guardian_weekly_explanation_default_language = (
        payload.ai_guardian_weekly_explanation_default_language.value
    )
    await session.commit()
    await session.refresh(school)
    return school
