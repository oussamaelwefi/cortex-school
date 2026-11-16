import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.attendance.models import (
    AttendanceRecord,
    AttendanceSubmission,
)
from modules.attendance.services import (
    _current_school_date,
    _get_school,
    _is_instructional_day,
)
from modules.classrooms.models import ClassEnrollment, Classroom
from modules.enrollments.models import Enrollment
from modules.student_registration.models import (
    StudentRegistrationRequest,
    StudentRegistrationStatus,
)
from modules.student_updates.models import (
    GuardianUpdateState,
    StudentUpdate,
    StudentUpdateActorRole,
    StudentUpdateEvent,
    StudentUpdateEventType,
    StudentUpdateRecipient,
)
from modules.student_updates.services import (
    build_guardian_feed_item,
    build_guardian_event_response,
    list_guardian_events,
    require_guardian_recipient,
)
from modules.students.models import GuardianStudent, Student

from .schemas import (
    GuardianAttendanceActivity,
    GuardianAttendanceSnapshot,
    GuardianAttendanceSummary,
    GuardianFamilyActivity,
    GuardianFamilyChildResponse,
    GuardianFamilyFeedResponse,
    GuardianFamilyStudentResponse,
    GuardianFamilyUpdateDetailResponse,
    GuardianPlacementResponse,
    GuardianRegistrationRequestResponse,
    GuardianUpdateActivity,
    GuardianUpdateEventActivity,
    GuardianUpdateSummary,
)


def _guardian_scope(current_user: dict) -> tuple[str, str]:
    guardian_id = current_user.get("user_id")
    organization_id = current_user.get("organization_id")
    if not guardian_id or not organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active guardian membership required",
        )
    return guardian_id, organization_id


async def _linked_students(
    session: AsyncSession,
    guardian_id: str,
    organization_id: str,
) -> list[Student]:
    return list(
        (
            await session.scalars(
                select(Student)
                .join(GuardianStudent, GuardianStudent.student_id == Student.id)
                .where(
                    GuardianStudent.guardian_workos_user_id == guardian_id,
                    Student.organization_id == organization_id,
                )
                .order_by(Student.last_name, Student.first_name, Student.id)
            )
        ).all()
    )


async def _active_year(
    session: AsyncSession,
    organization_id: str,
    school_date: date,
) -> AcademicYear | None:
    return await session.scalar(
        select(AcademicYear)
        .where(
            AcademicYear.organization_id == organization_id,
            AcademicYear.status == AcademicYearStatus.ACTIVE,
            AcademicYear.starts_on <= school_date,
            AcademicYear.ends_on >= school_date,
        )
        .order_by(AcademicYear.starts_on.desc(), AcademicYear.id)
        .limit(1)
    )


async def _school_context(
    session: AsyncSession,
    organization_id: str,
) -> tuple[Any, date, AcademicYear | None, bool]:
    school = await _get_school(session, organization_id)
    school_date = _current_school_date(school)
    year = await _active_year(session, organization_id, school_date)
    instructional = (
        year is not None
        and await _is_instructional_day(session, year, school_date, school)
    )
    return school, school_date, year, instructional


