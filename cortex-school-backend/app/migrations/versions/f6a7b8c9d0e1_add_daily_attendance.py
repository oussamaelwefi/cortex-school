"""add daily attendance

Revision ID: f6a7b8c9d0e1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME
attendance_status_enum = postgresql.ENUM(
    "present",
    "absent",
    "late",
    "excused",
    name="attendance_status_enum",
    schema=schema,
    create_type=False,
)


def upgrade() -> None:
    connection = op.get_bind()
    attendance_status_enum.create(connection, checkfirst=True)

    op.create_table(
        "attendancesubmission",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classroom_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_date", sa.Date(), nullable=False),
        sa.Column(
            "submitted_by_workos_user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_by_workos_user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["classroom_id"],
            [f"{schema}.classroom.id"],
            name="fk_attendancesubmission_classroom_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attendancesubmission"),
        sa.UniqueConstraint(
            "classroom_id",
            "school_date",
            name="uq_attendancesubmission_classroom_date",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_attendancesubmission_classroom_id",
        "attendancesubmission",
        ["classroom_id"],
        schema=schema,
    )
    op.create_index(
        "ix_attendancesubmission_school_date",
        "attendancesubmission",
        ["school_date"],
        schema=schema,
    )

    op.create_table(
        "attendancerecord",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "class_enrollment_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("school_date", sa.Date(), nullable=False),
        sa.Column("status", attendance_status_enum, nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column(
            "updated_by_workos_user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            [f"{schema}.attendancesubmission.id"],
            name="fk_attendancerecord_submission_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["class_enrollment_id"],
            [f"{schema}.classenrollment.id"],
            name="fk_attendancerecord_class_enrollment_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attendancerecord"),
        sa.UniqueConstraint(
            "class_enrollment_id",
            "school_date",
            name="uq_attendancerecord_placement_date",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_attendancerecord_submission_id",
        "attendancerecord",
        ["submission_id"],
        schema=schema,
    )
    op.create_index(
        "ix_attendancerecord_class_enrollment_id",
        "attendancerecord",
        ["class_enrollment_id"],
        schema=schema,
    )
    op.create_index(
        "ix_attendancerecord_school_date",
        "attendancerecord",
        ["school_date"],
        schema=schema,
    )


def downgrade() -> None:
    op.drop_table("attendancerecord", schema=schema)
    op.drop_table("attendancesubmission", schema=schema)
    attendance_status_enum.drop(op.get_bind(), checkfirst=True)
