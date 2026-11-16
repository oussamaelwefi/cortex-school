import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db import (
    Base,
    SCHEMA_NAME,
    TimestampMixin,
    create_sql_enum,
    uuid_pk,
)


class StudentUpdateTargetType(StrEnum):
    CLASSROOM = "classroom"
    STUDENTS = "students"


class StudentUpdateStatus(StrEnum):
    ASSIGNED = "assigned"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"


class StudentUpdateEventType(StrEnum):
    ASSIGNED = "assigned"
    TEACHER_FEEDBACK = "teacher_feedback"
    GUARDIAN_REPLY = "guardian_reply"
    GUARDIAN_ACKNOWLEDGED = "guardian_acknowledged"
    STATUS_CHANGED = "status_changed"
    REMINDER_SENT = "reminder_sent"


class StudentUpdateActorRole(StrEnum):
    TEACHER = "teacher"
    GUARDIAN = "guardian"
    ADMIN = "admin"
    SYSTEM = "system"


class StudentUpdateNotificationType(StrEnum):
    UPDATE_ASSIGNED = "update_assigned"
    TEACHER_FEEDBACK = "teacher_feedback"
    STATUS_CHANGED = "status_changed"
    ACKNOWLEDGEMENT_REMINDER = "acknowledgement_reminder"


class StudentUpdate(Base, TimestampMixin):
    __table_args__ = (
        Index(
            "ix_studentupdate_org_ack_due",
            "organization_id",
            "requires_acknowledgement",
            "due_at",
        ),
    )

    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    classroom_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.classroom.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    teacher_workos_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    target_type: Mapped[StudentUpdateTargetType] = mapped_column(
        create_sql_enum(StudentUpdateTargetType, "student_update_target_type_enum"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    requires_acknowledgement: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    allows_replies: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )


class StudentUpdateRecipient(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "student_update_id",
            "student_id",
            name="uq_studentupdaterecipient_update_student",
        ),
    )

    id: Mapped[uuid_pk]
    student_update_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.studentupdate.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.student.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    class_enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.classenrollment.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[StudentUpdateStatus] = mapped_column(
        create_sql_enum(StudentUpdateStatus, "student_update_status_enum"),
        default=StudentUpdateStatus.ASSIGNED,
        nullable=False,
        index=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StudentUpdateEvent(Base, TimestampMixin):
    id: Mapped[uuid_pk]
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            f"{SCHEMA_NAME}.studentupdaterecipient.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    event_type: Mapped[StudentUpdateEventType] = mapped_column(
        create_sql_enum(StudentUpdateEventType, "student_update_event_type_enum"),
        nullable=False,
        index=True,
    )
    actor_workos_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_role: Mapped[StudentUpdateActorRole] = mapped_column(
        create_sql_enum(StudentUpdateActorRole, "student_update_actor_role_enum"),
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_status: Mapped[StudentUpdateStatus | None] = mapped_column(
        create_sql_enum(StudentUpdateStatus, "student_update_status_enum"),
        nullable=True,
    )
    new_status: Mapped[StudentUpdateStatus | None] = mapped_column(
        create_sql_enum(StudentUpdateStatus, "student_update_status_enum"),
        nullable=True,
    )


class GuardianUpdateState(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "recipient_id",
            "guardian_workos_user_id",
            name="uq_guardianupdatestate_recipient_guardian",
        ),
    )

    id: Mapped[uuid_pk]
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            f"{SCHEMA_NAME}.studentupdaterecipient.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    guardian_workos_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StudentUpdateNotification(Base, TimestampMixin):
    __tablename__ = "notification"

    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "guardian_workos_user_id",
            name="uq_notification_event_guardian",
        ),
        Index(
            "ix_notification_guardian_read_at",
            "guardian_workos_user_id",
            "read_at",
        ),
    )

    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    guardian_workos_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            f"{SCHEMA_NAME}.studentupdaterecipient.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.studentupdateevent.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notification_type: Mapped[StudentUpdateNotificationType] = mapped_column(
        create_sql_enum(StudentUpdateNotificationType, "notification_type_enum"),
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
