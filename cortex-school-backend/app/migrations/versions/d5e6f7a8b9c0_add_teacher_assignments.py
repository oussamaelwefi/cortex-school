"""add teacher assignments

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-16 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME
teacher_assignment_role_enum = postgresql.ENUM(
    "lead",
    "assistant",
    name="teacher_assignment_role_enum",
    schema=schema,
    create_type=False,
)


def upgrade() -> None:
    connection = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    teacher_assignment_role_enum.create(connection, checkfirst=True)

    op.create_table(
        "teacherassignment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classroom_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("teacher_workos_user_id", sa.String(length=255), nullable=False),
        sa.Column("role", teacher_assignment_role_enum, nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_teacherassignment_valid_dates",
        ),
        sa.ForeignKeyConstraint(
            ["classroom_id"],
            [f"{schema}.classroom.id"],
            name="fk_teacherassignment_classroom_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_teacherassignment"),
        schema=schema,
    )
    op.create_index(
        "ix_teacherassignment_classroom_id",
        "teacherassignment",
        ["classroom_id"],
        schema=schema,
    )
    op.create_index(
        "ix_teacherassignment_teacher_workos_user_id",
        "teacherassignment",
        ["teacher_workos_user_id"],
        schema=schema,
    )
    op.execute(
        f"""
        ALTER TABLE "{schema}"."teacherassignment"
        ADD CONSTRAINT "ex_teacherassignment_no_overlap"
        EXCLUDE USING gist (
            classroom_id WITH =,
            teacher_workos_user_id WITH =,
            daterange(effective_from, effective_until, '[)') WITH &&
        )
        """
    )


def downgrade() -> None:
    op.drop_table("teacherassignment", schema=schema)
    teacher_assignment_role_enum.drop(op.get_bind(), checkfirst=True)
