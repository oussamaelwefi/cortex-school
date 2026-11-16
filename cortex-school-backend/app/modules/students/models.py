import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, SCHEMA_NAME, TimestampMixin, uuid_pk


class Student(Base, TimestampMixin):
    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)


class GuardianStudent(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "guardian_workos_user_id",
            name="uq_guardianstudent_student_guardian",
        ),
    )

    id: Mapped[uuid_pk]
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.student.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guardian_workos_user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
