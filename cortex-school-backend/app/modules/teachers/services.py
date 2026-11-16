from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.attendance.models import (
    AttendanceRecord,
    AttendanceStatus,
    AttendanceSubmission,
)
from modules.attendance.services import (
    _current_school_date,
    _get_school,
    _is_instructional_day,
)
from modules.classrooms.models import (
    ClassEnrollment,
    Classroom,
    TeacherAssignment,
)
from modules.classrooms.schemas import (
    TeacherClassroomResponse,
    TeacherClassroomStudentResponse,
)
from modules.enrollments.models import Enrollment
from modules.invitations.models import UserRoles
from modules.student_updates.models import StudentUpdate, StudentUpdateRecipient
from modules.students.models import Student
from modules.teachers.schemas import (
    TeacherTodayAttendanceResponse,
    TeacherTodayAttendanceStatus,
    TeacherTodayClassroomResponse,
    TeacherTodayDayStatus,
    TeacherTodayResponse,
    TeacherTodayUpdateResponse,
)


def _require_teacher_access(current_user: dict) -> tuple[str, str]:
    user_id = current_user.get("user_id")
    organization_id = current_user.get("organization_id")
    if not user_id or not organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teacher access required",
        )

    claims = current_user.get("claims", {})
    roles = claims.get("roles") or []
    if (
        claims.get("role") != UserRoles.TEACHER.value
        and UserRoles.TEACHER.value not in roles
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teacher access required",
        )

    return user_id, organization_id


def _teacher_classroom_response(
    classroom: Classroom,
    year: AcademicYear,
    assignment: TeacherAssignment,
    today: date,
) -> TeacherClassroomResponse:
    access_starts_on = max(year.starts_on, assignment.effective_from)
    return TeacherClassroomResponse(
        id=classroom.id,
        academic_year_id=classroom.academic_year_id,
        name=classroom.name,
        created_at=classroom.created_at,
        updated_at=classroom.updated_at,
        assignment_id=assignment.id,
        assignment_role=assignment.role,
        assignment_effective_from=assignment.effective_from,
        assignment_effective_until=assignment.effective_until,
        access_status=(
            "current" if access_starts_on <= today else "upcoming"
        ),
    )


def _teacher_classroom_student_response(
    student: Student,
    enrollment: Enrollment,
    placement: ClassEnrollment,
) -> TeacherClassroomStudentResponse:
    return TeacherClassroomStudentResponse(
        student_id=student.id,
        enrollment_id=enrollment.id,
        placement_id=placement.id,
        first_name=student.first_name,
        last_name=student.last_name,
        effective_from=placement.effective_from,
        effective_until=placement.effective_until,
    )


def _teacher_today_day_status(
    *,
    has_active_year: bool,
    is_instructional_day: bool,
) -> TeacherTodayDayStatus:
    if not has_active_year:
        return TeacherTodayDayStatus.OUTSIDE_ACTIVE_YEAR
    if not is_instructional_day:
        return TeacherTodayDayStatus.NON_INSTRUCTIONAL
    return TeacherTodayDayStatus.INSTRUCTIONAL


