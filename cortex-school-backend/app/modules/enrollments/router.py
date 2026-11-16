import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.academic_years.services import _get_academic_year
from modules.enrollments.models import Enrollment
from modules.enrollments.schemas import EnrollmentCreateRequest, EnrollmentResponse
from modules.enrollments.services import _get_enrollment
from modules.students.services import _get_student

router = APIRouter(
    tags=["Enrollments"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@router.post(
    "/students/{student_id}/enrollments/",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_enrollment(
    student_id: uuid.UUID,
    payload: EnrollmentCreateRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    await _get_student(session, student_id, current_user)
    academic_year = await _get_academic_year(
        session,
        payload.academic_year_id,
        current_user,
    )
    if academic_year.status == AcademicYearStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Closed academic years are read-only",
        )
    enrollment = Enrollment(
        student_id=student_id,
        academic_year_id=payload.academic_year_id,
    )
    session.add(enrollment)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student is already enrolled in this academic year",
        ) from exc
    await session.refresh(enrollment)
    return enrollment


@router.get(
    "/students/{student_id}/enrollments/",
    response_model=list[EnrollmentResponse],
)
async def list_student_enrollments(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    await _get_student(session, student_id, current_user)
    result = await session.scalars(
        select(Enrollment)
        .join(AcademicYear, AcademicYear.id == Enrollment.academic_year_id)
        .where(
            Enrollment.student_id == student_id,
            AcademicYear.organization_id == current_user.get("organization_id"),
        )
        .order_by(Enrollment.created_at.desc())
    )
    return list(result.all())


@router.get("/enrollments/{enrollment_id}/", response_model=EnrollmentResponse)
async def get_enrollment(
    enrollment_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await _get_enrollment(session, enrollment_id, current_user)


@router.delete(
    "/enrollments/{enrollment_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_enrollment(
    enrollment_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    enrollment = await _get_enrollment(session, enrollment_id, current_user)
    academic_year = await session.get(AcademicYear, enrollment.academic_year_id)
    if academic_year is not None and academic_year.status == AcademicYearStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Closed academic years are read-only",
        )
    await session.delete(enrollment)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Enrollment with class placement history cannot be deleted",
        ) from exc