async def _placements(
    session: AsyncSession,
    student_ids: list[uuid.UUID],
    organization_id: str,
    year: AcademicYear | None,
    school_date: date,
) -> tuple[dict[uuid.UUID, dict[str, Any]], set[uuid.UUID]]:
    if not student_ids or year is None:
        return {}, set()

    enrolled_ids = set(
        (
            await session.scalars(
                select(Enrollment.student_id)
                .where(
                    Enrollment.student_id.in_(student_ids),
                    Enrollment.academic_year_id == year.id,
                )
            )
        ).all()
    )
    rows = (
        await session.execute(
            select(
                Enrollment.student_id,
                ClassEnrollment.id,
                Classroom.id,
                Classroom.name,
                AcademicYear.id,
                AcademicYear.name,
            )
            .join(
                ClassEnrollment,
                ClassEnrollment.enrollment_id == Enrollment.id,
            )
            .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
            .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
            .where(
                Enrollment.student_id.in_(student_ids),
                Enrollment.academic_year_id == year.id,
                AcademicYear.organization_id == organization_id,
                ClassEnrollment.effective_from <= school_date,
                or_(
                    ClassEnrollment.effective_until.is_(None),
                    ClassEnrollment.effective_until > school_date,
                ),
            )
            .order_by(
                Enrollment.student_id,
                ClassEnrollment.effective_from.desc(),
                ClassEnrollment.id,
            )
        )
    ).all()
    placements: dict[uuid.UUID, dict[str, Any]] = {}
    for (
        student_id,
        class_enrollment_id,
        classroom_id,
        classroom_name,
        academic_year_id,
        academic_year_name,
    ) in rows:
        placements.setdefault(
            student_id,
            {
                "class_enrollment_id": class_enrollment_id,
                "classroom_id": classroom_id,
                "classroom_name": classroom_name,
                "academic_year_id": academic_year_id,
                "academic_year_name": academic_year_name,
            },
        )
    return placements, enrolled_ids


def _placement_response(
    student_id: uuid.UUID,
    placements: dict[uuid.UUID, dict[str, Any]],
    enrolled_ids: set[uuid.UUID],
) -> GuardianPlacementResponse:
    placement = placements.get(student_id)
    if placement is None:
        return GuardianPlacementResponse(
            state="not_placed" if student_id in enrolled_ids else "not_enrolled"
        )
    return GuardianPlacementResponse(
        state="current",
        classroom_id=placement["classroom_id"],
        classroom_name=placement["classroom_name"],
        academic_year_id=placement["academic_year_id"],
        academic_year_name=placement["academic_year_name"],
    )


async def _submitted_attendance(
    session: AsyncSession,
    student_ids: list[uuid.UUID],
    organization_id: str,
    *,
    school_date: date | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int | None = None,
) -> list[tuple[AttendanceRecord, uuid.UUID, uuid.UUID, str, uuid.UUID]]:
    if not student_ids:
        return []
    query = (
        select(
            AttendanceRecord,
            Student.id,
            Classroom.id,
            Classroom.name,
            ClassEnrollment.id,
        )
        .join(
            AttendanceSubmission,
            AttendanceSubmission.id == AttendanceRecord.submission_id,
        )
        .join(
            ClassEnrollment,
            ClassEnrollment.id == AttendanceRecord.class_enrollment_id,
        )
        .join(Enrollment, Enrollment.id == ClassEnrollment.enrollment_id)
        .join(Student, Student.id == Enrollment.student_id)
        .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
        .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
        .where(
            Student.id.in_(student_ids),
            Student.organization_id == organization_id,
            AcademicYear.organization_id == organization_id,
        )
    )
    if school_date is not None:
        query = query.where(AttendanceRecord.school_date == school_date)
    if from_date is not None:
        query = query.where(AttendanceRecord.school_date >= from_date)
    if to_date is not None:
        query = query.where(AttendanceRecord.school_date <= to_date)
    query = query.order_by(
        AttendanceRecord.school_date.desc(), AttendanceRecord.id.desc()
    )
    if limit is not None:
        query = query.limit(limit)
    return list((await session.execute(query)).all())


def _submitted_snapshot(
    record: AttendanceRecord,
    classroom_id: uuid.UUID,
    classroom_name: str,
) -> GuardianAttendanceSnapshot:
    return GuardianAttendanceSnapshot(
        state="submitted",
        school_date=record.school_date,
        status=record.status,
        note=record.note,
        classroom_id=classroom_id,
        classroom_name=classroom_name,
        updated_at=record.updated_at,
    )


