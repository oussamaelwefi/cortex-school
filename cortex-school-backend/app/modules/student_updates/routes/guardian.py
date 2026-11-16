import uuid

from fastapi import Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.db import db_session
from core.router import APIRouter
from modules.student_registration.services import require_active_guardian
from modules.student_updates.models import StudentUpdateStatus
from modules.student_updates.schemas import (
    GuardianFeedItemResponse,
    GuardianUpdateDetailResponse,
    GuardianUpdateEventResponse,
    StudentUpdateMessageRequest,
    StudentUpdateNotificationResponse,
)
from modules.student_updates.services import (
    acknowledge_guardian_update,
    add_guardian_reply,
    build_guardian_event_response,
    build_guardian_feed_item,
    list_guardian_events,
    list_guardian_feed,
    list_guardian_notifications,
    mark_guardian_notification_read,
    mark_guardian_update_read,
    require_guardian_recipient,
)


router = APIRouter(
    prefix="/guardian",
    tags=["Guardian Student Updates"],
    dependencies=[Depends(require_active_guardian)],
)


@router.get("/feed/", response_model=list[GuardianFeedItemResponse])
async def list_feed(
    update_status: StudentUpdateStatus | None = Query(default=None, alias="status"),
    unread_only: bool = Query(default=False),
    overdue_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await list_guardian_feed(
        session,
        current_user,
        student_id=None,
        update_status=update_status,
        unread_only=unread_only,
        overdue_only=overdue_only,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/students/{student_id}/feed/",
    response_model=list[GuardianFeedItemResponse],
)
async def list_student_feed(
    student_id: uuid.UUID,
    update_status: StudentUpdateStatus | None = Query(default=None, alias="status"),
    unread_only: bool = Query(default=False),
    overdue_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await list_guardian_feed(
        session,
        current_user,
        student_id=student_id,
        update_status=update_status,
        unread_only=unread_only,
        overdue_only=overdue_only,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/updates/{recipient_id}/",
    response_model=GuardianUpdateDetailResponse,
)
async def get_update(
    recipient_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    row = await require_guardian_recipient(session, recipient_id, current_user)
    feed_item = build_guardian_feed_item(*row)
    history = await list_guardian_events(
        session, recipient_id, current_user["user_id"]
    )
    return GuardianUpdateDetailResponse(
        **feed_item.model_dump(),
        history=history,
    )


@router.post(
    "/updates/{recipient_id}/read/",
    response_model=GuardianFeedItemResponse,
)
async def mark_update_read(
    recipient_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    row = await mark_guardian_update_read(session, recipient_id, current_user)
    return build_guardian_feed_item(*row)


@router.post(
    "/updates/{recipient_id}/acknowledge/",
    response_model=GuardianFeedItemResponse,
)
async def acknowledge_update(
    recipient_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    row = await acknowledge_guardian_update(session, recipient_id, current_user)
    return build_guardian_feed_item(*row)


@router.post(
    "/updates/{recipient_id}/replies/",
    response_model=GuardianUpdateEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reply_to_update(
    recipient_id: uuid.UUID,
    payload: StudentUpdateMessageRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    event = await add_guardian_reply(
        session, recipient_id, payload.content, current_user
    )
    return build_guardian_event_response(event, current_user["user_id"])


@router.get(
    "/notifications/",
    response_model=list[StudentUpdateNotificationResponse],
)
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await list_guardian_notifications(
        session,
        current_user,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/notifications/{notification_id}/read/",
    response_model=StudentUpdateNotificationResponse,
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await mark_guardian_notification_read(
        session, notification_id, current_user
    )
