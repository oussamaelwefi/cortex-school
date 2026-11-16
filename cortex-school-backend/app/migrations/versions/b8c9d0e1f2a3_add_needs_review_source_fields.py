"""add source fields for admin needs review

Revision ID: b8c9d0e1f2a3
Revises: c8d9e0f1a2b3
Create Date: 2026-09-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from core.config import settings

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def upgrade() -> None:
    op.add_column(
        "school",
        sa.Column(
            "attendance_cutoff_time",
            sa.Time(),
            server_default="10:00:00",
            nullable=False,
        ),
        schema=schema,
    )
    op.alter_column(
        "studentupdate",
        "requires_acknowledgement",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("false"),
        schema=schema,
    )
    op.add_column(
        "invitation",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.execute(
        sa.text(
            f"UPDATE {schema}.invitation "
            "SET expires_at = sent_at + (expires_in_days * INTERVAL '1 day') "
            "WHERE sent_at IS NOT NULL"
        )
    )
    op.create_index(
        "ix_studentupdate_org_ack_due",
        "studentupdate",
        ["organization_id", "requires_acknowledgement", "due_at"],
        schema=schema,
    )
    op.create_index(
        "ix_invitation_org_status_state_expiry",
        "invitation",
        ["organization_id", "send_status", "workos_state", "expires_at"],
        schema=schema,
    )


def downgrade() -> None:
    op.drop_index("ix_invitation_org_status_state_expiry", table_name="invitation", schema=schema)
    op.drop_index("ix_studentupdate_org_ack_due", table_name="studentupdate", schema=schema)
    op.drop_column("invitation", "expires_at", schema=schema)
    op.alter_column(
        "studentupdate",
        "requires_acknowledgement",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("true"),
        schema=schema,
    )
    op.drop_column("school", "attendance_cutoff_time", schema=schema)
