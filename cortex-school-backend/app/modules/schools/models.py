from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, SCHEMA_NAME


class Country(Base):
    __table_args__ = (
        UniqueConstraint("name", name="uq_country_name"),
        CheckConstraint(
            "code ~ '^[A-Z]{2}$'",
            name="ck_country_iso_code",
        ),
        CheckConstraint(
            "calling_code ~ '^\\+[0-9]{1,4}$'",
            name="ck_country_calling_code",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_country_name"),
    )

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    calling_code: Mapped[str] = mapped_column(String(8), nullable=False)


class School(Base):
    __table_args__ = (
        CheckConstraint(
            "cardinality(instructional_weekdays) > 0 AND "
            "instructional_weekdays <@ "
            "ARRAY[0,1,2,3,4,5,6]::smallint[]",
            name="ck_school_instructional_weekdays",
        ),
        CheckConstraint(
            "ai_teacher_draft_default_language IN ('auto', 'en', 'fr', 'ar')",
            name="ck_school_ai_teacher_draft_language",
        ),
        CheckConstraint(
            "ai_guardian_weekly_explanation_default_language IN ('auto', 'en', 'fr', 'ar')",
            name="ck_school_ai_guardian_weekly_explanation_language",
        ),
    )

    organization_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    country_code: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.country.code", ondelete="RESTRICT"),
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="Africa/Tunis",
        server_default="Africa/Tunis",
        nullable=False,
    )
    instructional_weekdays: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger),
        default=lambda: [0, 1, 2, 3, 4],
        server_default="{0,1,2,3,4}",
        nullable=False,
    )
    attendance_cutoff_time: Mapped[time] = mapped_column(
        Time(),
        default=time(hour=10),
        server_default="10:00:00",
        nullable=False,
    )
    ai_teacher_draft_enabled: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
        nullable=False,
    )
    ai_chat_data_enabled: Mapped[bool] = mapped_column(
        default=True,
        server_default="true",
        nullable=False,
    )
    ai_chat_data_revision: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    ai_teacher_draft_default_language: Mapped[str] = mapped_column(
        String(16),
        default="auto",
        server_default="auto",
        nullable=False,
    )
    ai_guardian_weekly_explanation_enabled: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
        nullable=False,
    )
    ai_guardian_weekly_explanation_default_language: Mapped[str] = mapped_column(
        String(16),
        default="auto",
        server_default="auto",
        nullable=False,
    )

    def validate_attendance_settings(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc

        weekdays = set(self.instructional_weekdays)
        if (
            not weekdays
            or len(weekdays) != len(self.instructional_weekdays)
            or not weekdays.issubset(set(range(7)))
        ):
            raise ValueError(
                "instructional_weekdays must contain unique values from 0 to 6"
            )
