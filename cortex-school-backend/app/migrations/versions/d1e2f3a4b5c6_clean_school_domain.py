"""clean school domain and add country-backed academic years

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-08-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def upgrade() -> None:
    connection = op.get_bind()
    academic_year_count = connection.execute(
        sa.text(f'SELECT count(*) FROM "{schema}"."academicyear"')
    ).scalar_one()
    if academic_year_count:
        raise RuntimeError(
            "Academic year dates must be backfilled before this migration can run"
        )

    op.drop_constraint("uq_invitation_student", "invitation", schema=schema)
    op.drop_constraint("fk_invitation_student_id", "invitation", schema=schema)
    op.drop_index("ix_invitation_student_id", table_name="invitation", schema=schema)
    op.drop_column("invitation", "student_id", schema=schema)

    op.drop_column("student", "converted_at", schema=schema)
    op.drop_column("student", "converted_to_role", schema=schema)
    op.drop_column("student", "conversion_status", schema=schema)
    op.drop_column("guardianstudent", "relationship", schema=schema)

    op.drop_constraint("ck_enrollment_payment_status", "enrollment", schema=schema)
    op.drop_column("enrollment", "payment_status", schema=schema)
    op.drop_constraint("fk_enrollment_student_id", "enrollment", schema=schema)
    op.drop_constraint("fk_enrollment_academic_year_id", "enrollment", schema=schema)
    op.create_foreign_key(
        "fk_enrollment_student_id",
        "enrollment",
        "student",
        ["student_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_enrollment_academic_year_id",
        "enrollment",
        "academicyear",
        ["academic_year_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="RESTRICT",
    )

    op.add_column(
        "academicyear",
        sa.Column("starts_on", sa.Date(), nullable=False),
        schema=schema,
    )
    op.add_column(
        "academicyear",
        sa.Column("ends_on", sa.Date(), nullable=False),
        schema=schema,
    )
    op.create_check_constraint(
        "ck_academicyear_valid_dates",
        "academicyear",
        "ends_on > starts_on",
        schema=schema,
    )

    op.create_table(
        "country",
        sa.Column("code", sa.String(length=2), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("calling_code", sa.String(length=8), nullable=False),
        sa.CheckConstraint(
            "code ~ '^[A-Z]{2}$'",
            name="ck_country_iso_code",
        ),
        sa.CheckConstraint(
            "calling_code ~ '^\\+[0-9]{1,4}$'",
            name="ck_country_calling_code",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_country_name",
        ),
        sa.PrimaryKeyConstraint("code", name="pk_country"),
        sa.UniqueConstraint("name", name="uq_country_name"),
        schema=schema,
    )
    op.bulk_insert(
        sa.table(
            "country",
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("calling_code", sa.String),
            schema=schema,
        ),
        [{"code": "TN", "name": "Tunisia", "calling_code": "+216"}],
    )
    op.create_table(
        "school",
        sa.Column("organization_id", sa.String(length=255), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["country_code"],
            [f"{schema}.country.code"],
            name="fk_school_country_code",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("organization_id", name="pk_school"),
        schema=schema,
    )


def downgrade() -> None:
    op.drop_table("school", schema=schema)
    op.drop_table("country", schema=schema)

    op.drop_constraint("ck_academicyear_valid_dates", "academicyear", schema=schema)
    op.drop_column("academicyear", "ends_on", schema=schema)
    op.drop_column("academicyear", "starts_on", schema=schema)

    op.drop_constraint("fk_enrollment_academic_year_id", "enrollment", schema=schema)
    op.drop_constraint("fk_enrollment_student_id", "enrollment", schema=schema)
    op.create_foreign_key(
        "fk_enrollment_student_id",
        "enrollment",
        "student",
        ["student_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_enrollment_academic_year_id",
        "enrollment",
        "academicyear",
        ["academic_year_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="CASCADE",
    )
    op.add_column(
        "enrollment",
        sa.Column(
            "payment_status",
            sa.String(length=16),
            nullable=False,
            server_default="unpaid",
        ),
        schema=schema,
    )
    op.alter_column(
        "enrollment",
        "payment_status",
        server_default=None,
        schema=schema,
    )
    op.create_check_constraint(
        "ck_enrollment_payment_status",
        "enrollment",
        "payment_status IN ('unpaid', 'partial', 'full')",
        schema=schema,
    )

    op.add_column(
        "guardianstudent",
        sa.Column("relationship", sa.String(length=64), nullable=True),
        schema=schema,
    )
    op.add_column(
        "student",
        sa.Column(
            "conversion_status",
            sa.String(length=32),
            nullable=False,
            server_default="none",
        ),
        schema=schema,
    )
    op.alter_column(
        "student",
        "conversion_status",
        server_default=None,
        schema=schema,
    )
    op.add_column(
        "student",
        sa.Column("converted_to_role", sa.String(length=32), nullable=True),
        schema=schema,
    )
    op.add_column(
        "student",
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )

    op.add_column(
        "invitation",
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=schema,
    )
    op.create_index(
        "ix_invitation_student_id",
        "invitation",
        ["student_id"],
        schema=schema,
    )
    op.create_foreign_key(
        "fk_invitation_student_id",
        "invitation",
        "student",
        ["student_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_invitation_student",
        "invitation",
        ["student_id"],
        schema=schema,
    )
