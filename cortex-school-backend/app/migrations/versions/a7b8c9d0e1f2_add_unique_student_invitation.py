"""prevent duplicate student conversion invitations

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-07-29 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

from core.config import settings

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

schema = settings.database.SCHEMA_NAME


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_invitation_student", "invitation", ["student_id"], schema=schema
    )


def downgrade() -> None:
    op.drop_constraint("uq_invitation_student", "invitation", schema=schema)
