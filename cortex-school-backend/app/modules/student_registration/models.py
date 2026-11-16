import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, SCHEMA_NAME, TimestampMixin, create_sql_enum, uuid_pk


class StudentRegistrationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class StudentRegistrationRequest(Base, TimestampMixin):
    id: Mapped[uuid_pk]
    guardian_workos_user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    child_first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    child_last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.academicyear.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[StudentRegistrationStatus] = mapped_column(
        create_sql_enum(
            StudentRegistrationStatus,
            "student_registration_status_enum",
        ),
        default=StudentRegistrationStatus.PENDING,
        nullable=False,
        index=True,
    )
    resolved_student_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.student.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

