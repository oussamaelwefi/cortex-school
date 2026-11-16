import uuid
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from workos import AsyncWorkOSClient

from core.config import settings
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.classrooms.models import (
    ClassEnrollment,
    Classroom,
    TeacherAssignment,
)
from modules.enrollments.models import Enrollment
from modules.invitations.models import UserRoles
from modules.students.models import Student


async def _get_classroom(
    session: AsyncSession,
    classroom_id: uuid.UUID,
    current_user: dict,
    *,
    for_update: bool = False,
) -> tuple[Classroom, AcademicYear]:
    query = (
        select(Classroom, AcademicYear)
        .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
        .where(
            Classroom.id == classroom_id,
            AcademicYear.organization_id == current_user.get("organization_id"),
        )
    )
    if for_update:
        query = query.with_for_update(of=(Classroom, AcademicYear))
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Classroom not found",
        )
    return row


async def _get_enrollment_for_update(
    session: AsyncSession,
    enrollment_id: uuid.UUID,
    current_user: dict,
) -> Enrollment:
    organization_id = current_user.get("organization_id")
    enrollment = await session.scalar(
        select(Enrollment)
        .join(AcademicYear, AcademicYear.id == Enrollment.academic_year_id)
        .join(Student, Student.id == Enrollment.student_id)
        .where(
            Enrollment.id == enrollment_id,
            AcademicYear.organization_id == organization_id,
            Student.organization_id == organization_id,
        )
        .with_for_update(of=Enrollment)
    )
    if enrollment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enrollment not found",
        )
    return enrollment


def _require_same_academic_year(
    classroom: Classroom,
    enrollment: Enrollment,
) -> None:
    if classroom.academic_year_id != enrollment.academic_year_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Classroom and enrollment must belong to the same academic year",
        )


def _require_year_writable(year: AcademicYear) -> None:
    if year.status == AcademicYearStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Closed academic years are read-only",
        )


def _validate_placement_dates(
    year: AcademicYear,
    effective_from: date,
    effective_until: date | None,
) -> None:
    year_end_exclusive = year.ends_on + timedelta(days=1)
    if effective_from < year.starts_on or effective_from > year.ends_on:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Placement dates must fall within the academic year",
        )
    if effective_until is not None and effective_until > year_end_exclusive:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Placement dates must fall within the academic year",
        )


async def _find_overlapping_placement(
    session: AsyncSession,
    enrollment_id: uuid.UUID,
    effective_from: date,
    effective_until: date | None,
    *,
    exclude_id: uuid.UUID | None = None,
) -> ClassEnrollment | None:
    query = select(ClassEnrollment).where(
        ClassEnrollment.enrollment_id == enrollment_id,
        or_(
            ClassEnrollment.effective_until.is_(None),
            ClassEnrollment.effective_until > effective_from,
        ),
    )
    if effective_until is not None:
        query = query.where(ClassEnrollment.effective_from < effective_until)
    if exclude_id is not None:
        query = query.where(ClassEnrollment.id != exclude_id)
    return await session.scalar(query.limit(1))


async def _require_no_placement_overlap(
    session: AsyncSession,
    enrollment_id: uuid.UUID,
    effective_from: date,
    effective_until: date | None,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    overlap = await _find_overlapping_placement(
        session,
        enrollment_id,
        effective_from,
        effective_until,
        exclude_id=exclude_id,
    )
    if overlap is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student already has an overlapping class placement",
        )


async def _require_active_teacher(
    teacher_workos_user_id: str,
    organization_id: str,
) -> None:
    if not settings.WORKOS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WorkOS is not configured",
        )

    try:
        async with AsyncWorkOSClient(api_key=settings.WORKOS_API_KEY) as client:
            memberships = (
                await client.organization_membership.list_organization_memberships(
                    organization_id=organization_id,
                    user_id=teacher_workos_user_id,
                    statuses=["active"],
                    limit=1,
                    request_options={
                        "base_url": settings.WORKOS_API_BASE_URL,
                        "timeout": 20,
                        "max_retries": 0,
                    },
                )
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify teacher membership",
        ) from exc

    if not any(
        role.slug == UserRoles.TEACHER
        for membership in memberships.data
        for role in membership.roles
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Active teacher not found in this school",
        )


def _validate_teacher_assignment_dates(
    year: AcademicYear,
    effective_from: date,
    effective_until: date | None,
) -> None:
    year_end_exclusive = year.ends_on + timedelta(days=1)
    if effective_from < year.starts_on or effective_from > year.ends_on:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Teacher assignment dates must fall within the academic year",
        )
    if effective_until is not None and effective_until > year_end_exclusive:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Teacher assignment dates must fall within the academic year",
        )


async def _require_no_teacher_assignment_overlap(
    session: AsyncSession,
    classroom_id: uuid.UUID,
    teacher_workos_user_id: str,
    effective_from: date,
    effective_until: date | None,
) -> None:
    query = select(TeacherAssignment.id).where(
        TeacherAssignment.classroom_id == classroom_id,
        TeacherAssignment.teacher_workos_user_id == teacher_workos_user_id,
        or_(
            TeacherAssignment.effective_until.is_(None),
            TeacherAssignment.effective_until > effective_from,
        ),
    )
    if effective_until is not None:
        query = query.where(TeacherAssignment.effective_from < effective_until)
    if await session.scalar(query.limit(1)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Teacher already has an overlapping assignment in this classroom",
        )


async def _get_teacher_assignment(
    session: AsyncSession,
    assignment_id: uuid.UUID,
    current_user: dict,
    *,
    for_update: bool = False,
) -> tuple[TeacherAssignment, AcademicYear]:
    query = (
        select(TeacherAssignment, AcademicYear)
        .join(Classroom, Classroom.id == TeacherAssignment.classroom_id)
        .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
        .where(
            TeacherAssignment.id == assignment_id,
            AcademicYear.organization_id == current_user.get("organization_id"),
        )
    )
    if for_update:
        query = query.with_for_update(of=(TeacherAssignment, AcademicYear))
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Teacher assignment not found",
        )
    return row


async def _get_teacher_classroom_access(
    session: AsyncSession,
    classroom_id: uuid.UUID,
    current_user: dict,
    today: date,
) -> tuple[Classroom, AcademicYear, TeacherAssignment]:
    row = (
        await session.execute(
            select(Classroom, AcademicYear, TeacherAssignment)
            .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
            .join(
                TeacherAssignment,
                TeacherAssignment.classroom_id == Classroom.id,
            )
            .where(
                Classroom.id == classroom_id,
                AcademicYear.organization_id
                == current_user.get("organization_id"),
                AcademicYear.status == AcademicYearStatus.ACTIVE,
                AcademicYear.ends_on >= today,
                TeacherAssignment.teacher_workos_user_id
                == current_user.get("user_id"),
                or_(
                    TeacherAssignment.effective_until.is_(None),
                    TeacherAssignment.effective_until > today,
                ),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Classroom not found",
        )
    return row
