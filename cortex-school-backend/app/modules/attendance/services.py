import uuid
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import utcnow
from modules.academic_years.models import (
    AcademicCalendar,
    AcademicYear,
    AcademicYearStatus,
    CalendarEntry,
    CalendarEntryType,
)
from modules.attendance.models import (
    AttendanceRecord,
    AttendanceStatus,
    AttendanceSubmission,
)
from modules.attendance.schemas import (
    AttendanceEntryResponse,
    AttendanceSheetRequest,
    AttendanceSheetResponse,
)
from modules.classrooms.models import (
    ClassEnrollment,
    Classroom,
    TeacherAssignment,
)
from modules.enrollments.models import Enrollment
from modules.schools.models import School
from modules.students.models import Student


EXCLUDED_CALENDAR_ENTRY_TYPES = (
    CalendarEntryType.HOLIDAY,
    CalendarEntryType.BREAK,
    CalendarEntryType.NON_INSTRUCTION_DAY,
)


def _current_school_date(school: School) -> date:
    try:
        timezone = ZoneInfo(school.timezone)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError("School timezone is not a valid IANA timezone") from exc
    return utcnow().astimezone(timezone).date()


def _school_weekdays(school: School) -> set[int]:
    weekdays = set(school.instructional_weekdays)
    if not weekdays or not weekdays.issubset(set(range(7))):
        raise RuntimeError(
            "School instructional weekdays must contain values from 0 to 6"
        )
    return weekdays


async def _get_school(
    session: AsyncSession,
    organization_id: str | None,
) -> School:
    school = await session.get(School, organization_id)
    if school is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="School not found",
        )
    return school


async def current_school_date(
    session: AsyncSession,
    organization_id: str | None,
) -> date:
    school = await _get_school(session, organization_id)
    return _current_school_date(school)


async def _is_instructional_day(
    session: AsyncSession,
    year: AcademicYear,
    school_date: date,
    school: School,
) -> bool:
    if not year.starts_on <= school_date <= year.ends_on:
        return False
    if school_date.weekday() not in _school_weekdays(school):
        return False

    excluded_entry_id = await session.scalar(
        select(CalendarEntry.id)
        .join(
            AcademicCalendar,
            AcademicCalendar.id == CalendarEntry.academic_calendar_id,
        )
        .where(
            AcademicCalendar.academic_year_id == year.id,
            CalendarEntry.entry_type.in_(EXCLUDED_CALENDAR_ENTRY_TYPES),
            CalendarEntry.starts_on <= school_date,
            CalendarEntry.ends_on >= school_date,
        )
        .limit(1)
    )
    return excluded_entry_id is None


async def _require_instructional_day(
    session: AsyncSession,
    year: AcademicYear,
    school_date: date,
    school: School,
) -> None:
    if not await _is_instructional_day(session, year, school_date, school):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Attendance can only be recorded on an instructional school day",
        )


