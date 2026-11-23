"""Add classroom study materials with separate school-wide book visibility."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision = "e7a4c63f9b20"
down_revision = "b4c6d8e0f2a3"
branch_labels = None
depends_on = None
schema = settings.database.SCHEMA_NAME


def upgrade():
    op.create_table(
        "tutorclassbook",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.String(255),
                  sa.ForeignKey(f"{schema}.school.organization_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("pdf", sa.LargeBinary(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("indexed_page_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "sha256", name="uq_tutor_class_book_school_hash"),
        schema=schema,
    )
    op.create_table(
        "tutorclasspassage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("book_id", sa.Uuid(),
                  sa.ForeignKey(f"{schema}.tutorclassbook.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(),
                  sa.Computed("to_tsvector('simple'::regconfig, search_text)", persisted=True), nullable=False),
        sa.UniqueConstraint("book_id", "page", "position", name="uq_tutorclasspassage_page_position"),
        sa.CheckConstraint("page > 0 AND position >= 0", name="ck_tutorclasspassage_page_position"),
        schema=schema,
    )
    op.create_index("ix_tutorclasspassage_search_vector", "tutorclasspassage", ["search_vector"],
                    postgresql_using="gin", schema=schema)
    op.create_table(
        "tutorclassmaterial",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("classroom_id", sa.Uuid(),
                  sa.ForeignKey(f"{schema}.classroom.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_id", sa.Uuid(),
                  sa.ForeignKey(f"{schema}.tutorclassbook.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("subject", sa.String(100), nullable=False),
        sa.Column("grade_level", sa.Integer(), nullable=True),
        sa.Column("published_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("classroom_id", "book_id", name="uq_tutor_class_material_class_book"),
        sa.CheckConstraint("grade_level BETWEEN 1 AND 13", name="ck_tutor_class_material_grade"),
        schema=schema,
    )
    op.create_index("ix_tutorclassmaterial_book_id", "tutorclassmaterial", ["book_id"], schema=schema)


def downgrade():
    op.drop_table("tutorclassmaterial", schema=schema)
    op.drop_table("tutorclasspassage", schema=schema)
    op.drop_table("tutorclassbook", schema=schema)
