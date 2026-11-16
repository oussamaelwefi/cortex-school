import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db import (
    Base,
    SCHEMA_NAME,
    TimestampMixin,
    create_sql_enum,
    uuid_pk,
)


class AttendanceStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"


class AttendanceSubmission(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "classroom_id",
            "school_date",
            name="uq_attendancesubmission_classroom_date",
        ),
    )

    id: Mapped[uuid_pk]
    classroom_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.classroom.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    school_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    submitted_by_workos_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_by_workos_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )


class AttendanceRecord(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "class_enrollment_id",
            "school_date",
            name="uq_attendancerecord_placement_date",
        ),
    )

    id: Mapped[uuid_pk]
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            f"{SCHEMA_NAME}.attendancesubmission.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    class_enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.classenrollment.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    school_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[AttendanceStatus] = mapped_column(
        create_sql_enum(AttendanceStatus, "attendance_status_enum"),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    updated_by_workos_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
