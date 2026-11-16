import uuid
from datetime import date

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.attendance.models import (
    AttendanceRecord,
    AttendanceStatus,
    AttendanceSubmission,
)
from modules.attendance.schemas import (
    AdminAttendanceSummaryResponse,
    AdminClassAttendanceResponse,
    AttendanceSheetRequest,
    AttendanceSheetResponse,
    AttendanceStatusCounts,
    GuardianAttendanceResponse,
)
from modules.attendance.services import (
    _current_school_date,
    _get_school,
    _is_instructional_day,
    current_school_date,
    get_status_counts_by_submission,
    get_teacher_attendance_sheet,
    save_teacher_attendance_sheet,
)
from modules.classrooms.models import ClassEnrollment, Classroom
from modules.enrollments.models import Enrollment
from modules.student_registration.services import require_active_guardian
from modules.students.models import GuardianStudent, Student
from modules.teachers.services import _require_teacher_access


teacher_router = APIRouter(prefix="/teacher", tags=["Teacher Attendance"])
guardian_router = APIRouter(
    prefix="/guardian",
    tags=["Guardian Attendance"],
    dependencies=[Depends(require_active_guardian)],
)
admin_router = APIRouter(
    prefix="/attendance",
    tags=["Attendance Administration"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@teacher_router.get(
    "/classrooms/{classroom_id}/attendance",
    response_model=AttendanceSheetResponse,
)
async def get_today_teacher_attendance(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    _require_teacher_access(current_user)
    return await get_teacher_attendance_sheet(
        session,
        classroom_id,
        await current_school_date(
            session,
            current_user.get("organization_id"),
        ),
        current_user,
    )


@teacher_router.get(
    "/classrooms/{classroom_id}/attendance/{school_date}",
    response_model=AttendanceSheetResponse,
)
async def get_dated_teacher_attendance(
    classroom_id: uuid.UUID,
    school_date: date,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    _require_teacher_access(current_user)
    return await get_teacher_attendance_sheet(
        session,
        classroom_id,
        school_date,
        current_user,
    )


@teacher_router.put(
    "/classrooms/{classroom_id}/attendance/{school_date}",
    response_model=AttendanceSheetResponse,
)
async def put_teacher_attendance(
    classroom_id: uuid.UUID,
    school_date: date,
    payload: AttendanceSheetRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    _require_teacher_access(current_user)
    return await save_teacher_attendance_sheet(
        session,
        classroom_id,
        school_date,
        payload,
        current_user,
    )


@guardian_router.get(
    "/students/{student_id}/attendance",
    response_model=list[GuardianAttendanceResponse],
)
async def list_guardian_student_attendance(
    student_id: uuid.UUID,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    if from_date is not None and to_date is not None and from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from must be on or before to",
        )

    linked_student_id = await session.scalar(
        select(Student.id)
        .join(GuardianStudent, GuardianStudent.student_id == Student.id)
        .where(
            Student.id == student_id,
            Student.organization_id == current_user.get("organization_id"),
            GuardianStudent.guardian_workos_user_id == current_user.get("user_id"),
        )
    )
    if linked_student_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    query = (
        select(AttendanceRecord, Classroom, AcademicYear)
        .join(
            ClassEnrollment,
            ClassEnrollment.id == AttendanceRecord.class_enrollment_id,
        )
        .join(Enrollment, Enrollment.id == ClassEnrollment.enrollment_id)
        .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
        .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
        .where(
            Enrollment.student_id == student_id,
            AcademicYear.organization_id == current_user.get("organization_id"),
        )
    )
    if from_date is not None:
        query = query.where(AttendanceRecord.school_date >= from_date)
    if to_date is not None:
        query = query.where(AttendanceRecord.school_date <= to_date)

    rows = (
        await session.execute(
            query.order_by(
                AttendanceRecord.school_date.desc(),
                AttendanceRecord.id,
            ).limit(limit)
        )
    ).all()
    return [
        GuardianAttendanceResponse(
            attendance_record_id=record.id,
            student_id=student_id,
            classroom_id=classroom.id,
            classroom_name=classroom.name,
            academic_year_id=year.id,
            academic_year_name=year.name,
            school_date=record.school_date,
            status=record.status,
            note=record.note,
            updated_at=record.updated_at,
        )
        for record, classroom, year in rows
    ]


@admin_router.get(
    "/submissions",
    response_model=AdminAttendanceSummaryResponse,
)
async def get_admin_attendance_submissions(
    school_date: date | None = Query(default=None),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    school = await _get_school(
        session,
        current_user.get("organization_id"),
    )
    requested_date = school_date or _current_school_date(school)
    years = list(
        (
            await session.scalars(
                select(AcademicYear).where(
                    AcademicYear.organization_id
                    == current_user.get("organization_id"),
                    AcademicYear.status.in_(
                        (
                            AcademicYearStatus.ACTIVE,
                            AcademicYearStatus.CLOSED,
                        )
                    ),
                    AcademicYear.starts_on <= requested_date,
                    AcademicYear.ends_on >= requested_date,
                )
            )
        ).all()
    )
    instructional_years = [
        year
        for year in years
        if await _is_instructional_day(
            session,
            year,
            requested_date,
            school,
        )
    ]
    if not instructional_years:
        return AdminAttendanceSummaryResponse(
            school_date=requested_date,
            expected_classroom_count=0,
            submitted_classroom_count=0,
            missing_classroom_count=0,
            classrooms=[],
        )

    years_by_id = {year.id: year for year in instructional_years}
    classrooms = list(
        (
            await session.scalars(
                select(Classroom)
                .where(Classroom.academic_year_id.in_(list(years_by_id)))
                .order_by(Classroom.name, Classroom.id)
            )
        ).all()
    )
    classroom_ids = [classroom.id for classroom in classrooms]
    if not classroom_ids:
        return AdminAttendanceSummaryResponse(
            school_date=requested_date,
            expected_classroom_count=0,
            submitted_classroom_count=0,
            missing_classroom_count=0,
            classrooms=[],
        )

    submissions = list(
        (
            await session.scalars(
                select(AttendanceSubmission).where(
                    AttendanceSubmission.classroom_id.in_(classroom_ids),
                    AttendanceSubmission.school_date == requested_date,
                )
            )
        ).all()
    )
    submissions_by_classroom = {
        submission.classroom_id: submission for submission in submissions
    }
    counts_by_submission = await get_status_counts_by_submission(
        session, [submission.id for submission in submissions]
    )

    roster_count_rows = (
        await session.execute(
            select(
                ClassEnrollment.classroom_id,
                func.count(ClassEnrollment.id),
            )
            .join(Enrollment, Enrollment.id == ClassEnrollment.enrollment_id)
            .where(
                ClassEnrollment.classroom_id.in_(classroom_ids),
                ClassEnrollment.effective_from <= requested_date,
                or_(
                    ClassEnrollment.effective_until.is_(None),
                    ClassEnrollment.effective_until > requested_date,
                ),
            )
            .group_by(ClassEnrollment.classroom_id)
        )
    ).all()
    roster_counts = dict(roster_count_rows)

    response_rows = []
    for classroom in classrooms:
        year = years_by_id[classroom.academic_year_id]
        submission = submissions_by_classroom.get(classroom.id)
        raw_counts = counts_by_submission.get(submission.id, {}) if submission else {}
        counts = AttendanceStatusCounts(
            present=raw_counts.get(AttendanceStatus.PRESENT, 0),
            absent=raw_counts.get(AttendanceStatus.ABSENT, 0),
            late=raw_counts.get(AttendanceStatus.LATE, 0),
            excused=raw_counts.get(AttendanceStatus.EXCUSED, 0),
        )
        recorded_count = sum(raw_counts.values())
        response_rows.append(
            AdminClassAttendanceResponse(
                classroom_id=classroom.id,
                classroom_name=classroom.name,
                academic_year_id=year.id,
                academic_year_name=year.name,
                school_date=requested_date,
                status="submitted" if submission else "missing",
                active_student_count=roster_counts.get(classroom.id, 0),
                recorded_student_count=recorded_count,
                counts=counts,
                submission_id=submission.id if submission else None,
                submitted_by_workos_user_id=(
                    submission.submitted_by_workos_user_id if submission else None
                ),
                submitted_at=submission.submitted_at if submission else None,
                updated_by_workos_user_id=(
                    submission.updated_by_workos_user_id if submission else None
                ),
                updated_at=submission.updated_at if submission else None,
            )
        )

    submitted_count = len(submissions)
    expected_count = len(classrooms)
    return AdminAttendanceSummaryResponse(
        school_date=requested_date,
        expected_classroom_count=expected_count,
        submitted_classroom_count=submitted_count,
        missing_classroom_count=expected_count - submitted_count,
        classrooms=response_rows,
    )


router = APIRouter()
router.include_router(teacher_router)
router.include_router(guardian_router)
router.include_router(admin_router)
