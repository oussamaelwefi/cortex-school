import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.academic_years.models import AcademicYear
from modules.enrollments.models import Enrollment
from modules.students.models import Student


async def _get_enrollment(
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
    )
    if enrollment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enrollment not found",
        )
    return enrollment
