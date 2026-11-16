"""add school attendance settings

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-08-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def upgrade() -> None:
    op.add_column(
        "school",
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="Africa/Tunis",
            nullable=False,
        ),
        schema=schema,
    )
    op.add_column(
        "school",
        sa.Column(
            "instructional_weekdays",
            postgresql.ARRAY(sa.SmallInteger()),
            server_default="{0,1,2,3,4}",
            nullable=False,
        ),
        schema=schema,
    )
    op.create_check_constraint(
        "ck_school_instructional_weekdays",
        "school",
        "cardinality(instructional_weekdays) > 0 AND "
        "instructional_weekdays <@ "
        "ARRAY[0,1,2,3,4,5,6]::smallint[]",
        schema=schema,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_school_instructional_weekdays",
        "school",
        schema=schema,
        type_="check",
    )
    op.drop_column("school", "instructional_weekdays", schema=schema)
    op.drop_column("school", "timezone", schema=schema)
