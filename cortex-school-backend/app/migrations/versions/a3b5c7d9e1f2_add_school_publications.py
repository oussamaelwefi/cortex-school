"""Add targeted school publications and durable per-account receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision = "a3b5c7d9e1f2"
down_revision = "f2e4d6c8b0a1"
branch_labels = None
depends_on = None
schema = settings.database.SCHEMA_NAME


def upgrade():
    op.create_table(
        "schoolpublication",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(255),
            sa.ForeignKey(f"{schema}.school.organization_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("author_user_id", sa.String(255), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("target_kind", sa.String(20), nullable=False),
        sa.Column("target_ids", postgresql.ARRAY(sa.String(255)), nullable=False),
        sa.Column("recipient_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "author_user_id",
            "idempotency_key",
            name="uq_publication_author_attempt",
        ),
        sa.CheckConstraint(
            "target_kind IN ('classrooms','guardians','teachers','students')",
            name="ck_publication_target_kind",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_publication_org_created",
        "schoolpublication",
        ["organization_id", "created_at"],
        schema=schema,
    )
    op.create_table(
        "publicationrecipient",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "publication_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.schoolpublication.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.String(16)), nullable=False),
        sa.Column("student_ids", postgresql.ARRAY(sa.String(36)), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "publication_id", "user_id", name="uq_publication_recipient_user"
        ),
        schema=schema,
    )
    op.create_index(
        "ix_publication_recipient_inbox",
        "publicationrecipient",
        ["user_id", "publication_id"],
        schema=schema,
    )


def downgrade():
    op.drop_table("publicationrecipient", schema=schema)
    op.drop_table("schoolpublication", schema=schema)
