import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.enrollments.models import Enrollment
from modules.student_registration.models import (
    StudentRegistrationRequest,
    StudentRegistrationStatus,
)
from modules.student_registration.schemas import (
    ApproveWithExistingStudent,
    StudentRegistrationApproval,
    StudentRegistrationRequestCreate,
    StudentRegistrationRequestUpdate,
)
from modules.students.models import GuardianStudent, Student
from modules.students.services import _require_active_guardian


async def require_active_guardian(
    current_user: dict = Depends(get_current_user),
) -> dict:
    guardian_workos_user_id = current_user.get("user_id")
    organization_id = current_user.get("organization_id")
    if not guardian_workos_user_id or not organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active guardian membership required",
        )

    try:
        await _require_active_guardian(
            guardian_workos_user_id,
            organization_id,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Active guardian membership required",
            ) from exc
        raise

    return current_user


def _require_pending(registration_request: StudentRegistrationRequest) -> None:
    if registration_request.status != StudentRegistrationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration request is no longer pending",
        )


async def _get_academic_year_for_organization(
    session: AsyncSession,
    academic_year_id: uuid.UUID,
    organization_id: str,
    *,
    require_active: bool = False,
) -> AcademicYear:
    academic_year = await session.scalar(
        select(AcademicYear).where(
            AcademicYear.id == academic_year_id,
            AcademicYear.organization_id == organization_id,
        )
    )
    if academic_year is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Academic year not found",
        )
    if require_active and academic_year.status != AcademicYearStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Academic year is not open for registration",
        )
    return academic_year


async def _get_registration_request_for_update(
    session: AsyncSession,
    request_id: uuid.UUID,
    organization_id: str,
    guardian_workos_user_id: str | None = None,
) -> StudentRegistrationRequest:
    query = (
        select(StudentRegistrationRequest)
        .where(
            StudentRegistrationRequest.id == request_id,
            StudentRegistrationRequest.organization_id == organization_id,
        )
        .with_for_update()
    )
    if guardian_workos_user_id is not None:
        query = query.where(
            StudentRegistrationRequest.guardian_workos_user_id
            == guardian_workos_user_id
        )

    registration_request = await session.scalar(query)
    if registration_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration request not found",
        )
    return registration_request


async def create_registration_request(
    session: AsyncSession,
    payload: StudentRegistrationRequestCreate,
    guardian_workos_user_id: str,
    organization_id: str,
) -> StudentRegistrationRequest:
    async with session.begin():
        await _get_academic_year_for_organization(
            session,
            payload.academic_year_id,
            organization_id,
            require_active=True,
        )
        registration_request = StudentRegistrationRequest(
            guardian_workos_user_id=guardian_workos_user_id,
            organization_id=organization_id,
            child_first_name=payload.child_first_name,
            child_last_name=payload.child_last_name,
            academic_year_id=payload.academic_year_id,
            status=StudentRegistrationStatus.PENDING,
        )
        session.add(registration_request)

    return registration_request


async def update_registration_request(
    session: AsyncSession,
    request_id: uuid.UUID,
    payload: StudentRegistrationRequestUpdate,
    guardian_workos_user_id: str,
    organization_id: str,
) -> StudentRegistrationRequest:
    async with session.begin():
        registration_request = await _get_registration_request_for_update(
            session,
            request_id,
            organization_id,
            guardian_workos_user_id,
        )
        _require_pending(registration_request)

        await _get_academic_year_for_organization(
            session,
            registration_request.academic_year_id,
            organization_id,
            require_active=True,
        )

        if payload.academic_year_id is not None:
            await _get_academic_year_for_organization(
                session,
                payload.academic_year_id,
                organization_id,
                require_active=True,
            )
            registration_request.academic_year_id = payload.academic_year_id
        if payload.child_first_name is not None:
            registration_request.child_first_name = payload.child_first_name
        if payload.child_last_name is not None:
            registration_request.child_last_name = payload.child_last_name

    return registration_request


async def withdraw_registration_request(
    session: AsyncSession,
    request_id: uuid.UUID,
    guardian_workos_user_id: str,
    organization_id: str,
) -> StudentRegistrationRequest:
    async with session.begin():
        registration_request = await _get_registration_request_for_update(
            session,
            request_id,
            organization_id,
            guardian_workos_user_id,
        )
        _require_pending(registration_request)
        await _get_academic_year_for_organization(
            session,
            registration_request.academic_year_id,
            organization_id,
            require_active=True,
        )
        registration_request.status = StudentRegistrationStatus.WITHDRAWN

    return registration_request


async def approve_registration_request(
    session: AsyncSession,
    request_id: uuid.UUID,
    payload: StudentRegistrationApproval,
    organization_id: str,
) -> StudentRegistrationRequest:
    async with session.begin():
        registration_request = await _get_registration_request_for_update(
            session,
            request_id,
            organization_id,
        )
        _require_pending(registration_request)
        await _get_academic_year_for_organization(
            session,
            registration_request.academic_year_id,
            organization_id,
            require_active=True,
        )

        if isinstance(payload, ApproveWithExistingStudent):
            student = await session.scalar(
                select(Student).where(
                    Student.id == payload.student_id,
                    Student.organization_id == organization_id,
                )
            )
            if student is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Student not found",
                )
        else:
            student = Student(
                organization_id=organization_id,
                first_name=registration_request.child_first_name,
                last_name=registration_request.child_last_name,
            )
            session.add(student)
            await session.flush()

        await session.execute(
            postgresql_insert(GuardianStudent)
            .values(
                student_id=student.id,
                guardian_workos_user_id=(
                    registration_request.guardian_workos_user_id
                ),
            )
            .on_conflict_do_nothing(
                constraint="uq_guardianstudent_student_guardian"
            )
        )
        await session.execute(
            postgresql_insert(Enrollment)
            .values(
                student_id=student.id,
                academic_year_id=registration_request.academic_year_id,
            )
            .on_conflict_do_nothing(
                constraint="uq_enrollment_student_academic_year"
            )
        )

        registration_request.resolved_student_id = student.id
        registration_request.status = StudentRegistrationStatus.APPROVED
        registration_request.rejection_reason = None

    return registration_request


async def reject_registration_request(
    session: AsyncSession,
    request_id: uuid.UUID,
    reason: str,
    organization_id: str,
) -> StudentRegistrationRequest:
    async with session.begin():
        registration_request = await _get_registration_request_for_update(
            session,
            request_id,
            organization_id,
        )
        _require_pending(registration_request)
        await _get_academic_year_for_organization(
            session,
            registration_request.academic_year_id,
            organization_id,
            require_active=True,
        )
        registration_request.status = StudentRegistrationStatus.REJECTED
        registration_request.rejection_reason = reason

    return registration_request
