"""add academic year calendar foundation

Revision ID: b3c4d5e6f7a8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-10 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME
academic_year_status_enum = postgresql.ENUM(
    "draft",
    "active",
    "closed",
    name="academic_year_status_enum",
    schema=schema,
    create_type=False,
)
calendar_entry_type_enum = postgresql.ENUM(
    "term",
    "holiday",
    "break",
    "non_instruction_day",
    name="calendar_entry_type_enum",
    schema=schema,
    create_type=False,
)


def upgrade() -> None:
    connection = op.get_bind()
    orphaned_year_count = connection.execute(
        sa.text(
            f"""
            SELECT count(*)
            FROM "{schema}"."academicyear" AS academic_year
            LEFT JOIN "{schema}"."school" AS school
              ON school.organization_id = academic_year.organization_id
            WHERE school.organization_id IS NULL
            """
        )
    ).scalar_one()
    if orphaned_year_count:
        raise RuntimeError(
            "Every academic year must reference an existing school before "
            "this migration can run"
        )

    academic_year_status_enum.create(connection, checkfirst=True)
    calendar_entry_type_enum.create(connection, checkfirst=True)

    op.add_column(
        "academicyear",
        sa.Column(
            "status",
            academic_year_status_enum,
            nullable=False,
            server_default="draft",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_academicyear_organization_id",
        "academicyear",
        ["organization_id"],
        schema=schema,
    )
    op.create_foreign_key(
        "fk_academicyear_organization_id",
        "academicyear",
        "school",
        ["organization_id"],
        ["organization_id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="RESTRICT",
    )

    op.create_table(
        "academiccalendar",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "academic_year_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["academic_year_id"],
            [f"{schema}.academicyear.id"],
            name="fk_academiccalendar_academic_year_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_academiccalendar"),
        sa.UniqueConstraint(
            "academic_year_id",
            name="uq_academiccalendar_academic_year_id",
        ),
        schema=schema,
    )
    connection.execute(
        sa.text(
            f"""
            INSERT INTO "{schema}"."academiccalendar"
                (id, academic_year_id, created_at, updated_at)
            SELECT gen_random_uuid(), id, now(), now()
            FROM "{schema}"."academicyear"
            """
        )
    )

    op.create_table(
        "calendarentry",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "academic_calendar_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("entry_type", calendar_entry_type_enum, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ends_on >= starts_on",
            name="ck_calendarentry_valid_dates",
        ),
        sa.ForeignKeyConstraint(
            ["academic_calendar_id"],
            [f"{schema}.academiccalendar.id"],
            name="fk_calendarentry_academic_calendar_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_calendarentry"),
        schema=schema,
    )
    op.create_index(
        "ix_calendarentry_academic_calendar_id",
        "calendarentry",
        ["academic_calendar_id"],
        schema=schema,
    )
    op.create_index(
        "ix_calendarentry_entry_type",
        "calendarentry",
        ["entry_type"],
        schema=schema,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calendarentry_entry_type",
        table_name="calendarentry",
        schema=schema,
    )
    op.drop_index(
        "ix_calendarentry_academic_calendar_id",
        table_name="calendarentry",
        schema=schema,
    )
    op.drop_table("calendarentry", schema=schema)
    op.drop_table("academiccalendar", schema=schema)

    op.drop_constraint(
        "fk_academicyear_organization_id",
        "academicyear",
        schema=schema,
    )
    op.drop_index(
        "ix_academicyear_organization_id",
        table_name="academicyear",
        schema=schema,
    )
    op.drop_column("academicyear", "status", schema=schema)

    calendar_entry_type_enum.drop(op.get_bind(), checkfirst=True)
    academic_year_status_enum.drop(op.get_bind(), checkfirst=True)
