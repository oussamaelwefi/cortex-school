"""Store private school chat conversations and their messages."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision = "08b5d2a9c4e1"
down_revision = "e7a4c63f9b20"
branch_labels = None
depends_on = None
schema = settings.database.SCHEMA_NAME


def upgrade():
    op.create_table(
        "chatconversation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.String(255),
                  sa.ForeignKey(f"{schema}.school.organization_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("initial_request_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("next_turn", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'teacher', 'guardian')", name="ck_chatconversation_role"),
        sa.UniqueConstraint("organization_id", "user_id", "role", "initial_request_id",
                            name="uq_chatconversation_initial_request"),
        schema=schema,
    )
    op.create_index(
        "ix_chatconversation_owner_activity", "chatconversation",
        ["organization_id", "user_id", "role", "updated_at", "id"], schema=schema,
    )
    op.create_table(
        "chatmessage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(),
                  sa.ForeignKey(f"{schema}.chatconversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("sender", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False),
        sa.Column("school_data_revision", sa.Integer(), nullable=True),
        sa.Column("lookups", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sender IN ('user', 'assistant')", name="ck_chatmessage_sender"),
        sa.UniqueConstraint("conversation_id", "turn", "sender", name="uq_chatmessage_turn_sender"),
        sa.UniqueConstraint("conversation_id", "request_id", "sender", name="uq_chatmessage_request_sender"),
        schema=schema,
    )


def downgrade():
    op.drop_table("chatmessage", schema=schema)
    op.drop_table("chatconversation", schema=schema)
