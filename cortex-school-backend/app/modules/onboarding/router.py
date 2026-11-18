import uuid

from fastapi import Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.db import db_session
from core.router import APIRouter
from modules.onboarding.models import SchoolRequest, SchoolRequestStatus
from modules.onboarding.schemas import (
    OnboardingCountryResponse, SchoolRequestCreate, SchoolRequestRejection, SchoolRequestResponse,
)
from modules.onboarding.services import create_school_request, review_school_request
from modules.onboarding.tasks import enqueue_school_provisioning
from modules.schools.models import Country


router = APIRouter(prefix="/school-requests", tags=["School Onboarding"])


@router.get("/countries", response_model=list[OnboardingCountryResponse])
async def onboarding_countries(session: AsyncSession = Depends(db_session), current_user: dict = Depends(get_current_user)):
    return (await session.scalars(select(Country).order_by(Country.name))).all()


@router.get("/mine", response_model=list[SchoolRequestResponse])
async def my_school_requests(session: AsyncSession = Depends(db_session), current_user: dict = Depends(get_current_user)):
    return (await session.scalars(select(SchoolRequest).where(
        SchoolRequest.requester_user_id == current_user["user_id"],
    ).order_by(SchoolRequest.created_at.desc()).limit(20))).all()


@router.post("/", response_model=SchoolRequestResponse, status_code=201)
async def request_school(payload: SchoolRequestCreate, session: AsyncSession = Depends(db_session),
                         current_user: dict = Depends(get_current_user)):
    return await create_school_request(session, payload, current_user["user_id"])


@router.post("/{request_id}/approve", response_model=SchoolRequestResponse)
async def approve_school_request(request_id: uuid.UUID, session: AsyncSession = Depends(db_session),
                                 current_user: dict = Depends(get_current_user)):
    result = await review_school_request(session, request_id, current_user["user_id"], approve=True)
    if result.status == SchoolRequestStatus.PROVISIONING:
        await run_in_threadpool(enqueue_school_provisioning, result.id)
    return result


@router.post("/{request_id}/reject", response_model=SchoolRequestResponse)
async def reject_school_request(request_id: uuid.UUID, payload: SchoolRequestRejection,
                                session: AsyncSession = Depends(db_session), current_user: dict = Depends(get_current_user)):
    return await review_school_request(session, request_id, current_user["user_id"], approve=False, reason=payload.reason)
