import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, SCHEMA_NAME, TimestampMixin, uuid_pk


class Enrollment(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "academic_year_id",
            name="uq_enrollment_student_academic_year",
        ),
    )

    id: Mapped[uuid_pk]
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.student.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.academicyear.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