async def _update_rows(
    session: AsyncSession,
    student_ids: list[uuid.UUID],
    guardian_id: str,
    organization_id: str,
) -> list[
    tuple[
        StudentUpdateRecipient,
        StudentUpdate,
        Classroom,
        GuardianUpdateState | None,
    ]
]:
    if not student_ids:
        return []
    query = (
        select(
            StudentUpdateRecipient,
            StudentUpdate,
            Classroom,
            GuardianUpdateState,
        )
        .join(
            StudentUpdate,
            StudentUpdate.id == StudentUpdateRecipient.student_update_id,
        )
        .join(Classroom, Classroom.id == StudentUpdate.classroom_id)
        .join(Student, Student.id == StudentUpdateRecipient.student_id)
        .join(GuardianStudent, GuardianStudent.student_id == Student.id)
        .outerjoin(
            GuardianUpdateState,
            and_(
                GuardianUpdateState.recipient_id == StudentUpdateRecipient.id,
                GuardianUpdateState.guardian_workos_user_id == guardian_id,
            ),
        )
        .where(
            StudentUpdateRecipient.student_id.in_(student_ids),
            StudentUpdate.organization_id == organization_id,
            Student.organization_id == organization_id,
            GuardianStudent.guardian_workos_user_id == guardian_id,
        )
        .order_by(
            StudentUpdate.created_at.desc(),
            StudentUpdate.id.desc(),
            StudentUpdateRecipient.id.desc(),
        )
    )
    return list((await session.execute(query)).all())


def _is_unread(state: GuardianUpdateState | None) -> bool:
    return state is None or state.read_at is None


def _needs_response(
    student_update: StudentUpdate,
    state: GuardianUpdateState | None,
) -> bool:
    return student_update.requires_acknowledgement and (
        state is None or state.acknowledged_at is None
    )


def _update_summary(
    recipient: StudentUpdateRecipient,
    student_update: StudentUpdate,
    state: GuardianUpdateState | None,
) -> GuardianUpdateSummary:
    unread = _is_unread(state)
    acknowledged = state is not None and state.acknowledged_at is not None
    return GuardianUpdateSummary(
        recipient_id=recipient.id,
        update_id=student_update.id,
        target_type=student_update.target_type,
        title=student_update.title,
        occurred_at=student_update.created_at,
        author_label="Teacher",
        unread=unread,
        requires_acknowledgement=student_update.requires_acknowledgement,
        acknowledged=acknowledged,
        needs_response=_needs_response(student_update, state),
        allows_replies=student_update.allows_replies,
    )


async def _registration_requests(
    session: AsyncSession,
    guardian_id: str,
    organization_id: str,
) -> list[GuardianRegistrationRequestResponse]:
    rows = (
        await session.execute(
            select(StudentRegistrationRequest, AcademicYear)
            .join(
                AcademicYear,
                AcademicYear.id == StudentRegistrationRequest.academic_year_id,
            )
            .where(
                StudentRegistrationRequest.guardian_workos_user_id == guardian_id,
                StudentRegistrationRequest.organization_id == organization_id,
                StudentRegistrationRequest.status.in_(
                    (
                        StudentRegistrationStatus.PENDING,
                        StudentRegistrationStatus.REJECTED,
                    )
                ),
            )
            .order_by(StudentRegistrationRequest.created_at.desc())
        )
    ).all()
    return [
        GuardianRegistrationRequestResponse(
            id=request.id,
            child_first_name=request.child_first_name,
            child_last_name=request.child_last_name,
            academic_year_id=request.academic_year_id,
            academic_year_name=year.name,
            status=request.status,
            rejection_reason=request.rejection_reason,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )
        for request, year in rows
    ]


