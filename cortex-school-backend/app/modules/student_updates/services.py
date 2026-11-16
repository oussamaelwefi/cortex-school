import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, update as sqlalchemy_update
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import utcnow
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.attendance.services import current_school_date
from modules.classrooms.models import (
    ClassEnrollment,
    Classroom,
    TeacherAssignment,
)
from modules.enrollments.models import Enrollment
from modules.reminders.policy import get_guardian_reminder_sources
from modules.student_updates.models import (
    GuardianUpdateState,
    StudentUpdate,
    StudentUpdateActorRole,
    StudentUpdateEvent,
    StudentUpdateEventType,
    StudentUpdateNotification,
    StudentUpdateNotificationType,
    StudentUpdateRecipient,
    StudentUpdateStatus,
    StudentUpdateTargetType,
)
from modules.student_updates.schemas import (
    AdminStudentUpdateItemResponse,
    GuardianFeedItemResponse,
    GuardianUpdateEventResponse,
    StudentUpdateCreateRequest,
    StudentUpdateAudiencePreviewRequest,
    StudentUpdateAudiencePreviewResponse,
    StudentUpdateEventResponse,
    StudentUpdateNotificationResponse,
    StudentUpdateRecipientResponse,
    StudentUpdateResponse,
    StudentsTarget,
    UpdateTarget,
)
from modules.students.models import GuardianStudent, Student
from modules.teachers.services import _require_teacher_access


def is_overdue(
    due_at: datetime | None,
    recipient_status: StudentUpdateStatus,
    *,
    now: datetime | None = None,
) -> bool:
    return bool(
        due_at is not None
        and due_at < (now or utcnow())
        and recipient_status != StudentUpdateStatus.COMPLETED
    )


