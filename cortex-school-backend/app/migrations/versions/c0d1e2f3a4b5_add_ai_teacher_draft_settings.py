"""add AI teacher draft settings

Revision ID: c0d1e2f3a4b5
Revises: b8c9d0e1f2a3
Create Date: 2026-09-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from core.config import settings


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def upgrade() -> None:
    op.add_column(
        "school",
        sa.Column(
            "ai_teacher_draft_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema=schema,
    )
    op.add_column(
        "school",
        sa.Column(
            "ai_teacher_draft_default_language",
            sa.String(length=16),
            nullable=False,
            server_default="auto",
        ),
        schema=schema,
    )
    op.create_check_constraint(
        "ck_school_ai_teacher_draft_language",
        "school",
        "ai_teacher_draft_default_language IN ('auto', 'en', 'fr', 'ar')",
        schema=schema,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_school_ai_teacher_draft_language",
        "school",
        schema=schema,
    )
    op.drop_column("school", "ai_teacher_draft_default_language", schema=schema)
    op.drop_column("school", "ai_teacher_draft_enabled", schema=schema)
