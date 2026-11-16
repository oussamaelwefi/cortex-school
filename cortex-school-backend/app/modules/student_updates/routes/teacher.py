import uuid

from fastapi import Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.db import db_session
from core.router import APIRouter
from modules.student_updates.models import StudentUpdateStatus
from modules.student_updates.schemas import (
    StudentUpdateAudiencePreviewRequest,
    StudentUpdateAudiencePreviewResponse,
    StudentUpdateCreateRequest,
    StudentUpdateEventResponse,
    StudentUpdateMessageRequest,
    StudentUpdateRecipientResponse,
    StudentUpdateResponse,
    StudentUpdateStatusRequest,
)
from modules.student_updates.services import (
    add_teacher_feedback,
    build_recipient_response,
    build_update_response,
    change_teacher_recipient_status,
    create_student_update,
    list_recipient_events as list_events,
    list_teacher_updates,
    preview_teacher_update_audience,
    require_teacher_recipient,
    require_teacher_update,
)


router = APIRouter(prefix="/teacher/updates", tags=["Teacher Student Updates"])


@router.post(
    "/preview/",
    response_model=StudentUpdateAudiencePreviewResponse,
)
async def preview_update_audience(
    payload: StudentUpdateAudiencePreviewRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await preview_teacher_update_audience(session, payload, current_user)


@router.post(
    "/",
    response_model=StudentUpdateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_update(
    payload: StudentUpdateCreateRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    student_update = await create_student_update(session, payload, current_user)
    return await build_update_response(session, student_update)


@router.get("/", response_model=list[StudentUpdateResponse])
async def list_updates(
    classroom_id: uuid.UUID | None = Query(default=None),
    update_status: StudentUpdateStatus | None = Query(default=None, alias="status"),
    overdue_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await list_teacher_updates(
        session,
        current_user,
        classroom_id=classroom_id,
        update_status=update_status,
        overdue_only=overdue_only,
        limit=limit,
        offset=offset,
    )


@router.get("/{update_id}/", response_model=StudentUpdateResponse)
async def get_update(
    update_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    student_update, classroom = await require_teacher_update(
        session, update_id, current_user
    )
    return await build_update_response(session, student_update, classroom)


@router.post(
    "/{update_id}/recipients/{recipient_id}/feedback/",
    response_model=StudentUpdateEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_feedback(
    update_id: uuid.UUID,
    recipient_id: uuid.UUID,
    payload: StudentUpdateMessageRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    event = await add_teacher_feedback(
        session,
        update_id,
        recipient_id,
        payload.content,
        current_user,
    )
    return StudentUpdateEventResponse.model_validate(event)


@router.patch(
    "/{update_id}/recipients/{recipient_id}/status/",
    response_model=StudentUpdateRecipientResponse,
)
async def set_recipient_status(
    update_id: uuid.UUID,
    recipient_id: uuid.UUID,
    payload: StudentUpdateStatusRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    recipient, student_update, student = await change_teacher_recipient_status(
        session,
        update_id,
        recipient_id,
        payload.status,
        current_user,
    )
    return build_recipient_response(recipient, student, student_update.due_at)


@router.get(
    "/{update_id}/recipients/{recipient_id}/history/",
    response_model=list[StudentUpdateEventResponse],
)
async def list_recipient_events(
    update_id: uuid.UUID,
    recipient_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    await require_teacher_recipient(session, update_id, recipient_id, current_user)
    return await list_events(session, recipient_id)
