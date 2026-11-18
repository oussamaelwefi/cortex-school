import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from workos import AsyncWorkOSClient

from core.config import settings
from modules.invitations.models import UserRoles
from modules.students.models import GuardianStudent, Student


async def guardian_ids_by_student(
    session: AsyncSession, organization_id: str, student_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[str]]:
    if not student_ids:
        return {}
    rows = await session.execute(
        select(GuardianStudent.student_id, GuardianStudent.guardian_workos_user_id)
        .join(Student, Student.id == GuardianStudent.student_id)
        .where(Student.organization_id == organization_id, Student.id.in_(student_ids))
        .order_by(GuardianStudent.guardian_workos_user_id)
    )
    result = {}
    for student_id, guardian_id in rows:
        result.setdefault(student_id, []).append(guardian_id)
    return result


async def _get_student(
    session: AsyncSession,
    student_id: uuid.UUID,
    current_user: dict,
) -> Student:
    student = await session.scalar(
        select(Student).where(
            Student.id == student_id,
            Student.organization_id == current_user.get("organization_id"),
        )
    )
    if student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )
    return student


async def _get_guardian(
    session: AsyncSession,
    student_id: uuid.UUID,
    guardian_id: uuid.UUID,
    current_user: dict,
) -> GuardianStudent:
    await _get_student(session, student_id, current_user)
    guardian = await session.scalar(
        select(GuardianStudent).where(
            GuardianStudent.id == guardian_id,
            GuardianStudent.student_id == student_id,
        )
    )
    if guardian is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guardian link not found",
        )
    return guardian


async def _require_active_guardian(
    guardian_workos_user_id: str,
    organization_id: str,
) -> None:
    if not settings.WORKOS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WorkOS is not configured",
        )

    try:
        async with AsyncWorkOSClient(api_key=settings.WORKOS_API_KEY) as client:
            memberships = await client.organization_membership.list_organization_memberships(
                organization_id=organization_id,
                user_id=guardian_workos_user_id,
                statuses=["active"],
                limit=1,
                request_options={
                    "base_url": settings.WORKOS_API_BASE_URL,
                    "timeout": 20,
                    "max_retries": 0,
                },
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify guardian membership",
        ) from exc

    if not any(
        role.slug == UserRoles.GUARDIAN
        for membership in memberships.data
        for role in membership.roles
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Active guardian not found in this school",
        )