async def get_family_overview(
    session: AsyncSession,
    current_user: dict,
) -> tuple[
    date,
    str,
    list[GuardianFamilyChildResponse],
    list[GuardianRegistrationRequestResponse],
]:
    guardian_id, organization_id = _guardian_scope(current_user)
    school, school_date, year, instructional = await _school_context(
        session, organization_id
    )
    students = await _linked_students(session, guardian_id, organization_id)
    student_ids = [student.id for student in students]
    placements, enrolled_ids = await _placements(
        session, student_ids, organization_id, year, school_date
    )

    today_rows = await _submitted_attendance(
        session,
        student_ids,
        organization_id,
        school_date=school_date,
    )
    latest_rows = await _submitted_attendance(
        session,
        student_ids,
        organization_id,
        limit=None,
    )
    today_by_student: dict[uuid.UUID, tuple[AttendanceRecord, uuid.UUID, str, uuid.UUID]] = {}
    latest_by_student: dict[uuid.UUID, tuple[AttendanceRecord, uuid.UUID, str, uuid.UUID]] = {}
    for record, student_id, classroom_id, classroom_name, class_enrollment_id in today_rows:
        current_placement = placements.get(student_id)
        if (
            student_id not in today_by_student
            or current_placement is None
            or current_placement["class_enrollment_id"] == class_enrollment_id
        ):
            today_by_student[student_id] = (
                record,
                classroom_id,
                classroom_name,
                class_enrollment_id,
            )
    for record, student_id, classroom_id, classroom_name, class_enrollment_id in latest_rows:
        latest_by_student.setdefault(
            student_id,
            (record, classroom_id, classroom_name, class_enrollment_id),
        )

    update_rows = await _update_rows(
        session, student_ids, guardian_id, organization_id
    )
    latest_updates: dict[uuid.UUID, tuple[StudentUpdateRecipient, StudentUpdate, GuardianUpdateState | None]] = {}
    unread_counts: dict[uuid.UUID, int] = {}
    needs_response_counts: dict[uuid.UUID, int] = {}
    for recipient, student_update, _, state in update_rows:
        latest_updates.setdefault(
            recipient.student_id, (recipient, student_update, state)
        )
        if _is_unread(state):
            unread_counts[recipient.student_id] = (
                unread_counts.get(recipient.student_id, 0) + 1
            )
        if _needs_response(student_update, state):
            needs_response_counts[recipient.student_id] = (
                needs_response_counts.get(recipient.student_id, 0) + 1
            )

    children: list[GuardianFamilyChildResponse] = []
    for student in students:
        placement = _placement_response(student.id, placements, enrolled_ids)
        today = today_by_student.get(student.id)
        if today is not None:
            today_snapshot = _submitted_snapshot(today[0], today[1], today[2])
        else:
            today_snapshot = GuardianAttendanceSnapshot(
                state="not_submitted" if placement.state == "current" and instructional else "not_expected",
                school_date=school_date,
                classroom_id=placement.classroom_id,
                classroom_name=placement.classroom_name,
            )
        latest = latest_by_student.get(student.id)
        latest_snapshot = (
            _submitted_snapshot(latest[0], latest[1], latest[2])
            if latest is not None
            else None
        )
        latest_update = latest_updates.get(student.id)
        children.append(
            GuardianFamilyChildResponse(
                id=student.id,
                first_name=student.first_name,
                last_name=student.last_name,
                placement=placement,
                attendance=GuardianAttendanceSummary(
                    today=today_snapshot,
                    latest_submitted=latest_snapshot,
                ),
                latest_update=(
                    _update_summary(*latest_update)
                    if latest_update is not None
                    else None
                ),
                unread_update_count=unread_counts.get(student.id, 0),
                needs_response_count=needs_response_counts.get(student.id, 0),
            )
        )

    requests = await _registration_requests(session, guardian_id, organization_id)
    return school_date, school.timezone, children, requests


def _school_datetime_bounds(
    timezone_name: str,
    from_date: date | None,
    to_date: date | None,
) -> tuple[datetime | None, datetime | None]:
    timezone_info = ZoneInfo(timezone_name)
    start = (
        datetime.combine(from_date, time.min, tzinfo=timezone_info).astimezone(
            timezone.utc
        )
        if from_date is not None
        else None
    )
    end = (
        datetime.combine(
            to_date + timedelta(days=1),
            time.min,
            tzinfo=timezone_info,
        ).astimezone(timezone.utc)
        if to_date is not None
        else None
    )
    return start, end


def _date_range_error(from_date: date | None, to_date: date | None) -> None:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from must be on or before to",
        )


