"""add student updates and guardian feed

Revision ID: b7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-08-27 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings


revision: str = "b7d8e9f0a1b2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME

target_type_enum = postgresql.ENUM(
    "classroom",
    "students",
    name="student_update_target_type_enum",
    schema=schema,
    create_type=False,
)
update_status_enum = postgresql.ENUM(
    "assigned",
    "acknowledged",
    "completed",
    name="student_update_status_enum",
    schema=schema,
    create_type=False,
)
event_type_enum = postgresql.ENUM(
    "assigned",
    "teacher_feedback",
    "guardian_reply",
    "guardian_acknowledged",
    "status_changed",
    name="student_update_event_type_enum",
    schema=schema,
    create_type=False,
)
actor_role_enum = postgresql.ENUM(
    "teacher",
    "guardian",
    "admin",
    "system",
    name="student_update_actor_role_enum",
    schema=schema,
    create_type=False,
)
notification_type_enum = postgresql.ENUM(
    "update_assigned",
    "teacher_feedback",
    "status_changed",
    name="notification_type_enum",
    schema=schema,
    create_type=False,
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    connection = op.get_bind()
    for enum in (
        target_type_enum,
        update_status_enum,
        event_type_enum,
        actor_role_enum,
        notification_type_enum,
    ):
        enum.create(connection, checkfirst=True)

    op.create_table(
        "studentupdate",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.String(length=255), nullable=False),
        sa.Column("classroom_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "teacher_workos_user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("target_type", target_type_enum, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["classroom_id"],
            [f"{schema}.classroom.id"],
            name="fk_studentupdate_classroom_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_studentupdate"),
        schema=schema,
    )
    for column in (
        "organization_id",
        "classroom_id",
        "teacher_workos_user_id",
        "due_at",
    ):
        op.create_index(
            f"ix_studentupdate_{column}",
            "studentupdate",
            [column],
            schema=schema,
        )

    op.create_table(
        "studentupdaterecipient",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "student_update_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "class_enrollment_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "status",
            update_status_enum,
            server_default="assigned",
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["student_update_id"],
            [f"{schema}.studentupdate.id"],
            name="fk_studentupdaterecipient_student_update_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            [f"{schema}.student.id"],
            name="fk_studentupdaterecipient_student_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["class_enrollment_id"],
            [f"{schema}.classenrollment.id"],
            name="fk_studentupdaterecipient_class_enrollment_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_studentupdaterecipient"),
        sa.UniqueConstraint(
            "student_update_id",
            "student_id",
            name="uq_studentupdaterecipient_update_student",
        ),
        schema=schema,
    )
    for column in (
        "student_update_id",
        "student_id",
        "class_enrollment_id",
        "status",
    ):
        op.create_index(
            f"ix_studentupdaterecipient_{column}",
            "studentupdaterecipient",
            [column],
            schema=schema,
        )

    op.create_table(
        "studentupdateevent",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", event_type_enum, nullable=False),
        sa.Column(
            "actor_workos_user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("actor_role", actor_role_enum, nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("previous_status", update_status_enum, nullable=True),
        sa.Column("new_status", update_status_enum, nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            [f"{schema}.studentupdaterecipient.id"],
            name="fk_studentupdateevent_recipient_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_studentupdateevent"),
        schema=schema,
    )
    op.create_index(
        "ix_studentupdateevent_recipient_id",
        "studentupdateevent",
        ["recipient_id"],
        schema=schema,
    )
    op.create_index(
        "ix_studentupdateevent_event_type",
        "studentupdateevent",
        ["event_type"],
        schema=schema,
    )

    op.create_table(
        "guardianupdatestate",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "guardian_workos_user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            [f"{schema}.studentupdaterecipient.id"],
            name="fk_guardianupdatestate_recipient_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_guardianupdatestate"),
        sa.UniqueConstraint(
            "recipient_id",
            "guardian_workos_user_id",
            name="uq_guardianupdatestate_recipient_guardian",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_guardianupdatestate_recipient_id",
        "guardianupdatestate",
        ["recipient_id"],
        schema=schema,
    )
    op.create_index(
        "ix_guardianupdatestate_guardian_workos_user_id",
        "guardianupdatestate",
        ["guardian_workos_user_id"],
        schema=schema,
    )

    op.create_table(
        "notification",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.String(length=255), nullable=False),
        sa.Column(
            "guardian_workos_user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", notification_type_enum, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            [f"{schema}.studentupdaterecipient.id"],
            name="fk_notification_recipient_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            [f"{schema}.studentupdateevent.id"],
            name="fk_notification_event_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification"),
        sa.UniqueConstraint(
            "event_id",
            "guardian_workos_user_id",
            name="uq_notification_event_guardian",
        ),
        schema=schema,
    )
    for column in (
        "organization_id",
        "guardian_workos_user_id",
        "recipient_id",
        "event_id",
        "read_at",
    ):
        op.create_index(
            f"ix_notification_{column}",
            "notification",
            [column],
            schema=schema,
        )
    op.create_index(
        "ix_notification_guardian_read_at",
        "notification",
        ["guardian_workos_user_id", "read_at"],
        schema=schema,
    )


def downgrade() -> None:
    op.drop_table("notification", schema=schema)
    op.drop_table("guardianupdatestate", schema=schema)
    op.drop_table("studentupdateevent", schema=schema)
    op.drop_table("studentupdaterecipient", schema=schema)
    op.drop_table("studentupdate", schema=schema)
    for enum in (
        notification_type_enum,
        actor_role_enum,
        event_type_enum,
        update_status_enum,
        target_type_enum,
    ):
        enum.drop(op.get_bind(), checkfirst=True)
