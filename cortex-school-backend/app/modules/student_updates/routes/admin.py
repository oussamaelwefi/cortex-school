import uuid

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.student_updates.models import StudentUpdateStatus
from modules.student_updates.schemas import (
    AdminStudentUpdateItemResponse,
    AdminStudentUpdateSummaryResponse,
    StudentUpdateEventResponse,
    StudentUpdateResponse,
)
from modules.student_updates.services import (
    build_update_response,
    get_admin_summary,
    get_admin_update,
    list_admin_student_updates,
    list_recipient_events as list_events,
    require_admin_recipient,
)


router = APIRouter(
    prefix="/student-updates",
    tags=["Admin Student Updates"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@router.get("/summary/", response_model=AdminStudentUpdateSummaryResponse)
async def get_summary(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await get_admin_summary(session, current_user["organization_id"])


@router.get("/", response_model=list[AdminStudentUpdateItemResponse])
async def list_updates(
    classroom_id: uuid.UUID | None = Query(default=None),
    teacher_id: str | None = Query(default=None),
    student_id: uuid.UUID | None = Query(default=None),
    update_status: StudentUpdateStatus | None = Query(default=None, alias="status"),
    overdue_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await list_admin_student_updates(
        session,
        current_user["organization_id"],
        classroom_id=classroom_id,
        teacher_id=teacher_id,
        student_id=student_id,
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
    student_update, classroom = await get_admin_update(
        session, update_id, current_user["organization_id"]
    )
    return await build_update_response(session, student_update, classroom)


@router.get(
    "/recipients/{recipient_id}/history/",
    response_model=list[StudentUpdateEventResponse],
)
async def list_recipient_events(
    recipient_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    await require_admin_recipient(
        session, recipient_id, current_user["organization_id"]
    )
    return await list_events(session, recipient_id)
