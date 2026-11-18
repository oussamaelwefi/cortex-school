"""Add verified school requests and durable organization provisioning."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision = "f2e4d6c8b0a1"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None
schema = settings.database.SCHEMA_NAME


def upgrade():
    op.create_table(
        "schoolrequest",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requester_user_id", sa.String(255), nullable=False),
        sa.Column("requester_email", sa.String(255), nullable=False),
        sa.Column("requester_name", sa.String(255), nullable=False),
        sa.Column("school_name", sa.String(255), nullable=False),
        sa.Column("country_code", sa.String(2), sa.ForeignKey(f"{schema}.country.code", ondelete="RESTRICT"), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("organization_id", sa.String(255)),
        sa.Column("membership_id", sa.String(255)),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending','provisioning','failed','approved','rejected')", name="ck_schoolrequest_status"),
        sa.UniqueConstraint("organization_id", name="uq_schoolrequest_organization_id"),
        schema=schema,
    )
    op.create_index("ix_schoolrequest_requester_user_id", "schoolrequest", ["requester_user_id"], schema=schema)
    op.create_index("ix_schoolrequest_status_created", "schoolrequest", ["status", "created_at"], schema=schema)
    op.create_index("uq_schoolrequest_open_requester", "schoolrequest", ["requester_user_id"], unique=True,
                    postgresql_where=sa.text("status IN ('pending','provisioning','failed')"), schema=schema)


def downgrade():
    op.drop_table("schoolrequest", schema=schema)
