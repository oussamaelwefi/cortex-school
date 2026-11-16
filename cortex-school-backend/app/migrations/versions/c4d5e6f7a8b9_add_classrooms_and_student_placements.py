"""add classrooms and student placements

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "classroom",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "academic_year_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["academic_year_id"],
            [f"{schema}.academicyear.id"],
            name="fk_classroom_academic_year_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_classroom"),
        sa.UniqueConstraint(
            "academic_year_id",
            "name",
            name="uq_classroom_academic_year_name",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_classroom_academic_year_id",
        "classroom",
        ["academic_year_id"],
        schema=schema,
    )

    op.create_table(
        "classenrollment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classroom_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_classenrollment_valid_dates",
        ),
        sa.ForeignKeyConstraint(
            ["classroom_id"],
            [f"{schema}.classroom.id"],
            name="fk_classenrollment_classroom_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["enrollment_id"],
            [f"{schema}.enrollment.id"],
            name="fk_classenrollment_enrollment_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_classenrollment"),
        schema=schema,
    )
    op.create_index(
        "ix_classenrollment_classroom_id",
        "classenrollment",
        ["classroom_id"],
        schema=schema,
    )
    op.create_index(
        "ix_classenrollment_enrollment_id",
        "classenrollment",
        ["enrollment_id"],
        schema=schema,
    )
    op.execute(
        f"""
        ALTER TABLE "{schema}"."classenrollment"
        ADD CONSTRAINT "ex_classenrollment_no_overlap"
        EXCLUDE USING gist (
            enrollment_id WITH =,
            daterange(effective_from, effective_until, '[)') WITH &&
        )
        """
    )


def downgrade() -> None:
    op.drop_table("classenrollment", schema=schema)
    op.drop_index(
        "ix_classroom_academic_year_id",
        table_name="classroom",
        schema=schema,
    )
    op.drop_table("classroom", schema=schema)
