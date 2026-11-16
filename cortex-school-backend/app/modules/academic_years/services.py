import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.academic_years.models import (
    AcademicCalendar,
    AcademicYear,
    AcademicYearStatus,
    CalendarEntry,
    CalendarEntryType,
)
from modules.classrooms.models import (
    ClassEnrollment,
    Classroom,
    TeacherAssignment,
)
from modules.enrollments.models import Enrollment


@dataclass(frozen=True)
class AcademicYearReadiness:
    errors: list[str]
    warnings: list[str]

    @property
    def can_publish(self) -> bool:
        return not self.errors


async def _commit_year(session: AsyncSession, year: AcademicYear) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Academic year name already exists for this school",
        ) from exc
    await session.refresh(year)


async def _get_academic_year(
    session: AsyncSession,
    year_id: uuid.UUID,
    current_user: dict,
    *,
    for_update: bool = False,
) -> AcademicYear:
    query = select(AcademicYear).where(
        AcademicYear.id == year_id,
        AcademicYear.organization_id == current_user.get("organization_id"),
    )
    if for_update:
        query = query.with_for_update()
    year = await session.scalar(query)
    if year is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Academic year not found",
        )
    return year


async def _get_academic_calendar(
    session: AsyncSession,
    year: AcademicYear,
) -> AcademicCalendar:
    calendar = await session.scalar(
        select(AcademicCalendar).where(
            AcademicCalendar.academic_year_id == year.id,
        )
    )
    if calendar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Academic calendar not found",
        )
    return calendar


async def _get_calendar_entry(
    session: AsyncSession,
    year: AcademicYear,
    entry_id: uuid.UUID,
) -> CalendarEntry:
    entry = await session.scalar(
        select(CalendarEntry)
        .join(
            AcademicCalendar,
            AcademicCalendar.id == CalendarEntry.academic_calendar_id,
        )
        .where(
            CalendarEntry.id == entry_id,
            AcademicCalendar.academic_year_id == year.id,
        )
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar entry not found",
        )
    return entry


def _require_draft_year(year: AcademicYear) -> None:
    if year.status != AcademicYearStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft academic years can be edited",
        )


def _require_year_writable(year: AcademicYear) -> None:
    if year.status == AcademicYearStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Closed academic years are read-only",
        )


def _validate_calendar_entry_dates(
    year: AcademicYear,
    starts_on: date,
    ends_on: date,
) -> None:
    if starts_on < year.starts_on or ends_on > year.ends_on:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Calendar entry dates must fall within the academic year",
        )


async def _validate_academic_year_dates_against_history(
    session: AsyncSession,
    year: AcademicYear,
    starts_on: date,
    ends_on: date,
) -> None:
    invalid_entry_id = await session.scalar(
        select(CalendarEntry.id)
        .join(
            AcademicCalendar,
            AcademicCalendar.id == CalendarEntry.academic_calendar_id,
        )
        .where(
            AcademicCalendar.academic_year_id == year.id,
            or_(
                CalendarEntry.starts_on < starts_on,
                CalendarEntry.ends_on > ends_on,
            ),
        )
        .limit(1)
    )
    if invalid_entry_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Academic year dates must include all existing calendar entries"
            ),
        )

    year_end_exclusive = ends_on + timedelta(days=1)
    invalid_placement_id = await session.scalar(
        select(ClassEnrollment.id)
        .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
        .where(
            Classroom.academic_year_id == year.id,
            or_(
                ClassEnrollment.effective_from < starts_on,
                ClassEnrollment.effective_from > ends_on,
                ClassEnrollment.effective_until > year_end_exclusive,
            ),
        )
        .limit(1)
    )
    if invalid_placement_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Academic year dates must include all existing class placements"
            ),
        )

    invalid_assignment_id = await session.scalar(
        select(TeacherAssignment.id)
        .join(Classroom, Classroom.id == TeacherAssignment.classroom_id)
        .where(
            Classroom.academic_year_id == year.id,
            or_(
                TeacherAssignment.effective_from < starts_on,
                TeacherAssignment.effective_from > ends_on,
                TeacherAssignment.effective_until > year_end_exclusive,
            ),
        )
        .limit(1)
    )
    if invalid_assignment_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Academic year dates must include all existing teacher assignments"
            ),
        )


async def get_academic_year_readiness(
    session: AsyncSession,
    year: AcademicYear,
) -> AcademicYearReadiness:
    errors: list[str] = []
    warnings: list[str] = []

    calendar = await session.scalar(
        select(AcademicCalendar).where(
            AcademicCalendar.academic_year_id == year.id,
        )
    )
    if calendar is None:
        errors.append("Academic calendar is missing")
    else:
        term_count = await session.scalar(
            select(func.count(CalendarEntry.id)).where(
                CalendarEntry.academic_calendar_id == calendar.id,
                CalendarEntry.entry_type == CalendarEntryType.TERM,
            )
        )
        if not term_count:
            errors.append("At least one calendar term is required")

        invalid_entry_count = await session.scalar(
            select(func.count(CalendarEntry.id)).where(
                CalendarEntry.academic_calendar_id == calendar.id,
                or_(
                    CalendarEntry.starts_on < year.starts_on,
                    CalendarEntry.ends_on > year.ends_on,
                ),
            )
        )
        if invalid_entry_count:
            errors.append("Calendar entries must fall within the academic year")

    classroom_count = await session.scalar(
        select(func.count(Classroom.id)).where(
            Classroom.academic_year_id == year.id,
        )
    )
    if not classroom_count:
        warnings.append("No classrooms have been created")

    teacher_assignment_count = await session.scalar(
        select(func.count(TeacherAssignment.id))
        .join(Classroom, Classroom.id == TeacherAssignment.classroom_id)
        .where(Classroom.academic_year_id == year.id)
    )
    if not teacher_assignment_count:
        warnings.append("No teacher assignments have been configured")
    elif classroom_count:
        unassigned_classroom_count = await session.scalar(
            select(func.count(Classroom.id)).where(
                Classroom.academic_year_id == year.id,
                ~exists(
                    select(TeacherAssignment.id).where(
                        TeacherAssignment.classroom_id == Classroom.id,
                    )
                ),
            )
        )
        if unassigned_classroom_count:
            warnings.append(
                f"{unassigned_classroom_count} classroom(s) have no teacher assignment"
            )

    enrollment_count = await session.scalar(
        select(func.count(Enrollment.id)).where(
            Enrollment.academic_year_id == year.id,
        )
    )
    if not enrollment_count:
        warnings.append("No student placements have been configured")
    else:
        unplaced_enrollment_count = await session.scalar(
            select(func.count(Enrollment.id)).where(
                Enrollment.academic_year_id == year.id,
                ~exists(
                    select(ClassEnrollment.id).where(
                        ClassEnrollment.enrollment_id == Enrollment.id,
                    )
                ),
            )
        )
        if unplaced_enrollment_count:
            warnings.append(
                f"{unplaced_enrollment_count} enrollment(s) have no class placement"
            )

    return AcademicYearReadiness(errors=errors, warnings=warnings)


async def require_academic_year_publishable(
    session: AsyncSession,
    year: AcademicYear,
) -> AcademicYearReadiness:
    readiness = await get_academic_year_readiness(session, year)
    if not readiness.can_publish:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Academic year is not ready to publish",
                "errors": readiness.errors,
                "warnings": readiness.warnings,
            },
        )
    return readiness
