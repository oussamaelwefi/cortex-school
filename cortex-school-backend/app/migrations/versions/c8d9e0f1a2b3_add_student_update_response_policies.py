"""add acknowledgement and reply policies to student updates

Revision ID: c8d9e0f1a2b3
Revises: b7d8e9f0a1b2
Create Date: 2026-09-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from core.config import settings


revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def upgrade() -> None:
    op.add_column(
        "studentupdate",
        sa.Column(
            "requires_acknowledgement",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        schema=schema,
    )
    op.add_column(
        "studentupdate",
        sa.Column(
            "allows_replies",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        schema=schema,
    )


def downgrade() -> None:
    op.drop_column("studentupdate", "allows_replies", schema=schema)
    op.drop_column(
        "studentupdate",
        "requires_acknowledgement",
        schema=schema,
    )
