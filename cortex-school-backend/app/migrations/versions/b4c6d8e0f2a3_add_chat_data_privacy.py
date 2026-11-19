"""Add school chat-data control and school-scoped guardian opt-outs."""

import sqlalchemy as sa
from alembic import op
from core.config import settings

revision = "b4c6d8e0f2a3"
down_revision = "a3b5c7d9e1f2"
branch_labels = None
depends_on = None
schema = settings.database.SCHEMA_NAME


def upgrade():
    op.add_column(
        "school",
        sa.Column(
            "ai_chat_data_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        schema=schema,
    )
    op.add_column(
        "school",
        sa.Column(
            "ai_chat_data_revision", sa.Integer(), nullable=False, server_default="0"
        ),
        schema=schema,
    )
    op.create_table(
        "guardianchatpreference",
        sa.Column(
            "organization_id",
            sa.String(255),
            sa.ForeignKey(f"{schema}.school.organization_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("guardian_user_id", sa.String(255), primary_key=True),
        sa.Column(
            "data_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=schema,
    )


def downgrade():
    op.drop_table("guardianchatpreference", schema=schema)
    op.drop_column("school", "ai_chat_data_revision", schema=schema)
    op.drop_column("school", "ai_chat_data_enabled", schema=schema)
