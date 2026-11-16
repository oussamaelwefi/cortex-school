"""Store original school policy PDFs for guardian downloads."""

import sqlalchemy as sa
from alembic import op

from core.config import settings


revision = "a4e7d2b9c1f0"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None
schema = settings.database.SCHEMA_NAME


def upgrade():
    op.create_table(
        "schoolpolicyfile",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=schema,
    )
    op.create_index(
        "ix_schoolpolicyfile_organization_id", "schoolpolicyfile", ["organization_id"], schema=schema
    )


def downgrade():
    op.drop_table("schoolpolicyfile", schema=schema)
