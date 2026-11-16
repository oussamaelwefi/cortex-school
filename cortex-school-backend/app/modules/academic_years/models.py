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


class AcademicYearStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class CalendarEntryType(StrEnum):
    TERM = "term"
    HOLIDAY = "holiday"
    BREAK = "break"
    NON_INSTRUCTION_DAY = "non_instruction_day"


class AcademicYear(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_academicyear_organization_name",
        ),
        CheckConstraint(
            "ends_on > starts_on",
            name="ck_academicyear_valid_dates",
        ),
    )

    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{SCHEMA_NAME}.school.organization_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AcademicYearStatus] = mapped_column(
        create_sql_enum(AcademicYearStatus, "academic_year_status_enum"),
        default=AcademicYearStatus.DRAFT,
        server_default=AcademicYearStatus.DRAFT.value,
        nullable=False,
    )


class AcademicCalendar(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "academic_year_id",
            name="uq_academiccalendar_academic_year_id",
        ),
    )

    id: Mapped[uuid_pk]
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.academicyear.id", ondelete="CASCADE"),
        nullable=False,
    )


class CalendarEntry(Base, TimestampMixin):
    __table_args__ = (
        CheckConstraint(
            "ends_on >= starts_on",
            name="ck_calendarentry_valid_dates",
        ),
    )

    id: Mapped[uuid_pk]
    academic_calendar_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.academiccalendar.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_type: Mapped[CalendarEntryType] = mapped_column(
        create_sql_enum(CalendarEntryType, "calendar_entry_type_enum"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
