import uuid
from datetime import date

from fastapi import Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.db import db_session
from core.router import APIRouter
from modules.academic_years.models import (
    AcademicYear,
    AcademicYearStatus,
    CalendarEntry,
)
from modules.academic_years.schemas import AcademicCalendarResponse
from modules.academic_years.services import _get_academic_calendar
from modules.attendance.services import current_school_date
from modules.classrooms.models import (
    ClassEnrollment,
    Classroom,
    TeacherAssignment,
)
from modules.classrooms.schemas import (
    TeacherClassroomResponse,
    TeacherClassroomStudentResponse,
)
from modules.classrooms.services import _get_teacher_classroom_access
from modules.enrollments.models import Enrollment
from modules.students.models import Student
from modules.teachers.services import (
    _require_teacher_access,
    _teacher_classroom_response,
    _teacher_classroom_student_response,
    get_teacher_today,
)
from modules.teachers.schemas import TeacherTodayResponse

router = APIRouter(prefix="/teacher", tags=["Teacher Access"])


@router.get("/today", response_model=TeacherTodayResponse)
async def get_teacher_today_workspace(
    school_date: date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await get_teacher_today(session, school_date, current_user)


@router.get("/classrooms/", response_model=list[TeacherClassroomResponse])
async def list_teacher_classrooms(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    user_id, organization_id = _require_teacher_access(current_user)
    today = await current_school_date(session, organization_id)
    rows = (
        await session.execute(
            select(Classroom, AcademicYear, TeacherAssignment)
            .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
            .join(
                TeacherAssignment,
                TeacherAssignment.classroom_id == Classroom.id,
            )
            .where(
                AcademicYear.organization_id == organization_id,
                AcademicYear.status == AcademicYearStatus.ACTIVE,
                AcademicYear.ends_on >= today,
                TeacherAssignment.teacher_workos_user_id == user_id,
                or_(
                    TeacherAssignment.effective_until.is_(None),
                    TeacherAssignment.effective_until > today,
                ),
            )
            .order_by(AcademicYear.starts_on, Classroom.name)
        )
    ).all()
    return [
        _teacher_classroom_response(classroom, year, assignment, today)
        for classroom, year, assignment in rows
    ]


@router.get(
    "/classrooms/{classroom_id}/",
    response_model=TeacherClassroomResponse,
)
async def get_teacher_classroom(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    _, organization_id = _require_teacher_access(current_user)
    today = await current_school_date(session, organization_id)
    classroom, year, assignment = await _get_teacher_classroom_access(
        session,
        classroom_id,
        current_user,
        today,
    )
    return _teacher_classroom_response(classroom, year, assignment, today)


@router.get(
    "/classrooms/{classroom_id}/students/",
    response_model=list[TeacherClassroomStudentResponse],
)
async def list_teacher_classroom_students(
    classroom_id: uuid.UUID,
    search: str | None = Query(default=None, max_length=255),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    _, organization_id = _require_teacher_access(current_user)
    today = await current_school_date(session, organization_id)
    classroom, year, _ = await _get_teacher_classroom_access(
        session,
        classroom_id,
        current_user,
        today,
    )

    query = (
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
            ClassEnrollment.effective_from <= today,
            or_(
                ClassEnrollment.effective_until.is_(None),
                ClassEnrollment.effective_until > today,
            ),
        )
    )

    search_term = search.strip() if search is not None else ""
    if search_term:
        query = query.where(
            or_(
                Student.first_name.icontains(search_term, autoescape=True),
                Student.last_name.icontains(search_term, autoescape=True),
                func.concat(
                    Student.first_name,
                    " ",
                    Student.last_name,
                ).icontains(search_term, autoescape=True),
            )
        )

    rows = (
        await session.execute(
            query.order_by(
                Student.last_name,
                Student.first_name,
            )
        )
    ).all()
    return [
        _teacher_classroom_student_response(
            student,
            enrollment,
            placement,
        )
        for student, enrollment, placement in rows
    ]


@router.get(
    "/classrooms/{classroom_id}/calendar/",
    response_model=AcademicCalendarResponse,
)
async def get_teacher_classroom_calendar(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    _, organization_id = _require_teacher_access(current_user)
    today = await current_school_date(session, organization_id)
    _, year, _ = await _get_teacher_classroom_access(
        session,
        classroom_id,
        current_user,
        today,
    )
    calendar = await _get_academic_calendar(session, year)
    entries = list(
        (
            await session.scalars(
                select(CalendarEntry)
                .where(CalendarEntry.academic_calendar_id == calendar.id)
                .order_by(CalendarEntry.starts_on, CalendarEntry.title)
            )
        ).all()
    )
    return AcademicCalendarResponse(
        id=calendar.id,
        academic_year_id=calendar.academic_year_id,
        entries=entries,
        created_at=calendar.created_at,
        updated_at=calendar.updated_at,
    )
