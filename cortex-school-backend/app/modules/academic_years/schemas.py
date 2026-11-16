import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from core.pydantic import CustomBaseModel
from modules.academic_years.models import AcademicYearStatus, CalendarEntryType


class AcademicYearCreateRequest(CustomBaseModel):
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
    ]
    starts_on: date
    ends_on: date

    @model_validator(mode="after")
    def validate_dates(self):
        if self.ends_on <= self.starts_on:
            raise ValueError("ends_on must be after starts_on")
        return self


class AcademicYearResponse(CustomBaseModel):
    id: uuid.UUID
    organization_id: str
    name: str
    starts_on: date
    ends_on: date
    status: AcademicYearStatus
    created_at: datetime
    updated_at: datetime
    warnings: list[str] = Field(default_factory=list)


class AcademicYearReadinessResponse(CustomBaseModel):
    can_publish: bool
    errors: list[str]
    warnings: list[str]


class CalendarEntryRequest(CustomBaseModel):
    entry_type: CalendarEntryType
    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    ]
    starts_on: date
    ends_on: date

    @model_validator(mode="after")
    def validate_dates(self):
        if self.ends_on < self.starts_on:
            raise ValueError("ends_on must be on or after starts_on")
        return self


class CalendarEntryResponse(CustomBaseModel):
    id: uuid.UUID
    academic_calendar_id: uuid.UUID
    entry_type: CalendarEntryType
    title: str
    starts_on: date
    ends_on: date
    created_at: datetime
    updated_at: datetime


class AcademicCalendarResponse(CustomBaseModel):
    id: uuid.UUID
    academic_year_id: uuid.UUID
    entries: list[CalendarEntryResponse]
    created_at: datetime
    updated_at: datetime
