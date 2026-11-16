import uuid
from datetime import date
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db import (
    Base,
    SCHEMA_NAME,
    TimestampMixin,
    create_sql_enum,
    uuid_pk,
)


class TeacherAssignmentRole(StrEnum):
    LEAD = "lead"
    ASSISTANT = "assistant"


class Classroom(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "academic_year_id",
            "name",
            name="uq_classroom_academic_year_name",
        ),
    )

    id: Mapped[uuid_pk]
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.academicyear.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)


class ClassEnrollment(Base, TimestampMixin):
    __table_args__ = (
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_classenrollment_valid_dates",
        ),
    )

    id: Mapped[uuid_pk]
    classroom_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.classroom.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.enrollment.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)


class TeacherAssignment(Base, TimestampMixin):
    __table_args__ = (
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_teacherassignment_valid_dates",
        ),
    )

    id: Mapped[uuid_pk]
    classroom_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.classroom.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    teacher_workos_user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    role: Mapped[TeacherAssignmentRole] = mapped_column(
        create_sql_enum(
            TeacherAssignmentRole,
            "teacher_assignment_role_enum",
        ),
        nullable=False,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
