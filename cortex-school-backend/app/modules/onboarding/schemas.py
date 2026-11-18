import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from core.pydantic import CustomBaseModel
from modules.onboarding.models import SchoolRequestStatus


class SchoolRequestCreate(CustomBaseModel):
    school_name: str = Field(min_length=2, max_length=255)
    country_code: str = Field(pattern="^[A-Z]{2}$")
    timezone: str = Field(min_length=1, max_length=64)
    notes: str = Field(default="", max_length=2000)

    @field_validator("school_name", "notes", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Choose a valid IANA timezone") from exc
        return value


class SchoolRequestResponse(CustomBaseModel):
    id: uuid.UUID
    school_name: str
    country_code: str
    timezone: str
    notes: str
    status: SchoolRequestStatus
    rejection_reason: str | None
    organization_id: str | None
    created_at: datetime
    completed_at: datetime | None


class OnboardingCountryResponse(CustomBaseModel):
    code: str
    name: str


class SchoolRequestRejection(CustomBaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value
