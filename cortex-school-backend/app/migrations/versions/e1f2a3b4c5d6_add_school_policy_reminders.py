"""Add school policy retrieval and approved acknowledgement reminders."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings


revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None
schema = settings.database.SCHEMA_NAME


def timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade():
    op.create_table(
        "schoolpolicypassage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("heading", sa.String(150), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "search_vector", postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, search_text)", persisted=True),
            nullable=False,
        ),
        *timestamps(),
        schema=schema,
    )
    for field in ("document_id", "organization_id"):
        op.create_index(f"ix_schoolpolicypassage_{field}", "schoolpolicypassage", [field], schema=schema)
    op.create_index(
        "ix_schoolpolicypassage_search_vector", "schoolpolicypassage", ["search_vector"],
        schema=schema, postgresql_using="gin",
    )
    op.create_table(
        "reminderproposal",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.String(255), nullable=False),
        sa.Column("update_id", sa.Uuid(), sa.ForeignKey(f"{schema}.studentupdate.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("draft_message", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False),
        sa.Column("approved_message", sa.Text()),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.UniqueConstraint("update_id", name="uq_reminderproposal_update"),
        sa.CheckConstraint("status IN ('draft', 'queued', 'completed')", name="ck_reminderproposal_status"),
        schema=schema,
    )
    op.create_index("ix_reminderproposal_queue", "reminderproposal", ["status", "approved_at"], schema=schema)
    op.create_table(
        "reminderdelivery",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey(f"{schema}.reminderproposal.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guardian_id", sa.String(255), nullable=False),
        sa.Column("guardian_name", sa.String(255)),
        sa.Column("students", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("outcome_reason", sa.String(255)),
        *timestamps(),
        sa.UniqueConstraint("proposal_id", "guardian_id", name="uq_reminderdelivery_proposal_guardian"),
        sa.CheckConstraint("status IN ('pending', 'sent', 'skipped', 'failed')", name="ck_reminderdelivery_status"),
        schema=schema,
    )
    op.add_column("notification", sa.Column("message", sa.Text()), schema=schema)
    quoted_schema = op.get_context().dialect.identifier_preparer.quote_schema(schema)
    op.execute(f"ALTER TYPE {quoted_schema}.student_update_event_type_enum ADD VALUE 'reminder_sent'")
    op.execute(f"ALTER TYPE {quoted_schema}.notification_type_enum ADD VALUE 'acknowledgement_reminder'")


def downgrade():
    quoted_schema = op.get_context().dialect.identifier_preparer.quote_schema(schema)
    op.execute(f"DELETE FROM {quoted_schema}.notification WHERE notification_type = 'acknowledgement_reminder'")
    op.execute(f"DELETE FROM {quoted_schema}.studentupdateevent WHERE event_type = 'reminder_sent'")
    for table, column, enum_name, values in (
        ("notification", "notification_type", "notification_type_enum", (
            "update_assigned", "teacher_feedback", "status_changed",
        )),
        ("studentupdateevent", "event_type", "student_update_event_type_enum", (
            "assigned", "teacher_feedback", "guardian_reply", "guardian_acknowledged", "status_changed",
        )),
    ):
        name = f"{quoted_schema}.{enum_name}"
        old_name = f"{enum_name}_old"
        labels = ", ".join(f"'{value}'" for value in values)
        op.execute(f"ALTER TYPE {name} RENAME TO {old_name}")
        op.execute(f"CREATE TYPE {name} AS ENUM ({labels})")
        op.execute(
            f"ALTER TABLE {quoted_schema}.{table} ALTER COLUMN {column} "
            f"TYPE {name} USING {column}::text::{name}"
        )
        op.execute(f"DROP TYPE {quoted_schema}.{old_name}")
    op.drop_column("notification", "message", schema=schema)
    op.drop_table("reminderdelivery", schema=schema)
    op.drop_table("reminderproposal", schema=schema)
    op.drop_table("schoolpolicypassage", schema=schema)