async def get_teacher_today(
    session: AsyncSession,
    selected_date: date | None,
    current_user: dict,
) -> TeacherTodayResponse:
    user_id, organization_id = _require_teacher_access(current_user)
    school = await _get_school(session, organization_id)
    current_date = _current_school_date(school)
    school_date = selected_date or current_date

    if school_date > current_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Teacher Today cannot be viewed for a future date",
        )

    active_years = list(
        (
            await session.scalars(
                select(AcademicYear).where(
                    AcademicYear.organization_id == organization_id,
                    AcademicYear.status == AcademicYearStatus.ACTIVE,
                    AcademicYear.starts_on <= school_date,
                    AcademicYear.ends_on >= school_date,
                )
            )
        ).all()
    )
    instructional = False
    for year in active_years:
        if await _is_instructional_day(session, year, school_date, school):
            instructional = True
            break
    day_status = _teacher_today_day_status(
        has_active_year=bool(active_years),
        is_instructional_day=instructional,
    )

    classroom_rows = (
        await session.execute(
            select(
                Classroom.id,
                Classroom.name,
                TeacherAssignment.role,
                func.count(Student.id).label("active_student_count"),
            )
            .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
            .join(
                TeacherAssignment,
                and_(
                    TeacherAssignment.classroom_id == Classroom.id,
                    TeacherAssignment.teacher_workos_user_id == user_id,
                    TeacherAssignment.effective_from <= school_date,
                    or_(
                        TeacherAssignment.effective_until.is_(None),
                        TeacherAssignment.effective_until > school_date,
                    ),
                ),
            )
            .outerjoin(
                ClassEnrollment,
                and_(
                    ClassEnrollment.classroom_id == Classroom.id,
                    ClassEnrollment.effective_from <= school_date,
                    or_(
                        ClassEnrollment.effective_until.is_(None),
                        ClassEnrollment.effective_until > school_date,
                    ),
                ),
            )
            .outerjoin(
                Enrollment,
                and_(
                    Enrollment.id == ClassEnrollment.enrollment_id,
                    Enrollment.academic_year_id == Classroom.academic_year_id,
                ),
            )
            .outerjoin(
                Student,
                and_(
                    Student.id == Enrollment.student_id,
                    Student.organization_id == organization_id,
                ),
            )
            .where(
                AcademicYear.organization_id == organization_id,
                AcademicYear.status == AcademicYearStatus.ACTIVE,
                AcademicYear.starts_on <= school_date,
                AcademicYear.ends_on >= school_date,
            )
            .group_by(Classroom.id, Classroom.name, TeacherAssignment.role)
            .order_by(Classroom.name, Classroom.id)
        )
    ).all()
    classroom_ids = [classroom_id for classroom_id, _, _, _ in classroom_rows]

    submissions = []
    if classroom_ids:
        submissions = list(
            (
                await session.scalars(
                    select(AttendanceSubmission).where(
                        AttendanceSubmission.classroom_id.in_(classroom_ids),
                        AttendanceSubmission.school_date == school_date,
                    )
                )
            ).all()
        )
    submissions_by_classroom = {
        submission.classroom_id: submission for submission in submissions
    }

    status_count_rows = []
    if submissions:
        status_count_rows = (
            await session.execute(
                select(
                    AttendanceRecord.submission_id,
                    AttendanceRecord.status,
                    func.count(AttendanceRecord.id),
                )
                .where(
                    AttendanceRecord.submission_id.in_(
                        [submission.id for submission in submissions]
                    )
                )
                .group_by(
                    AttendanceRecord.submission_id,
                    AttendanceRecord.status,
                )
            )
        ).all()
    counts_by_submission: dict[uuid.UUID, dict[AttendanceStatus, int]] = {}
    for submission_id, attendance_status, count in status_count_rows:
        counts_by_submission.setdefault(submission_id, {})[
            attendance_status
        ] = int(count)

    recent_updates: dict[uuid.UUID, TeacherTodayUpdateResponse] = {}
    if classroom_ids:
        update_rows = (
            await session.execute(
                select(
                    StudentUpdate.id,
                    StudentUpdate.classroom_id,
                    StudentUpdate.target_type,
                    StudentUpdate.title,
                    StudentUpdate.teacher_workos_user_id,
                    func.count(StudentUpdateRecipient.id).label(
                        "recipient_count"
                    ),
                    StudentUpdate.created_at,
                )
                .outerjoin(
                    StudentUpdateRecipient,
                    StudentUpdateRecipient.student_update_id == StudentUpdate.id,
                )
                .where(
                    StudentUpdate.organization_id == organization_id,
                    StudentUpdate.classroom_id.in_(classroom_ids),
                )
                .group_by(
                    StudentUpdate.id,
                    StudentUpdate.classroom_id,
                    StudentUpdate.target_type,
                    StudentUpdate.title,
                    StudentUpdate.created_at,
                )
                .order_by(StudentUpdate.created_at.desc(), StudentUpdate.id.desc())
            )
        ).all()
        for (
            update_id,
            classroom_id,
            target_type,
            title,
            update_teacher_id,
            recipient_count,
            created_at,
        ) in update_rows:
            if classroom_id in recent_updates:
                continue
            recent_updates[classroom_id] = TeacherTodayUpdateResponse(
                id=update_id,
                title=title,
                target_type=target_type,
                recipient_count=int(recipient_count),
                created_at=created_at,
                authored_by_current_teacher=update_teacher_id == user_id,
            )

    classrooms = []
    for classroom_id, classroom_name, assignment_role, student_count in classroom_rows:
        submission = submissions_by_classroom.get(classroom_id)
        status_counts = counts_by_submission.get(submission.id, {}) if submission else {}
        classrooms.append(
            TeacherTodayClassroomResponse(
                id=classroom_id,
                name=classroom_name,
                assignment_role=assignment_role,
                active_student_count=int(student_count),
                attendance=TeacherTodayAttendanceResponse(
                    status=(
                        TeacherTodayAttendanceStatus.SUBMITTED
                        if submission
                        else TeacherTodayAttendanceStatus.NOT_STARTED
                    ),
                    recorded_student_count=sum(status_counts.values()),
                    exception_count=sum(
                        status_counts.get(attendance_status, 0)
                        for attendance_status in (
                            AttendanceStatus.ABSENT,
                            AttendanceStatus.LATE,
                            AttendanceStatus.EXCUSED,
                        )
                    ),
                    submitted_at=submission.submitted_at if submission else None,
                    updated_at=submission.updated_at if submission else None,
                ),
                recent_update=recent_updates.get(classroom_id),
            )
        )

    return TeacherTodayResponse(
        school_date=school_date,
        current_school_date=current_date,
        day_status=day_status,
        can_submit_attendance=day_status == TeacherTodayDayStatus.INSTRUCTIONAL,
        ai_teacher_draft_enabled=school.ai_teacher_draft_enabled,
        classrooms=classrooms,
    )