async def require_active_teacher_classroom(
    session: AsyncSession,
    classroom_id: uuid.UUID,
    current_user: dict,
) -> tuple[Classroom, AcademicYear]:
    teacher_id, organization_id = _require_teacher_access(current_user)
    today = await current_school_date(session, organization_id)
    row = (
        await session.execute(
            select(Classroom, AcademicYear)
            .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
            .join(TeacherAssignment, TeacherAssignment.classroom_id == Classroom.id)
            .where(
                Classroom.id == classroom_id,
                AcademicYear.organization_id == organization_id,
                AcademicYear.status == AcademicYearStatus.ACTIVE,
                AcademicYear.starts_on <= today,
                AcademicYear.ends_on >= today,
                TeacherAssignment.teacher_workos_user_id == teacher_id,
                TeacherAssignment.effective_from <= today,
                or_(
                    TeacherAssignment.effective_until.is_(None),
                    TeacherAssignment.effective_until > today,
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


async def _get_active_roster(
    session: AsyncSession,
    classroom: Classroom,
    organization_id: str,
    school_date,
) -> list[tuple[Student, ClassEnrollment]]:
    return list(
        (
            await session.execute(
                select(Student, ClassEnrollment)
                .join(Enrollment, Enrollment.student_id == Student.id)
                .join(
                    ClassEnrollment,
                    ClassEnrollment.enrollment_id == Enrollment.id,
                )
                .where(
                    ClassEnrollment.classroom_id == classroom.id,
                    Enrollment.academic_year_id == classroom.academic_year_id,
                    Student.organization_id == organization_id,
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


async def _guardian_ids_by_student(
    session: AsyncSession,
    student_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[str]]:
    if not student_ids:
        return {}
    rows = (
        await session.execute(
            select(
                GuardianStudent.student_id,
                GuardianStudent.guardian_workos_user_id,
            ).where(GuardianStudent.student_id.in_(student_ids))
        )
    ).all()
    result: dict[uuid.UUID, list[str]] = {}
    for student_id, guardian_id in rows:
        result.setdefault(student_id, []).append(guardian_id)
    return result


def _new_event(
    recipient_id: uuid.UUID,
    event_type: StudentUpdateEventType,
    actor_id: str,
    actor_role: StudentUpdateActorRole,
    *,
    content: str | None = None,
    previous_status: StudentUpdateStatus | None = None,
    new_status: StudentUpdateStatus | None = None,
) -> StudentUpdateEvent:
    return StudentUpdateEvent(
        id=uuid.uuid4(),
        recipient_id=recipient_id,
        event_type=event_type,
        actor_workos_user_id=actor_id,
        actor_role=actor_role,
        content=content,
        previous_status=previous_status,
        new_status=new_status,
    )


def _add_guardian_notifications(
    session: AsyncSession,
    organization_id: str,
    recipient_id: uuid.UUID,
    event_id: uuid.UUID,
    guardian_ids: list[str],
    notification_type: StudentUpdateNotificationType,
) -> None:
    for guardian_id in guardian_ids:
        session.add(
            StudentUpdateNotification(
                organization_id=organization_id,
                guardian_workos_user_id=guardian_id,
                recipient_id=recipient_id,
                event_id=event_id,
                notification_type=notification_type,
            )
        )


async def _ensure_guardian_states(
    session: AsyncSession,
    recipient_id: uuid.UUID,
    guardian_ids: list[str],
) -> None:
    if not guardian_ids:
        return
    existing_ids = set(
        (
            await session.scalars(
                select(GuardianUpdateState.guardian_workos_user_id).where(
                    GuardianUpdateState.recipient_id == recipient_id,
                    GuardianUpdateState.guardian_workos_user_id.in_(guardian_ids),
                )
            )
        ).all()
    )
    for guardian_id in set(guardian_ids) - existing_ids:
        session.add(
            GuardianUpdateState(
                recipient_id=recipient_id,
                guardian_workos_user_id=guardian_id,
            )
        )


# Teacher operations
async def _resolve_teacher_update_audience(
    session: AsyncSession,
    classroom_id: uuid.UUID,
    target: UpdateTarget,
    current_user: dict,
) -> tuple[Classroom, list[tuple[Student, ClassEnrollment]], StudentUpdateTargetType]:
    _, organization_id = _require_teacher_access(current_user)
    classroom, _ = await require_active_teacher_classroom(
        session, classroom_id, current_user
    )
    school_date = await current_school_date(session, organization_id)
    roster = await _get_active_roster(
        session, classroom, organization_id, school_date
    )
    if isinstance(target, StudentsTarget):
        requested_ids = set(target.student_ids)
        roster = [row for row in roster if row[0].id in requested_ids]
        if {student.id for student, _ in roster} != requested_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Every selected student must be active in the classroom",
            )
        target_type = StudentUpdateTargetType.STUDENTS
    else:
        target_type = StudentUpdateTargetType.CLASSROOM

    if not roster:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The update must have at least one active student",
        )
    return classroom, roster, target_type


async def preview_teacher_update_audience(
    session: AsyncSession,
    payload: StudentUpdateAudiencePreviewRequest,
    current_user: dict,
) -> StudentUpdateAudiencePreviewResponse:
    classroom, roster, target_type = await _resolve_teacher_update_audience(
        session, payload.classroom_id, payload.target, current_user
    )
    guardian_ids_by_student = await _guardian_ids_by_student(
        session, [student.id for student, _ in roster]
    )
    unique_guardian_ids = {
        guardian_id
        for guardian_ids in guardian_ids_by_student.values()
        for guardian_id in guardian_ids
    }
    return StudentUpdateAudiencePreviewResponse(
        classroom_id=classroom.id,
        target_type=target_type,
        student_names=[
            f"{student.first_name} {student.last_name}"
            for student, _ in roster
        ],
        student_count=len(roster),
        unique_guardian_count=len(unique_guardian_ids),
    )


async def create_student_update(
    session: AsyncSession,
    payload: StudentUpdateCreateRequest,
    current_user: dict,
) -> StudentUpdate:
    teacher_id, organization_id = _require_teacher_access(current_user)
    now = utcnow()
    if payload.due_at is not None and payload.due_at <= now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="due_at must be in the future",
        )

    async with session.begin():
        classroom, roster, target_type = await _resolve_teacher_update_audience(
            session, payload.classroom_id, payload.target, current_user
        )

        student_update = StudentUpdate(
            id=uuid.uuid4(),
            organization_id=organization_id,
            classroom_id=classroom.id,
            teacher_workos_user_id=teacher_id,
            target_type=target_type,
            title=payload.title,
            body=payload.body,
            due_at=payload.due_at,
            requires_acknowledgement=payload.requires_acknowledgement,
            allows_replies=payload.allows_replies,
        )
        session.add(student_update)
        await session.flush()

        guardian_ids_by_student = await _guardian_ids_by_student(
            session, [student.id for student, _ in roster]
        )
        recipients: list[tuple[StudentUpdateRecipient, Student]] = []
        for student, placement in roster:
            recipient = StudentUpdateRecipient(
                id=uuid.uuid4(),
                student_update_id=student_update.id,
                student_id=student.id,
                class_enrollment_id=placement.id,
                status=StudentUpdateStatus.ASSIGNED,
            )
            recipients.append((recipient, student))
            session.add(recipient)
        await session.flush()

        events: list[tuple[StudentUpdateEvent, StudentUpdateRecipient, Student]] = []
        for recipient, student in recipients:
            event = _new_event(
                recipient.id,
                StudentUpdateEventType.ASSIGNED,
                teacher_id,
                StudentUpdateActorRole.TEACHER,
                new_status=StudentUpdateStatus.ASSIGNED,
            )
            events.append((event, recipient, student))
            session.add(event)
        await session.flush()

        for event, recipient, student in events:
            guardian_ids = guardian_ids_by_student.get(student.id, [])
            for guardian_id in guardian_ids:
                session.add(
                    GuardianUpdateState(
                        recipient_id=recipient.id,
                        guardian_workos_user_id=guardian_id,
                    )
                )
            _add_guardian_notifications(
                session,
                organization_id,
                recipient.id,
                event.id,
                guardian_ids,
                StudentUpdateNotificationType.UPDATE_ASSIGNED,
            )

    return student_update


async def require_teacher_update(
    session: AsyncSession,
    update_id: uuid.UUID,
    current_user: dict,
) -> tuple[StudentUpdate, Classroom]:
    teacher_id, organization_id = _require_teacher_access(current_user)
    row = (
        await session.execute(
            select(StudentUpdate, Classroom)
            .join(Classroom, Classroom.id == StudentUpdate.classroom_id)
            .where(
                StudentUpdate.id == update_id,
                StudentUpdate.organization_id == organization_id,
                StudentUpdate.teacher_workos_user_id == teacher_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student update not found",
        )
    return row


async def require_teacher_recipient(
    session: AsyncSession,
    update_id: uuid.UUID,
    recipient_id: uuid.UUID,
    current_user: dict,
    *,
    lock_recipient: bool = False,
) -> tuple[StudentUpdateRecipient, StudentUpdate, Student]:
    teacher_id, organization_id = _require_teacher_access(current_user)
    query = (
        select(StudentUpdateRecipient, StudentUpdate, Student)
        .join(
            StudentUpdate,
            StudentUpdate.id == StudentUpdateRecipient.student_update_id,
        )
        .join(Student, Student.id == StudentUpdateRecipient.student_id)
        .where(
            StudentUpdate.id == update_id,
            StudentUpdateRecipient.id == recipient_id,
            StudentUpdate.organization_id == organization_id,
            StudentUpdate.teacher_workos_user_id == teacher_id,
        )
    )
    if lock_recipient:
        query = query.with_for_update(of=StudentUpdateRecipient)
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student update recipient not found",
        )
    return row


def build_recipient_response(
    recipient: StudentUpdateRecipient,
    student: Student,
    due_at: datetime | None,
) -> StudentUpdateRecipientResponse:
    return StudentUpdateRecipientResponse(
        id=recipient.id,
        student_id=student.id,
        class_enrollment_id=recipient.class_enrollment_id,
        first_name=student.first_name,
        last_name=student.last_name,
        status=recipient.status,
        acknowledged_at=recipient.acknowledged_at,
        completed_at=recipient.completed_at,
        is_overdue=is_overdue(due_at, recipient.status),
        created_at=recipient.created_at,
        updated_at=recipient.updated_at,
    )


async def build_update_response(
    session: AsyncSession,
    student_update: StudentUpdate,
    classroom: Classroom | None = None,
) -> StudentUpdateResponse:
    if classroom is None:
        classroom = await session.get(Classroom, student_update.classroom_id)
    rows = (
        await session.execute(
            select(StudentUpdateRecipient, Student)
            .join(Student, Student.id == StudentUpdateRecipient.student_id)
            .where(StudentUpdateRecipient.student_update_id == student_update.id)
            .order_by(Student.last_name, Student.first_name, Student.id)
        )
    ).all()
    recipients = [
        build_recipient_response(recipient, student, student_update.due_at)
        for recipient, student in rows
    ]
    return StudentUpdateResponse(
        id=student_update.id,
        organization_id=student_update.organization_id,
        classroom_id=student_update.classroom_id,
        classroom_name=classroom.name,
        teacher_workos_user_id=student_update.teacher_workos_user_id,
        target_type=student_update.target_type,
        title=student_update.title,
        body=student_update.body,
        due_at=student_update.due_at,
        requires_acknowledgement=student_update.requires_acknowledgement,
        allows_replies=student_update.allows_replies,
        recipient_count=len(recipients),
        recipients=recipients,
        created_at=student_update.created_at,
        updated_at=student_update.updated_at,
    )


async def list_teacher_updates(
    session: AsyncSession,
    current_user: dict,
    *,
    classroom_id: uuid.UUID | None,
    update_status: StudentUpdateStatus | None,
    overdue_only: bool,
    limit: int,
    offset: int,
) -> list[StudentUpdateResponse]:
    teacher_id, organization_id = _require_teacher_access(current_user)
    query = (
        select(StudentUpdate, Classroom)
        .join(Classroom, Classroom.id == StudentUpdate.classroom_id)
        .where(
            StudentUpdate.organization_id == organization_id,
            StudentUpdate.teacher_workos_user_id == teacher_id,
        )
    )
    if classroom_id is not None:
        query = query.where(StudentUpdate.classroom_id == classroom_id)
    if update_status is not None or overdue_only:
        query = query.join(
            StudentUpdateRecipient,
            StudentUpdateRecipient.student_update_id == StudentUpdate.id,
        ).distinct()
    if update_status is not None:
        query = query.where(StudentUpdateRecipient.status == update_status)
    if overdue_only:
        query = query.where(
            StudentUpdate.due_at.is_not(None),
            StudentUpdate.due_at < utcnow(),
            StudentUpdateRecipient.status != StudentUpdateStatus.COMPLETED,
        )
    rows = (
        await session.execute(
            query.order_by(StudentUpdate.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        await build_update_response(session, student_update, classroom)
        for student_update, classroom in rows
    ]


async def add_teacher_feedback(
    session: AsyncSession,
    update_id: uuid.UUID,
    recipient_id: uuid.UUID,
    content: str,
    current_user: dict,
) -> StudentUpdateEvent:
    teacher_id, organization_id = _require_teacher_access(current_user)
    async with session.begin():
        recipient, _, _ = await require_teacher_recipient(
            session, update_id, recipient_id, current_user, lock_recipient=True
        )
        event = _new_event(
            recipient.id,
            StudentUpdateEventType.TEACHER_FEEDBACK,
            teacher_id,
            StudentUpdateActorRole.TEACHER,
            content=content,
        )
        session.add(event)
        guardian_ids = (
            await _guardian_ids_by_student(session, [recipient.student_id])
        ).get(recipient.student_id, [])
        await _ensure_guardian_states(session, recipient.id, guardian_ids)
        _add_guardian_notifications(
            session,
            organization_id,
            recipient.id,
            event.id,
            guardian_ids,
            StudentUpdateNotificationType.TEACHER_FEEDBACK,
        )
    return event


ALLOWED_STATUS_TRANSITIONS = {
    StudentUpdateStatus.ASSIGNED: {
        StudentUpdateStatus.ACKNOWLEDGED,
        StudentUpdateStatus.COMPLETED,
    },
    StudentUpdateStatus.ACKNOWLEDGED: {StudentUpdateStatus.COMPLETED},
    StudentUpdateStatus.COMPLETED: set(),
}


async def change_teacher_recipient_status(
    session: AsyncSession,
    update_id: uuid.UUID,
    recipient_id: uuid.UUID,
    requested_status: StudentUpdateStatus,
    current_user: dict,
) -> tuple[StudentUpdateRecipient, StudentUpdate, Student]:
    teacher_id, organization_id = _require_teacher_access(current_user)
    async with session.begin():
        recipient, student_update, student = await require_teacher_recipient(
            session, update_id, recipient_id, current_user, lock_recipient=True
        )
        previous_status = recipient.status
        if requested_status == previous_status:
            return recipient, student_update, student
        if requested_status not in ALLOWED_STATUS_TRANSITIONS[previous_status]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot move status from {previous_status} to "
                    f"{requested_status}"
                ),
            )

        now = utcnow()
        recipient.status = requested_status
        if requested_status == StudentUpdateStatus.ACKNOWLEDGED:
            recipient.acknowledged_at = recipient.acknowledged_at or now
        if requested_status == StudentUpdateStatus.COMPLETED:
            recipient.completed_at = now
        event = _new_event(
            recipient.id,
            StudentUpdateEventType.STATUS_CHANGED,
            teacher_id,
            StudentUpdateActorRole.TEACHER,
            previous_status=previous_status,
            new_status=requested_status,
        )
        session.add(event)
        guardian_ids = (
            await _guardian_ids_by_student(session, [recipient.student_id])
        ).get(recipient.student_id, [])
        await _ensure_guardian_states(session, recipient.id, guardian_ids)
        _add_guardian_notifications(
            session,
            organization_id,
            recipient.id,
            event.id,
            guardian_ids,
            StudentUpdateNotificationType.STATUS_CHANGED,
        )
    return recipient, student_update, student


async def list_recipient_events(
    session: AsyncSession,
    recipient_id: uuid.UUID,
) -> list[StudentUpdateEventResponse]:
    events = list(
        (
            await session.scalars(
                select(StudentUpdateEvent)
                .where(StudentUpdateEvent.recipient_id == recipient_id)
                .order_by(StudentUpdateEvent.created_at, StudentUpdateEvent.id)
            )
        ).all()
    )
    return [StudentUpdateEventResponse.model_validate(event) for event in events]


def _guardian_author_label(
    actor_role: StudentUpdateActorRole,
    actor_id: str,
    guardian_id: str,
) -> str:
    if actor_role == StudentUpdateActorRole.GUARDIAN:
        return "You" if actor_id == guardian_id else "Guardian"
    if actor_role == StudentUpdateActorRole.TEACHER:
        return "Teacher"
    return "School"


def build_guardian_event_response(
    event: StudentUpdateEvent,
    guardian_id: str,
) -> GuardianUpdateEventResponse:
    return GuardianUpdateEventResponse(
        id=event.id,
        recipient_id=event.recipient_id,
        event_type=event.event_type,
        actor_role=event.actor_role,
        author_label=_guardian_author_label(
            event.actor_role,
            event.actor_workos_user_id,
            guardian_id,
        ),
        content=event.content,
        previous_status=event.previous_status,
        new_status=event.new_status,
        created_at=event.created_at,
    )


async def list_guardian_events(
    session: AsyncSession,
    recipient_id: uuid.UUID,
    guardian_id: str,
) -> list[GuardianUpdateEventResponse]:
    events = list(
        (
            await session.scalars(
                select(StudentUpdateEvent)
                .where(
                    StudentUpdateEvent.recipient_id == recipient_id,
                    StudentUpdateEvent.event_type != StudentUpdateEventType.REMINDER_SENT,
                )
                .order_by(StudentUpdateEvent.created_at, StudentUpdateEvent.id)
            )
        ).all()
    )
    return [build_guardian_event_response(event, guardian_id) for event in events]


# Guardian operations
async def require_guardian_recipient(
    session: AsyncSession,
    recipient_id: uuid.UUID,
    current_user: dict,
    *,
    lock_recipient: bool = False,
    expected_student_id: uuid.UUID | None = None,
) -> tuple[
    StudentUpdateRecipient,
    StudentUpdate,
    Student,
    Classroom,
    GuardianUpdateState | None,
]:
    guardian_id = current_user.get("user_id")
    organization_id = current_user.get("organization_id")
    query = (
        select(
            StudentUpdateRecipient,
            StudentUpdate,
            Student,
            Classroom,
            GuardianUpdateState,
        )
        .join(
            StudentUpdate,
            StudentUpdate.id == StudentUpdateRecipient.student_update_id,
        )
        .join(Student, Student.id == StudentUpdateRecipient.student_id)
        .join(Classroom, Classroom.id == StudentUpdate.classroom_id)
        .join(GuardianStudent, GuardianStudent.student_id == Student.id)
        .outerjoin(
            GuardianUpdateState,
            and_(
                GuardianUpdateState.recipient_id == StudentUpdateRecipient.id,
                GuardianUpdateState.guardian_workos_user_id == guardian_id,
            ),
        )
        .where(
            StudentUpdateRecipient.id == recipient_id,
            StudentUpdate.organization_id == organization_id,
            Student.organization_id == organization_id,
            GuardianStudent.guardian_workos_user_id == guardian_id,
        )
    )
    if expected_student_id is not None:
        query = query.where(Student.id == expected_student_id)
    if lock_recipient:
        query = query.with_for_update(of=StudentUpdateRecipient)
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student update not found",
        )
    return row


def build_guardian_feed_item(
    recipient: StudentUpdateRecipient,
    student_update: StudentUpdate,
    student: Student,
    classroom: Classroom,
    guardian_state: GuardianUpdateState | None,
) -> GuardianFeedItemResponse:
    return GuardianFeedItemResponse(
        recipient_id=recipient.id,
        update_id=student_update.id,
        student_id=student.id,
        student_first_name=student.first_name,
        student_last_name=student.last_name,
        classroom_id=classroom.id,
        classroom_name=classroom.name,
        target_type=student_update.target_type,
        author_label="Teacher",
        title=student_update.title,
        body=student_update.body,
        due_at=student_update.due_at,
        requires_acknowledgement=student_update.requires_acknowledgement,
        allows_replies=student_update.allows_replies,
        status=recipient.status,
        is_overdue=is_overdue(student_update.due_at, recipient.status),
        read_at=guardian_state.read_at if guardian_state else None,
        acknowledged_at=guardian_state.acknowledged_at if guardian_state else None,
        created_at=student_update.created_at,
        updated_at=max(student_update.updated_at, recipient.updated_at),
    )


async def list_guardian_feed(
    session: AsyncSession,
    current_user: dict,
    *,
    student_id: uuid.UUID | None,
    update_status: StudentUpdateStatus | None,
    unread_only: bool,
    overdue_only: bool,
    limit: int,
    offset: int,
) -> list[GuardianFeedItemResponse]:
    guardian_id = current_user.get("user_id")
    organization_id = current_user.get("organization_id")
    query = (
        select(
            StudentUpdateRecipient,
            StudentUpdate,
            Student,
            Classroom,
            GuardianUpdateState,
        )
        .join(
            StudentUpdate,
            StudentUpdate.id == StudentUpdateRecipient.student_update_id,
        )
        .join(Student, Student.id == StudentUpdateRecipient.student_id)
        .join(Classroom, Classroom.id == StudentUpdate.classroom_id)
        .join(GuardianStudent, GuardianStudent.student_id == Student.id)
        .outerjoin(
            GuardianUpdateState,
            and_(
                GuardianUpdateState.recipient_id == StudentUpdateRecipient.id,
                GuardianUpdateState.guardian_workos_user_id == guardian_id,
            ),
        )
        .where(
            StudentUpdate.organization_id == organization_id,
            Student.organization_id == organization_id,
            GuardianStudent.guardian_workos_user_id == guardian_id,
        )
    )
    if student_id is not None:
        query = query.where(Student.id == student_id)
    if update_status is not None:
        query = query.where(StudentUpdateRecipient.status == update_status)
    if unread_only:
        query = query.where(
            or_(
                GuardianUpdateState.id.is_(None),
                GuardianUpdateState.read_at.is_(None),
            )
        )
    if overdue_only:
        query = query.where(
            StudentUpdate.due_at.is_not(None),
            StudentUpdate.due_at < utcnow(),
            StudentUpdateRecipient.status != StudentUpdateStatus.COMPLETED,
        )
    rows = (
        await session.execute(
            query.order_by(StudentUpdate.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [build_guardian_feed_item(*row) for row in rows]


async def _get_or_create_guardian_state(
    session: AsyncSession,
    recipient_id: uuid.UUID,
    guardian_id: str,
    existing_state: GuardianUpdateState | None,
) -> GuardianUpdateState:
    if existing_state is not None:
        return existing_state
    state = GuardianUpdateState(
        recipient_id=recipient_id,
        guardian_workos_user_id=guardian_id,
    )
    session.add(state)
    return state


async def _mark_recipient_notifications_read(
    session: AsyncSession,
    recipient_id: uuid.UUID,
    guardian_id: str,
    now: datetime,
) -> None:
    await session.execute(
        sqlalchemy_update(StudentUpdateNotification)
        .where(
            StudentUpdateNotification.recipient_id == recipient_id,
            StudentUpdateNotification.guardian_workos_user_id == guardian_id,
            StudentUpdateNotification.read_at.is_(None),
        )
        .values(read_at=now, updated_at=now)
    )


async def mark_guardian_update_read(
    session: AsyncSession,
    recipient_id: uuid.UUID,
    current_user: dict,
) -> tuple[
    StudentUpdateRecipient,
    StudentUpdate,
    Student,
    Classroom,
    GuardianUpdateState,
]:
    guardian_id = current_user["user_id"]
    async with session.begin():
        recipient, student_update, student, classroom, existing_state = (
            await require_guardian_recipient(
                session, recipient_id, current_user, lock_recipient=True
            )
        )
        guardian_state = await _get_or_create_guardian_state(
            session, recipient.id, guardian_id, existing_state
        )
        now = utcnow()
        guardian_state.read_at = guardian_state.read_at or now
        await _mark_recipient_notifications_read(
            session, recipient.id, guardian_id, now
        )
    return recipient, student_update, student, classroom, guardian_state


async def acknowledge_guardian_update(
    session: AsyncSession,
    recipient_id: uuid.UUID,
    current_user: dict,
) -> tuple[
    StudentUpdateRecipient,
    StudentUpdate,
    Student,
    Classroom,
    GuardianUpdateState,
]:
    guardian_id = current_user["user_id"]
    async with session.begin():
        recipient, student_update, student, classroom, existing_state = (
            await require_guardian_recipient(
                session, recipient_id, current_user, lock_recipient=True
            )
        )
        if not student_update.requires_acknowledgement:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This update does not require acknowledgement",
            )
        guardian_state = await _get_or_create_guardian_state(
            session, recipient.id, guardian_id, existing_state
        )
        if guardian_state.acknowledged_at is not None:
            return recipient, student_update, student, classroom, guardian_state

        now = utcnow()
        guardian_state.read_at = guardian_state.read_at or now
        guardian_state.acknowledged_at = now
        previous_status = recipient.status
        new_status = previous_status
        if previous_status == StudentUpdateStatus.ASSIGNED:
            new_status = StudentUpdateStatus.ACKNOWLEDGED
            recipient.status = new_status
            recipient.acknowledged_at = recipient.acknowledged_at or now
        session.add(
            _new_event(
                recipient.id,
                StudentUpdateEventType.GUARDIAN_ACKNOWLEDGED,
                guardian_id,
                StudentUpdateActorRole.GUARDIAN,
                previous_status=previous_status,
                new_status=new_status,
            )
        )
        await _mark_recipient_notifications_read(
            session, recipient.id, guardian_id, now
        )
    return recipient, student_update, student, classroom, guardian_state


async def add_guardian_reply(
    session: AsyncSession,
    recipient_id: uuid.UUID,
    content: str,
    current_user: dict,
) -> StudentUpdateEvent:
    guardian_id = current_user["user_id"]
    async with session.begin():
        recipient, student_update, _, _, existing_state = await require_guardian_recipient(
            session, recipient_id, current_user, lock_recipient=True
        )
        if not student_update.allows_replies:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Replies are disabled for this update",
            )
        guardian_state = await _get_or_create_guardian_state(
            session, recipient.id, guardian_id, existing_state
        )
        now = utcnow()
        guardian_state.read_at = guardian_state.read_at or now
        event = _new_event(
            recipient.id,
            StudentUpdateEventType.GUARDIAN_REPLY,
            guardian_id,
            StudentUpdateActorRole.GUARDIAN,
            content=content,
        )
        session.add(event)
        await _mark_recipient_notifications_read(
            session, recipient.id, guardian_id, now
        )
    return event


def _notification_response(
    notification: StudentUpdateNotification,
    student_update: StudentUpdate,
    student: Student,
) -> StudentUpdateNotificationResponse:
    return StudentUpdateNotificationResponse(
        id=notification.id,
        recipient_id=notification.recipient_id,
        event_id=notification.event_id,
        notification_type=notification.notification_type,
        student_id=student.id,
        student_first_name=student.first_name,
        student_last_name=student.last_name,
        update_id=student_update.id,
        update_title=student_update.title,
        message=notification.message,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


async def _attach_notification_policy_sources(
    session: AsyncSession,
    notifications: list[StudentUpdateNotificationResponse],
    organization_id: str | None,
    guardian_id: str | None,
) -> None:
    reminders = [
        notification for notification in notifications
        if notification.notification_type == StudentUpdateNotificationType.ACKNOWLEDGEMENT_REMINDER
    ]
    sources = await get_guardian_reminder_sources(
        session, organization_id, guardian_id, {reminder.update_id for reminder in reminders}
    )
    for reminder in reminders:
        reminder.policy_sources = sources.get(reminder.update_id, [])


# Notification operations
async def list_guardian_notifications(
    session: AsyncSession,
    current_user: dict,
    *,
    unread_only: bool,
    limit: int,
    offset: int,
) -> list[StudentUpdateNotificationResponse]:
    guardian_id = current_user.get("user_id")
    organization_id = current_user.get("organization_id")
    query = (
        select(
            StudentUpdateNotification,
            StudentUpdateRecipient,
            StudentUpdate,
            Student,
        )
        .join(
            StudentUpdateRecipient,
            StudentUpdateRecipient.id == StudentUpdateNotification.recipient_id,
        )
        .join(
            StudentUpdate,
            StudentUpdate.id == StudentUpdateRecipient.student_update_id,
        )
        .join(Student, Student.id == StudentUpdateRecipient.student_id)
        .join(GuardianStudent, GuardianStudent.student_id == Student.id)
        .where(
            StudentUpdateNotification.organization_id == organization_id,
            StudentUpdateNotification.guardian_workos_user_id == guardian_id,
            StudentUpdate.organization_id == organization_id,
            Student.organization_id == organization_id,
            GuardianStudent.guardian_workos_user_id == guardian_id,
        )
    )
    if unread_only:
        query = query.where(StudentUpdateNotification.read_at.is_(None))
    rows = (
        await session.execute(
            query.order_by(StudentUpdateNotification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    notifications = [
        _notification_response(notification, student_update, student)
        for notification, _, student_update, student in rows
    ]
    await _attach_notification_policy_sources(session, notifications, organization_id, guardian_id)
    return notifications


async def mark_guardian_notification_read(
    session: AsyncSession,
    notification_id: uuid.UUID,
    current_user: dict,
) -> StudentUpdateNotificationResponse:
    guardian_id = current_user.get("user_id")
    organization_id = current_user.get("organization_id")
    async with session.begin():
        row = (
            await session.execute(
                select(
                    StudentUpdateNotification,
                    StudentUpdateRecipient,
                    StudentUpdate,
                    Student,
                )
                .join(
                    StudentUpdateRecipient,
                    StudentUpdateRecipient.id
                    == StudentUpdateNotification.recipient_id,
                )
                .join(
                    StudentUpdate,
                    StudentUpdate.id == StudentUpdateRecipient.student_update_id,
                )
                .join(Student, Student.id == StudentUpdateRecipient.student_id)
                .join(GuardianStudent, GuardianStudent.student_id == Student.id)
                .where(
                    StudentUpdateNotification.id == notification_id,
                    StudentUpdateNotification.organization_id == organization_id,
                    StudentUpdateNotification.guardian_workos_user_id == guardian_id,
                    StudentUpdate.organization_id == organization_id,
                    Student.organization_id == organization_id,
                    GuardianStudent.guardian_workos_user_id == guardian_id,
                )
                .with_for_update(of=StudentUpdateNotification)
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )
        notification, _, student_update, student = row
        notification.read_at = notification.read_at or utcnow()
        response = _notification_response(notification, student_update, student)
        await _attach_notification_policy_sources(session, [response], organization_id, guardian_id)
    return response


# Administration operations
def _admin_item_response(
    recipient: StudentUpdateRecipient,
    student_update: StudentUpdate,
    student: Student,
    classroom: Classroom,
) -> AdminStudentUpdateItemResponse:
    return AdminStudentUpdateItemResponse(
        recipient_id=recipient.id,
        update_id=student_update.id,
        classroom_id=classroom.id,
        classroom_name=classroom.name,
        student_id=student.id,
        student_first_name=student.first_name,
        student_last_name=student.last_name,
        teacher_workos_user_id=student_update.teacher_workos_user_id,
        title=student_update.title,
        due_at=student_update.due_at,
        requires_acknowledgement=student_update.requires_acknowledgement,
        status=recipient.status,
        is_overdue=is_overdue(student_update.due_at, recipient.status),
        created_at=student_update.created_at,
        updated_at=max(student_update.updated_at, recipient.updated_at),
    )


async def list_admin_student_updates(
    session: AsyncSession,
    organization_id: str,
    *,
    classroom_id: uuid.UUID | None,
    teacher_id: str | None,
    student_id: uuid.UUID | None,
    update_status: StudentUpdateStatus | None,
    overdue_only: bool,
    limit: int,
    offset: int,
) -> list[AdminStudentUpdateItemResponse]:
    query = (
        select(StudentUpdateRecipient, StudentUpdate, Student, Classroom)
        .join(
            StudentUpdate,
            StudentUpdate.id == StudentUpdateRecipient.student_update_id,
        )
        .join(Student, Student.id == StudentUpdateRecipient.student_id)
        .join(Classroom, Classroom.id == StudentUpdate.classroom_id)
        .where(StudentUpdate.organization_id == organization_id)
    )
    if classroom_id is not None:
        query = query.where(StudentUpdate.classroom_id == classroom_id)
    if teacher_id is not None:
        query = query.where(StudentUpdate.teacher_workos_user_id == teacher_id)
    if student_id is not None:
        query = query.where(StudentUpdateRecipient.student_id == student_id)
    if update_status is not None:
        query = query.where(StudentUpdateRecipient.status == update_status)
    if overdue_only:
        query = query.where(
            StudentUpdate.due_at.is_not(None),
            StudentUpdate.due_at < utcnow(),
            StudentUpdateRecipient.status != StudentUpdateStatus.COMPLETED,
        )
    rows = (
        await session.execute(
            query.order_by(StudentUpdate.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [_admin_item_response(*row) for row in rows]


async def get_admin_summary(
    session: AsyncSession,
    organization_id: str,
) -> dict:
    status_rows = (
        await session.execute(
            select(StudentUpdateRecipient.status, func.count(StudentUpdateRecipient.id))
            .join(
                StudentUpdate,
                StudentUpdate.id == StudentUpdateRecipient.student_update_id,
            )
            .where(StudentUpdate.organization_id == organization_id)
            .group_by(StudentUpdateRecipient.status)
        )
    ).all()
    counts = dict(status_rows)
    overdue = await session.scalar(
        select(func.count(StudentUpdateRecipient.id))
        .join(
            StudentUpdate,
            StudentUpdate.id == StudentUpdateRecipient.student_update_id,
        )
        .where(
            StudentUpdate.organization_id == organization_id,
            StudentUpdate.due_at.is_not(None),
            StudentUpdate.due_at < utcnow(),
            StudentUpdateRecipient.status != StudentUpdateStatus.COMPLETED,
        )
    )
    unread = await session.scalar(
        select(func.count(StudentUpdateNotification.id)).where(
            StudentUpdateNotification.organization_id == organization_id,
            StudentUpdateNotification.read_at.is_(None),
        )
    )
    return {
        "assigned": counts.get(StudentUpdateStatus.ASSIGNED, 0),
        "acknowledged": counts.get(StudentUpdateStatus.ACKNOWLEDGED, 0),
        "completed": counts.get(StudentUpdateStatus.COMPLETED, 0),
        "overdue": overdue or 0,
        "unread_notifications": unread or 0,
    }


async def get_admin_update(
    session: AsyncSession,
    update_id: uuid.UUID,
    organization_id: str,
) -> tuple[StudentUpdate, Classroom]:
    row = (
        await session.execute(
            select(StudentUpdate, Classroom)
            .join(Classroom, Classroom.id == StudentUpdate.classroom_id)
            .where(
                StudentUpdate.id == update_id,
                StudentUpdate.organization_id == organization_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student update not found",
        )
    return row


async def require_admin_recipient(
    session: AsyncSession,
    recipient_id: uuid.UUID,
    organization_id: str,
) -> StudentUpdateRecipient:
    recipient = await session.scalar(
        select(StudentUpdateRecipient)
        .join(
            StudentUpdate,
            StudentUpdate.id == StudentUpdateRecipient.student_update_id,
        )
        .where(
            StudentUpdateRecipient.id == recipient_id,
            StudentUpdate.organization_id == organization_id,
        )
    )
    if recipient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student update recipient not found",
        )
    return recipient
