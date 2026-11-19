"""Build a historical student update that participates in acknowledgement reminders."""

import uuid

from sqlalchemy import or_, select

from core.db import utcnow
from modules.classrooms.models import TeacherAssignment
from modules.reminders.services import pending_guardians
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
from modules.student_updates.services import _get_active_roster


async def prepare_acknowledgement(
    session, organization_id, classroom, school_date, members, audience, teacher_id=None
):
    active_teachers = {item["id"] for item in members if "teacher" in item["roles"]}
    assignments = (
        await session.scalars(
            select(TeacherAssignment).where(
                TeacherAssignment.classroom_id == classroom.id,
                TeacherAssignment.effective_from <= school_date,
                or_(
                    TeacherAssignment.effective_until.is_(None),
                    TeacherAssignment.effective_until > school_date,
                ),
            )
        )
    ).all()
    candidates = sorted(
        (
            item
            for item in assignments
            if item.teacher_workos_user_id in active_teachers
        ),
        key=lambda item: (item.role != "lead", item.teacher_workos_user_id),
    )
    if teacher_id is None:
        if not candidates:
            raise ValueError(
                "Aucun enseignant actif n’est affecté à cette classe. Affectez un enseignant avant l’import avec accusé de réception."
            )
        teacher_id = candidates[0].teacher_workos_user_id
    if not any(item.teacher_workos_user_id == teacher_id for item in candidates):
        raise ValueError(
            "L’enseignant choisi doit être actif et actuellement affecté à cette classe."
        )
    roster = await _get_active_roster(session, classroom, organization_id, school_date)
    students = [
        {
            "student_id": student.id,
            "placement_id": placement.id,
            "guardian_ids": sorted(
                {
                    item["id"]
                    for item in audience
                    if "guardian" in item["roles"]
                    and str(student.id) in item["student_ids"]
                }
            ),
        }
        for student, placement in roster
    ]
    if not students or not any(item["guardian_ids"] for item in students):
        raise ValueError(
            "Aucun élève avec un responsable familial actif n’est présent dans cette classe."
        )
    return {"teacher_id": teacher_id, "students": students}


async def write_acknowledgement(
    session,
    *,
    update_id,
    organization_id,
    classroom_id,
    author_id,
    title,
    body,
    published_at,
    due_at,
    snapshot,
):
    existing = await session.get(StudentUpdate, update_id)
    if existing is not None:
        if (
            existing.organization_id != organization_id
            or str(existing.classroom_id) != str(classroom_id)
            or existing.title != title
            or existing.body != body
            or existing.due_at != due_at
            or not existing.requires_acknowledgement
        ):
            raise ValueError(
                "L’identifiant d’import est déjà utilisé par un autre suivi."
            )
        return {
            "status": "already_imported",
            "teacher_user_id": existing.teacher_workos_user_id,
            "pending_guardian_count": len(
                await pending_guardians(session, organization_id, update_id)
            ),
        }

    now = utcnow()
    session.add(
        StudentUpdate(
            id=update_id,
            organization_id=organization_id,
            classroom_id=uuid.UUID(str(classroom_id)),
            teacher_workos_user_id=snapshot["teacher_id"],
            target_type=StudentUpdateTargetType.CLASSROOM,
            title=title,
            body=body,
            due_at=due_at,
            requires_acknowledgement=True,
            allows_replies=True,
            created_at=published_at,
            updated_at=now,
        )
    )
    await session.flush()
    recipients = []
    for student in snapshot["students"]:
        recipient = StudentUpdateRecipient(
            id=uuid.uuid4(),
            student_update_id=update_id,
            student_id=student["student_id"],
            class_enrollment_id=student["placement_id"],
            status=StudentUpdateStatus.ASSIGNED,
            created_at=published_at,
            updated_at=now,
        )
        session.add(recipient)
        recipients.append((recipient, student["guardian_ids"]))
    await session.flush()
    events = []
    for recipient, guardians in recipients:
        event = StudentUpdateEvent(
            id=uuid.uuid4(),
            recipient_id=recipient.id,
            event_type=StudentUpdateEventType.ASSIGNED,
            actor_workos_user_id=author_id,
            actor_role=StudentUpdateActorRole.ADMIN,
            new_status=StudentUpdateStatus.ASSIGNED,
            created_at=published_at,
            updated_at=now,
        )
        session.add(event)
        events.append((event, recipient, guardians))
    await session.flush()
    for event, recipient, guardians in events:
        for guardian_id in guardians:
            session.add(
                GuardianUpdateState(
                    recipient_id=recipient.id,
                    guardian_workos_user_id=guardian_id,
                    created_at=published_at,
                    updated_at=now,
                )
            )
            session.add(
                StudentUpdateNotification(
                    organization_id=organization_id,
                    guardian_workos_user_id=guardian_id,
                    recipient_id=recipient.id,
                    event_id=event.id,
                    notification_type=StudentUpdateNotificationType.UPDATE_ASSIGNED,
                    created_at=published_at,
                    updated_at=now,
                )
            )
    await session.flush()
    return {
        "status": "imported",
        "pending_guardian_count": len(
            await pending_guardians(session, organization_id, update_id)
        ),
    }
