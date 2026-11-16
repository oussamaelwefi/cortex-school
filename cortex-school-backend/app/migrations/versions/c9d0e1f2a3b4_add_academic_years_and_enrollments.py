"""add academic years and enrollments

Revision ID: c9d0e1f2a3b4
Revises: a7b8c9d0e1f2
Create Date: 2026-07-29 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def upgrade() -> None:
    op.create_table(
        "academicyear",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_academicyear"),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_academicyear_organization_name",
        ),
        schema=schema,
    )

    op.create_table(
        "enrollment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("academic_year_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "payment_status IN ('unpaid', 'partial', 'full')",
            name="ck_enrollment_payment_status",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id"],
            [f"{schema}.academicyear.id"],
            name="fk_enrollment_academic_year_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            [f"{schema}.student.id"],
            name="fk_enrollment_student_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_enrollment"),
        sa.UniqueConstraint(
            "student_id",
            "academic_year_id",
            name="uq_enrollment_student_academic_year",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_enrollment_student_id", "enrollment", ["student_id"], schema=schema
    )
    op.create_index(
        "ix_enrollment_academic_year_id",
        "enrollment",
        ["academic_year_id"],
        schema=schema,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_enrollment_academic_year_id",
        table_name="enrollment",
        schema=schema,
    )
    op.drop_index(
        "ix_enrollment_student_id", table_name="enrollment", schema=schema
    )
    op.drop_table("enrollment", schema=schema)
    op.drop_table("academicyear", schema=schema)
