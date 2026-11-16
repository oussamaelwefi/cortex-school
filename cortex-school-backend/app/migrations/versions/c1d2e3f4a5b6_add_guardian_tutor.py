"""Add guardian study books and page-level searchable passages."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings


revision = "c1d2e3f4a5b6"
down_revision = "a4e7d2b9c1f0"
branch_labels = None
depends_on = None
schema = settings.database.SCHEMA_NAME


def upgrade():
    op.create_table(
        "tutorbook",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.String(255),
                  sa.ForeignKey(f"{schema}.school.organization_id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("pdf", sa.LargeBinary(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("indexed_page_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "sha256", name="uq_tutorbook_school_hash"),
        schema=schema,
    )
    op.create_index("ix_tutorbook_organization_id", "tutorbook", ["organization_id"], schema=schema)
    op.create_table(
        "tutorpassage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("book_id", sa.Uuid(),
                  sa.ForeignKey(f"{schema}.tutorbook.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(),
                  sa.Computed("to_tsvector('simple'::regconfig, search_text)", persisted=True), nullable=False),
        sa.UniqueConstraint("book_id", "page", "position", name="uq_tutorpassage_page_position"),
        sa.CheckConstraint("page > 0 AND position >= 0", name="ck_tutorpassage_page_position"),
        schema=schema,
    )
    op.create_index("ix_tutorpassage_search_vector", "tutorpassage", ["search_vector"],
                    postgresql_using="gin", schema=schema)


def downgrade():
    op.drop_table("tutorpassage", schema=schema)
    op.drop_table("tutorbook", schema=schema)
