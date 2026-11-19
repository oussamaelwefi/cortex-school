"""Bounded schemas shared by school chat tools and HTTP responses."""

import uuid
from datetime import date
from typing import Literal

from core.pydantic import CustomBaseModel
from pydantic import Field, model_validator

ChatRole = Literal["admin", "teacher", "guardian"]


class SchoolDataQuery(CustomBaseModel):
    dataset: Literal[
        "overview",
        "academic_years",
        "students",
        "classrooms",
        "enrollments",
        "attendance",
        "updates",
        "acknowledgements",
        "publications",
        "calendar",
        "registrations",
        "invitations",
        "members",
    ]
    search: str = Field(default="", max_length=120)
    student_id: uuid.UUID | None = None
    classroom_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID | None = None
    record_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: str | None = Field(default=None, max_length=32)
    unread_only: bool = False
    overdue_only: bool = False
    limit: int = Field(default=10, ge=1, le=25)
    offset: int = Field(default=0, ge=0, le=5000)

    @model_validator(mode="after")
    def bounded_dates(self):
        if self.date_from and self.date_to:
            if not 0 <= (self.date_to - self.date_from).days <= 366:
                raise ValueError("Use an ordered date range of at most 366 days")
        return self


class ChatSource(CustomBaseModel):
    id: str
    label: str
    href: str | None = None
    excerpt: str | None = None
