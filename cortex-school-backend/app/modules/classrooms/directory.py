"""Year-scoped admin rosters and attendance, using a fixed number of queries."""
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.academic_years.services import _get_academic_year
from modules.attendance.models import AttendanceRecord, AttendanceStatus, AttendanceSubmission
from modules.attendance.services import current_school_date
from modules.classrooms.models import ClassEnrollment, Classroom, TeacherAssignment
from modules.classrooms.schemas import (
    DirectoryAttendanceResponse, DirectoryClassroomResponse,
    DirectoryStudentResponse, SchoolDirectoryResponse, TeacherAssignmentResponse,
)
from modules.enrollments.models import Enrollment
from modules.students.models import Student
from modules.students.services import guardian_ids_by_student


async def get_school_directory(
    session: AsyncSession, year_id: uuid.UUID, current_user: dict,
) -> SchoolDirectoryResponse:
    year = await _get_academic_year(session, year_id, current_user)
    organization_id = year.organization_id
    today = await current_school_date(session, organization_id)
    roster_date = min(max(today, year.starts_on), year.ends_on)
    attendance_through = min(today, year.ends_on) if today >= year.starts_on else None
    classrooms = (await session.scalars(
        select(Classroom).where(Classroom.academic_year_id == year.id)
        .order_by(Classroom.name, Classroom.id)
    )).all()
    people = (await session.execute(
        select(Student, Enrollment.id)
        .outerjoin(Enrollment, and_(Enrollment.student_id == Student.id, Enrollment.academic_year_id == year.id))
        .where(Student.organization_id == organization_id)
        .order_by(Student.last_name, Student.first_name, Student.id)
    )).all()
    placements = (await session.execute(
        select(ClassEnrollment, Enrollment.student_id)
        .join(Enrollment, Enrollment.id == ClassEnrollment.enrollment_id)
        .join(Student, Student.id == Enrollment.student_id)
        .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
        .where(
            Enrollment.academic_year_id == year.id, Classroom.academic_year_id == year.id,
            Student.organization_id == organization_id,
            ClassEnrollment.effective_from <= roster_date,
            or_(ClassEnrollment.effective_until.is_(None), ClassEnrollment.effective_until > roster_date),
        )
        .order_by(ClassEnrollment.effective_from.desc(), ClassEnrollment.id.desc())
    )).all()
    placements_by_student = {}
    for placement, student_id in placements:
        placements_by_student.setdefault(student_id, placement)
    assignments = (await session.scalars(
        select(TeacherAssignment)
        .join(Classroom, Classroom.id == TeacherAssignment.classroom_id)
        .where(
            Classroom.academic_year_id == year.id,
            TeacherAssignment.effective_from <= roster_date,
            or_(TeacherAssignment.effective_until.is_(None), TeacherAssignment.effective_until > roster_date),
        )
        .order_by(TeacherAssignment.role, TeacherAssignment.teacher_workos_user_id)
    )).all()

    attendance_by_student = {}
    if attendance_through is not None:
        # Transfers can leave two records on one date. Use the most recently
        # updated submitted record, exactly once per student and school day.
        daily = (
            select(
                Enrollment.student_id.label("student_id"), AttendanceRecord.status.label("status"),
                func.row_number().over(
                    partition_by=(Enrollment.student_id, AttendanceRecord.school_date),
                    order_by=(AttendanceRecord.updated_at.desc(), AttendanceRecord.id.desc()),
                ).label("position"),
            )
            .select_from(AttendanceRecord)
            .join(AttendanceSubmission, and_(
                AttendanceSubmission.id == AttendanceRecord.submission_id,
                AttendanceSubmission.school_date == AttendanceRecord.school_date,
            ))
            .join(ClassEnrollment, ClassEnrollment.id == AttendanceRecord.class_enrollment_id)
            .join(Classroom, and_(Classroom.id == ClassEnrollment.classroom_id, Classroom.id == AttendanceSubmission.classroom_id))
            .join(Enrollment, Enrollment.id == ClassEnrollment.enrollment_id)
            .join(Student, Student.id == Enrollment.student_id)
            .where(
                Student.organization_id == organization_id,
                Enrollment.academic_year_id == year.id, Classroom.academic_year_id == year.id,
                AttendanceRecord.school_date.between(year.starts_on, attendance_through),
            ).subquery()
        )
        rows = await session.execute(
            select(daily.c.student_id, func.count().label("recorded_days"), *(
                func.count().filter(daily.c.status == status).label(status.value)
                for status in AttendanceStatus
            )).where(daily.c.position == 1).group_by(daily.c.student_id)
        )
        for row in rows.mappings():
            attendance_by_student[row["student_id"]] = DirectoryAttendanceResponse(
                present=row["present"], late=row["late"], absent=row["absent"], excused=row["excused"],
                recorded_days=row["recorded_days"],
                rate=(row["present"] + row["late"]) / row["recorded_days"] * 100,
            )

    guardians = await guardian_ids_by_student(session, organization_id, [student.id for student, _ in people])
    student_rows = []
    for student, enrollment_id in people:
        placement = placements_by_student.get(student.id)
        student_rows.append(DirectoryStudentResponse(
            id=student.id, first_name=student.first_name, last_name=student.last_name,
            enrollment_id=enrollment_id, placement_id=placement.id if placement else None,
            classroom_id=placement.classroom_id if placement else None,
            attendance=attendance_by_student.get(student.id, DirectoryAttendanceResponse()),
            guardian_ids=guardians.get(student.id, []),
        ))
    teachers_by_class = {}
    students_by_class = {}
    for assignment in assignments:
        teachers_by_class.setdefault(assignment.classroom_id, []).append(
            TeacherAssignmentResponse.model_validate(assignment)
        )
    for student in student_rows:
        if student.classroom_id is not None:
            students_by_class.setdefault(student.classroom_id, []).append(student.id)
    return SchoolDirectoryResponse(
        year_id=year.id, year_name=year.name, year_status=year.status,
        school_date=today, roster_date=roster_date,
        attendance_from=year.starts_on, attendance_through=attendance_through,
        students=student_rows,
        classrooms=[DirectoryClassroomResponse(
            id=classroom.id, name=classroom.name,
            teachers=teachers_by_class.get(classroom.id, []),
            student_ids=students_by_class.get(classroom.id, []),
        ) for classroom in classrooms],
    )
