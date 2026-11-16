"""add student invitation conversion fields

Revision ID: f1a2b3c4d5e6
Revises: e9a4c6d2f731
Create Date: 2026-07-29 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e9a4c6d2f731"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def upgrade() -> None:
    op.add_column(
        "student",
        sa.Column(
            "conversion_status",
            sa.String(length=32),
            nullable=False,
            server_default="none",
        ),
        schema=schema,
    )
    op.alter_column(
        "student",
        "conversion_status",
        server_default=None,
        schema=schema,
    )
    op.add_column(
        "student",
        sa.Column("converted_to_role", sa.String(length=32), nullable=True),
        schema=schema,
    )
    op.add_column(
        "student",
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.add_column(
        "invitation",
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=schema,
    )
    op.create_index(
        "ix_invitation_student_id", "invitation", ["student_id"], schema=schema
    )
    op.create_foreign_key(
        "fk_invitation_student_id",
        "invitation",
        "student",
        ["student_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_invitation_student_id", "invitation", schema=schema)
    op.drop_index("ix_invitation_student_id", table_name="invitation", schema=schema)
    op.drop_column("invitation", "student_id", schema=schema)
    op.drop_column("student", "converted_at", schema=schema)
    op.drop_column("student", "converted_to_role", schema=schema)
    op.drop_column("student", "conversion_status", schema=schema)
