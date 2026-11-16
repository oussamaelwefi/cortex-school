import uuid
from datetime import date

from fastapi import Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.db import db_session
from core.router import APIRouter
from modules.ai.guardian_weekly import guardian_weekly_explanation_service
from modules.ai.schemas import (
    GuardianWeeklyExplanationRequest,
    GuardianWeeklyExplanationResponse,
)
from modules.reminders.policy import list_policy_files
from modules.reminders.policy_pdf import PDF_DOWNLOAD_RESPONSES, policy_pdf_download
from modules.reminders.schemas import SchoolPolicyFileResponse
from modules.student_registration.services import require_active_guardian

from .schemas import (
    GuardianFamilyFeedResponse,
    GuardianFamilyOverviewResponse,
    GuardianFamilyUpdateDetailResponse,
)
from .services import (
    get_family_feed,
    get_family_overview,
    get_family_update_detail,
)


router = APIRouter(
    prefix="/guardian/family",
    tags=["Guardian Family"],
    dependencies=[Depends(require_active_guardian)],
)


@router.get("/policies/", response_model=list[SchoolPolicyFileResponse])
async def list_guardian_school_policies(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await list_policy_files(session, current_user["organization_id"])


@router.get("/policies/{document_id}/pdf/", response_class=Response, responses=PDF_DOWNLOAD_RESPONSES)
async def download_guardian_school_policy(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await policy_pdf_download(session, current_user["organization_id"], document_id)


@router.get("/", response_model=GuardianFamilyOverviewResponse)
async def family_overview(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    school_date, school_timezone, children, requests = await get_family_overview(
        session, current_user
    )
    return GuardianFamilyOverviewResponse(
        school_date=school_date,
        school_timezone=school_timezone,
        children=children,
        registration_requests=requests,
    )


@router.get(
    "/students/{student_id}/feed/",
    response_model=GuardianFamilyFeedResponse,
)
async def family_student_feed(
    student_id: uuid.UUID,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    unread_only: bool = Query(default=False),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await get_family_feed(
        session,
        student_id,
        current_user,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
        from_date=from_date,
        to_date=to_date,
    )


@router.post(
    "/students/{student_id}/weekly-explanation/",
    response_model=GuardianWeeklyExplanationResponse,
    status_code=status.HTTP_200_OK,
)
async def create_family_weekly_explanation(
    student_id: uuid.UUID,
    payload: GuardianWeeklyExplanationRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await guardian_weekly_explanation_service.generate(
        session=session,
        student_id=student_id,
        current_user=current_user,
        output_language=payload.output_language,
        request_id=getattr(request.state, "request_id", "unknown"),
    )


@router.get(
    "/students/{student_id}/updates/{recipient_id}/",
    response_model=GuardianFamilyUpdateDetailResponse,
)
async def family_update_detail(
    student_id: uuid.UUID,
    recipient_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await get_family_update_detail(
        session, student_id, recipient_id, current_user
    )
