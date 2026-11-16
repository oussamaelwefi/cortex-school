"""update invitation user roles

Revision ID: c7e4b2a19d63
Revises: a8c3f5d9e2b1
Create Date: 2026-07-23 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

from core.config import settings

# revision identifiers, used by Alembic.
revision: str = "c7e4b2a19d63"
down_revision: Union[str, None] = "a8c3f5d9e2b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def _rename_enum_value(old_value: str, new_value: str) -> None:
    op.execute(
        f'ALTER TYPE "{schema}"."user_roles_enum" '
        f"RENAME VALUE '{old_value}' TO '{new_value}'"
    )


def upgrade() -> None:
    _rename_enum_value("admin", "school_admin")
    _rename_enum_value("student", "guardian")


def downgrade() -> None:
    _rename_enum_value("school_admin", "admin")
    _rename_enum_value("guardian", "student")
