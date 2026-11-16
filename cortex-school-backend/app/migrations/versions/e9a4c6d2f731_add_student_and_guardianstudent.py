"""add student and guardianstudent

Revision ID: e9a4c6d2f731
Revises: c7e4b2a19d63
Create Date: 2026-07-24 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

# revision identifiers, used by Alembic.
revision: str = "e9a4c6d2f731"
down_revision: Union[str, None] = "c7e4b2a19d63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def upgrade() -> None:
    op.create_table(
        "student",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.String(length=255), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_student"),
        schema=schema,
    )
    op.create_index(
        "ix_student_organization_id",
        "student",
        ["organization_id"],
        unique=False,
        schema=schema,
    )

    op.create_table(
        "guardianstudent",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "guardian_workos_user_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("relationship", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["student_id"],
            [f"{schema}.student.id"],
            name="fk_guardianstudent_student_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_guardianstudent"),
        sa.UniqueConstraint(
            "student_id",
            "guardian_workos_user_id",
            name="uq_guardianstudent_student_guardian",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_guardianstudent_student_id",
        "guardianstudent",
        ["student_id"],
        unique=False,
        schema=schema,
    )
    op.create_index(
        "ix_guardianstudent_guardian_workos_user_id",
        "guardianstudent",
        ["guardian_workos_user_id"],
        unique=False,
        schema=schema,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_guardianstudent_guardian_workos_user_id",
        table_name="guardianstudent",
        schema=schema,
    )
    op.drop_index(
        "ix_guardianstudent_student_id",
        table_name="guardianstudent",
        schema=schema,
    )
    op.drop_table("guardianstudent", schema=schema)
    op.drop_index(
        "ix_student_organization_id",
        table_name="student",
        schema=schema,
    )
    op.drop_table("student", schema=schema)