def _update_activity(
    recipient: StudentUpdateRecipient,
    student_update: StudentUpdate,
    classroom: Classroom,
    state: GuardianUpdateState | None,
) -> GuardianUpdateActivity:
    return GuardianUpdateActivity(
        type="update",
        id=recipient.id,
        student_id=recipient.student_id,
        occurred_at=student_update.created_at,
        recipient_id=recipient.id,
        update_id=student_update.id,
        classroom_id=classroom.id,
        classroom_name=classroom.name,
        target_type=student_update.target_type,
        title=student_update.title,
        body=student_update.body,
        due_at=student_update.due_at,
        author_label="Teacher",
        status=recipient.status,
        read_at=state.read_at if state else None,
        acknowledged_at=state.acknowledged_at if state else None,
        requires_acknowledgement=student_update.requires_acknowledgement,
        allows_replies=student_update.allows_replies,
    )


def _event_activity(
    event: StudentUpdateEvent,
    recipient: StudentUpdateRecipient,
    student_update: StudentUpdate,
    classroom: Classroom,
    guardian_id: str,
) -> GuardianUpdateEventActivity:
    event_response = build_guardian_event_response(event, guardian_id)
    return GuardianUpdateEventActivity(
        type="update_event",
        id=event.id,
        student_id=recipient.student_id,
        occurred_at=event.created_at,
        recipient_id=recipient.id,
        update_id=student_update.id,
        classroom_id=classroom.id,
        classroom_name=classroom.name,
        title=student_update.title,
        event_type=event.event_type,
        actor_role=event.actor_role,
        author_label=event_response.author_label,
        content=event.content,
        previous_status=event.previous_status,
        new_status=event.new_status,
    )


