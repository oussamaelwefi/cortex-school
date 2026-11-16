"""add invitation

Revision ID: a8c3f5d9e2b1
Revises:
Create Date: 2026-07-08 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

# revision identifiers, used by Alembic.
revision: str = "a8c3f5d9e2b1"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME
user_roles_enum = postgresql.ENUM(
    "admin",
    "teacher",
    "student",
    name="user_roles_enum",
    schema=schema,
    create_type=False,
)


def upgrade() -> None:
    user_roles_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "invitation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("role_slug", user_roles_enum, nullable=True),
        sa.Column("expires_in_days", sa.Integer(), nullable=False),
        sa.Column("send_status", sa.String(length=32), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("workos_invitation_id", sa.String(length=255), nullable=True),
        sa.Column("workos_state", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_invitation"),
        sa.UniqueConstraint("organization_id", "email", name="uq_invitation_email"),
        schema=schema,
    )


def downgrade() -> None:
    op.drop_table("invitation", schema=schema)
    user_roles_enum.drop(op.get_bind(), checkfirst=True)