async def _get_teacher_attendance_context(
    session: AsyncSession,
    classroom_id: uuid.UUID,
    school_date: date,
    current_user: dict,
) -> tuple[Classroom, AcademicYear, TeacherAssignment, School]:
    row = (
        await session.execute(
            select(Classroom, AcademicYear, TeacherAssignment, School)
            .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
            .join(School, School.organization_id == AcademicYear.organization_id)
            .join(
                TeacherAssignment,
                TeacherAssignment.classroom_id == Classroom.id,
            )
            .where(
                Classroom.id == classroom_id,
                AcademicYear.organization_id == current_user.get("organization_id"),
                AcademicYear.status == AcademicYearStatus.ACTIVE,
                AcademicYear.starts_on <= school_date,
                AcademicYear.ends_on >= school_date,
                TeacherAssignment.teacher_workos_user_id
                == current_user.get("user_id"),
                TeacherAssignment.effective_from <= school_date,
                or_(
                    TeacherAssignment.effective_until.is_(None),
                    TeacherAssignment.effective_until > school_date,
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


async def _get_attendance_roster(
    session: AsyncSession,
    classroom: Classroom,
    year: AcademicYear,
    school_date: date,
) -> list[tuple[Student, Enrollment, ClassEnrollment]]:
    return list(
        (
            await session.execute(
                select(Student, Enrollment, ClassEnrollment)
                .join(Enrollment, Enrollment.student_id == Student.id)
                .join(
                    ClassEnrollment,
                    ClassEnrollment.enrollment_id == Enrollment.id,
                )
                .where(
                    ClassEnrollment.classroom_id == classroom.id,
                    Enrollment.academic_year_id == classroom.academic_year_id,
                    Student.organization_id == year.organization_id,
                    ClassEnrollment.effective_from <= school_date,
                    or_(
                        ClassEnrollment.effective_until.is_(None),
                        ClassEnrollment.effective_until > school_date,
                    ),
                )
                .order_by(Student.last_name, Student.first_name, Student.id)
            )
        ).all()
    )


async def get_teacher_attendance_sheet(
    session: AsyncSession,
    classroom_id: uuid.UUID,
    school_date: date,
    current_user: dict,
) -> AttendanceSheetResponse:
    classroom, year, _, school = await _get_teacher_attendance_context(
        session, classroom_id, school_date, current_user
    )
    if school_date > _current_school_date(school):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Attendance cannot be viewed for a future date",
        )
    roster = await _get_attendance_roster(session, classroom, year, school_date)

    submission = await session.scalar(
        select(AttendanceSubmission).where(
            AttendanceSubmission.classroom_id == classroom.id,
            AttendanceSubmission.school_date == school_date,
        )
    )
    records_by_placement: dict[uuid.UUID, AttendanceRecord] = {}
    if submission is not None:
        records = await session.scalars(
            select(AttendanceRecord).where(
                AttendanceRecord.submission_id == submission.id
            )
        )
        records_by_placement = {
            record.class_enrollment_id: record for record in records.all()
        }

    entries = []
    for student, enrollment, placement in roster:
        record = records_by_placement.get(placement.id)
        entries.append(
            AttendanceEntryResponse(
                attendance_record_id=record.id if record else None,
                placement_id=placement.id,
                enrollment_id=enrollment.id,
                student_id=student.id,
                first_name=student.first_name,
                last_name=student.last_name,
                status=record.status if record else AttendanceStatus.PRESENT,
                note=record.note if record else None,
                updated_at=record.updated_at if record else None,
            )
        )

    return AttendanceSheetResponse(
        submission_id=submission.id if submission else None,
        classroom_id=classroom.id,
        classroom_name=classroom.name,
        school_date=school_date,
        submitted=submission is not None,
        submitted_by_workos_user_id=(
            submission.submitted_by_workos_user_id if submission else None
        ),
        submitted_at=submission.submitted_at if submission else None,
        updated_by_workos_user_id=(
            submission.updated_by_workos_user_id if submission else None
        ),
        updated_at=submission.updated_at if submission else None,
        entries=entries,
    )


async def save_teacher_attendance_sheet(
    session: AsyncSession,
    classroom_id: uuid.UUID,
    school_date: date,
    payload: AttendanceSheetRequest,
    current_user: dict,
) -> AttendanceSheetResponse:
    classroom, year, _, school = await _get_teacher_attendance_context(
        session, classroom_id, school_date, current_user
    )
    if school_date > _current_school_date(school):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Attendance cannot be recorded for a future date",
        )
    await _require_instructional_day(session, year, school_date, school)
    roster = await _get_attendance_roster(session, classroom, year, school_date)

    roster_ids = {placement.id for _, _, placement in roster}
    supplied_ids = {entry.placement_id for entry in payload.entries}
    if supplied_ids != roster_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Attendance entries must match the active roster",
                "missing_placement_ids": sorted(
                    str(value) for value in roster_ids - supplied_ids
                ),
                "unexpected_placement_ids": sorted(
                    str(value) for value in supplied_ids - roster_ids
                ),
            },
        )

    now = utcnow()
    user_id = current_user["user_id"]
    submission_insert = postgresql_insert(AttendanceSubmission).values(
        id=uuid.uuid4(),
        classroom_id=classroom.id,
        school_date=school_date,
        submitted_by_workos_user_id=user_id,
        submitted_at=now,
        updated_by_workos_user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    submission_id = await session.scalar(
        submission_insert.on_conflict_do_update(
            constraint="uq_attendancesubmission_classroom_date",
            set_={
                "updated_by_workos_user_id": user_id,
                "updated_at": now,
            },
        ).returning(AttendanceSubmission.id)
    )

    if roster_ids:
        await session.execute(
            delete(AttendanceRecord).where(
                AttendanceRecord.submission_id == submission_id,
                AttendanceRecord.class_enrollment_id.not_in(roster_ids),
            )
        )
    else:
        await session.execute(
            delete(AttendanceRecord).where(
                AttendanceRecord.submission_id == submission_id
            )
        )

    if payload.entries:
        record_values = [
            {
                "id": uuid.uuid4(),
                "submission_id": submission_id,
                "class_enrollment_id": entry.placement_id,
                "school_date": school_date,
                "status": entry.status,
                "note": entry.note,
                "updated_by_workos_user_id": user_id,
                "created_at": now,
                "updated_at": now,
            }
            for entry in payload.entries
        ]
        record_insert = postgresql_insert(AttendanceRecord).values(record_values)
        await session.execute(
            record_insert.on_conflict_do_update(
                constraint="uq_attendancerecord_placement_date",
                set_={
                    "submission_id": record_insert.excluded.submission_id,
                    "status": record_insert.excluded.status,
                    "note": record_insert.excluded.note,
                    "updated_by_workos_user_id": user_id,
                    "updated_at": now,
                },
            )
        )

    await session.commit()
    return await get_teacher_attendance_sheet(
        session, classroom_id, school_date, current_user
    )


async def get_status_counts_by_submission(
    session: AsyncSession,
    submission_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[AttendanceStatus, int]]:
    if not submission_ids:
        return {}
    rows = (
        await session.execute(
            select(
                AttendanceRecord.submission_id,
                AttendanceRecord.status,
                func.count(AttendanceRecord.id),
            )
            .where(AttendanceRecord.submission_id.in_(submission_ids))
            .group_by(AttendanceRecord.submission_id, AttendanceRecord.status)
        )
    ).all()
    counts: dict[uuid.UUID, dict[AttendanceStatus, int]] = {}
    for submission_id, attendance_status, count in rows:
        counts.setdefault(submission_id, {})[attendance_status] = count
    return counts