async def get_family_feed(
    session: AsyncSession,
    student_id: uuid.UUID,
    current_user: dict,
    *,
    limit: int,
    offset: int,
    unread_only: bool,
    from_date: date | None,
    to_date: date | None,
) -> GuardianFamilyFeedResponse:
    guardian_id, organization_id = _guardian_scope(current_user)
    _date_range_error(from_date, to_date)
    student = (
        await session.scalar(
            select(Student)
            .join(GuardianStudent, GuardianStudent.student_id == Student.id)
            .where(
                Student.id == student_id,
                Student.organization_id == organization_id,
                GuardianStudent.guardian_workos_user_id == guardian_id,
            )
        )
    )
    if student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    school, school_date, year, _ = await _school_context(session, organization_id)
    placements, enrolled_ids = await _placements(
        session, [student.id], organization_id, year, school_date
    )
    placement = _placement_response(student.id, placements, enrolled_ids)
    start_at, end_at = _school_datetime_bounds(
        school.timezone, from_date, to_date
    )
    fetch_limit = offset + limit + 1

    attendance_rows = await _submitted_attendance(
        session,
        [student.id],
        organization_id,
        from_date=from_date,
        to_date=to_date,
        limit=fetch_limit,
    )
    items: list[GuardianFamilyActivity] = [
        GuardianAttendanceActivity(
            type="attendance",
            id=record.id,
            student_id=student.id,
            occurred_at=record.updated_at,
            school_date=record.school_date,
            status=record.status,
            note=record.note,
            classroom_id=classroom_id,
            classroom_name=classroom_name,
        )
        for record, _, classroom_id, classroom_name, _ in attendance_rows
    ]

    update_query = (
        select(
            StudentUpdateRecipient,
            StudentUpdate,
            Classroom,
            GuardianUpdateState,
        )
        .join(
            StudentUpdate,
            StudentUpdate.id == StudentUpdateRecipient.student_update_id,
        )
        .join(Classroom, Classroom.id == StudentUpdate.classroom_id)
        .outerjoin(
            GuardianUpdateState,
            and_(
                GuardianUpdateState.recipient_id == StudentUpdateRecipient.id,
                GuardianUpdateState.guardian_workos_user_id == guardian_id,
            ),
        )
        .where(
            StudentUpdateRecipient.student_id == student.id,
            StudentUpdate.organization_id == organization_id,
        )
        .order_by(
            StudentUpdate.created_at.desc(),
            StudentUpdate.id.desc(),
            StudentUpdateRecipient.id.desc(),
        )
    )
    if start_at is not None:
        update_query = update_query.where(StudentUpdate.created_at >= start_at)
    if end_at is not None:
        update_query = update_query.where(StudentUpdate.created_at < end_at)
    if unread_only:
        update_query = update_query.where(
            or_(GuardianUpdateState.id.is_(None), GuardianUpdateState.read_at.is_(None))
        )
    update_query = update_query.limit(fetch_limit)
    update_rows = list((await session.execute(update_query)).all())
    items.extend(
        _update_activity(recipient, student_update, classroom, state)
        for recipient, student_update, classroom, state in update_rows
    )

    event_query = (
        select(
            StudentUpdateEvent,
            StudentUpdateRecipient,
            StudentUpdate,
            Classroom,
            GuardianUpdateState,
        )
        .join(
            StudentUpdateRecipient,
            StudentUpdateRecipient.id == StudentUpdateEvent.recipient_id,
        )
        .join(
            StudentUpdate,
            StudentUpdate.id == StudentUpdateRecipient.student_update_id,
        )
        .join(Classroom, Classroom.id == StudentUpdate.classroom_id)
        .outerjoin(
            GuardianUpdateState,
            and_(
                GuardianUpdateState.recipient_id == StudentUpdateRecipient.id,
                GuardianUpdateState.guardian_workos_user_id == guardian_id,
            ),
        )
        .where(
            StudentUpdateRecipient.student_id == student.id,
            StudentUpdate.organization_id == organization_id,
            StudentUpdateEvent.event_type.not_in((
                StudentUpdateEventType.ASSIGNED,
                StudentUpdateEventType.REMINDER_SENT,
            )),
        )
        .order_by(StudentUpdateEvent.created_at.desc(), StudentUpdateEvent.id.desc())
    )
    if start_at is not None:
        event_query = event_query.where(StudentUpdateEvent.created_at >= start_at)
    if end_at is not None:
        event_query = event_query.where(StudentUpdateEvent.created_at < end_at)
    if unread_only:
        event_query = event_query.where(
            or_(GuardianUpdateState.id.is_(None), GuardianUpdateState.read_at.is_(None))
        )
    event_query = event_query.limit(fetch_limit)
    event_rows = list((await session.execute(event_query)).all())
    items.extend(
        _event_activity(
            event,
            recipient,
            student_update,
            classroom,
            guardian_id,
        )
        for event, recipient, student_update, classroom, _ in event_rows
    )

    # ponytail: merge the three bounded source reads in memory; move to a SQL
    # union/cursor only when feed volume makes offset pagination measurable.
    items.sort(key=lambda item: (item.occurred_at, str(item.id)), reverse=True)
    page_end = offset + limit
    current_week_start = school_date - timedelta(days=school_date.weekday())
    return GuardianFamilyFeedResponse(
        student=GuardianFamilyStudentResponse(
            id=student.id,
            first_name=student.first_name,
            last_name=student.last_name,
            placement=placement,
        ),
        school_date=school_date,
        school_timezone=school.timezone,
        current_week_start=current_week_start,
        current_week_end=school_date,
        ai_guardian_weekly_explanation_enabled=(
            school.ai_guardian_weekly_explanation_enabled
        ),
        items=items[offset:page_end],
        limit=limit,
        offset=offset,
        has_more=len(items) > page_end,
    )


async def get_family_update_detail(
    session: AsyncSession,
    student_id: uuid.UUID,
    recipient_id: uuid.UUID,
    current_user: dict,
):
    _, organization_id = _guardian_scope(current_user)
    row = await require_guardian_recipient(
        session,
        recipient_id,
        current_user,
        expected_student_id=student_id,
    )
    feed_item = build_guardian_feed_item(*row)
    history = await list_guardian_events(
        session, recipient_id, current_user["user_id"]
    )
    school = await _get_school(session, organization_id)
    return GuardianFamilyUpdateDetailResponse(
        **feed_item.model_dump(),
        history=history,
        school_timezone=school.timezone,
    )
