from typing import Annotated
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, StringConstraints, field_validator, model_validator

from core.pydantic import CustomBaseModel
from modules.ai.schemas import TeacherDraftLanguage


SchoolTimezone = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class SchoolAttendanceSettingsRequest(CustomBaseModel):
    timezone: SchoolTimezone
    instructional_weekdays: list[int] = Field(min_length=1, max_length=7)
    attendance_cutoff_time: time = Field(default=time(hour=10))

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_valid(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def weekdays_must_be_unique_and_valid(self):
        weekdays = set(self.instructional_weekdays)
        if (
            len(weekdays) != len(self.instructional_weekdays)
            or not weekdays.issubset(set(range(7)))
        ):
            raise ValueError(
                "instructional_weekdays must contain unique values from 0 to 6"
            )
        return self

    @field_validator("attendance_cutoff_time")
    @classmethod
    def cutoff_must_be_local_minute(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("attendance_cutoff_time must not include a timezone")
        if value.second or value.microsecond:
            raise ValueError("attendance_cutoff_time must use whole minutes")
        return value


class SchoolAttendanceSettingsResponse(CustomBaseModel):
    timezone: str
    instructional_weekdays: list[int]
    attendance_cutoff_time: time


class SchoolAISettingsRequest(CustomBaseModel):
    ai_teacher_draft_enabled: bool = False
    ai_teacher_draft_default_language: TeacherDraftLanguage = (
        TeacherDraftLanguage.AUTO
    )
    ai_guardian_weekly_explanation_enabled: bool = False
    ai_guardian_weekly_explanation_default_language: TeacherDraftLanguage = (
        TeacherDraftLanguage.AUTO
    )


class SchoolAISettingsResponse(CustomBaseModel):
    ai_teacher_draft_enabled: bool
    ai_teacher_draft_default_language: TeacherDraftLanguage
    ai_guardian_weekly_explanation_enabled: bool
    ai_guardian_weekly_explanation_default_language: TeacherDraftLanguage
