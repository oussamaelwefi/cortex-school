"""add student registration requests

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME
registration_status_enum = postgresql.ENUM(
    "pending",
    "approved",
    "rejected",
    "withdrawn",
    name="student_registration_status_enum",
    schema=schema,
    create_type=False,
)


def upgrade() -> None:
    registration_status_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "studentregistrationrequest",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guardian_workos_user_id", sa.String(length=255), nullable=False),
        sa.Column("organization_id", sa.String(length=255), nullable=False),
        sa.Column("child_first_name", sa.String(length=255), nullable=False),
        sa.Column("child_last_name", sa.String(length=255), nullable=False),
        sa.Column(
            "academic_year_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("status", registration_status_enum, nullable=False),
        sa.Column(
            "resolved_student_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["academic_year_id"],
            [f"{schema}.academicyear.id"],
            name="fk_studentregistrationrequest_academic_year_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_student_id"],
            [f"{schema}.student.id"],
            name="fk_studentregistrationrequest_resolved_student_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_studentregistrationrequest"),
        schema=schema,
    )
    op.create_index(
        "ix_studentregistrationrequest_guardian_workos_user_id",
        "studentregistrationrequest",
        ["guardian_workos_user_id"],
        schema=schema,
    )
    op.create_index(
        "ix_studentregistrationrequest_organization_id",
        "studentregistrationrequest",
        ["organization_id"],
        schema=schema,
    )
    op.create_index(
        "ix_studentregistrationrequest_academic_year_id",
        "studentregistrationrequest",
        ["academic_year_id"],
        schema=schema,
    )
    op.create_index(
        "ix_studentregistrationrequest_status",
        "studentregistrationrequest",
        ["status"],
        schema=schema,
    )
    op.create_index(
        "ix_studentregistrationrequest_resolved_student_id",
        "studentregistrationrequest",
        ["resolved_student_id"],
        schema=schema,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_studentregistrationrequest_resolved_student_id",
        table_name="studentregistrationrequest",
        schema=schema,
    )
    op.drop_index(
        "ix_studentregistrationrequest_status",
        table_name="studentregistrationrequest",
        schema=schema,
    )
    op.drop_index(
        "ix_studentregistrationrequest_academic_year_id",
        table_name="studentregistrationrequest",
        schema=schema,
    )
    op.drop_index(
        "ix_studentregistrationrequest_organization_id",
        table_name="studentregistrationrequest",
        schema=schema,
    )
    op.drop_index(
        "ix_studentregistrationrequest_guardian_workos_user_id",
        table_name="studentregistrationrequest",
        schema=schema,
    )
    op.drop_table("studentregistrationrequest", schema=schema)
    registration_status_enum.drop(op.get_bind(), checkfirst=True)
