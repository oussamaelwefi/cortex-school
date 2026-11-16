import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from core.pydantic import CustomBaseModel
from modules.attendance.models import AttendanceStatus


AttendanceNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]


class AttendanceEntryRequest(CustomBaseModel):
    placement_id: uuid.UUID
    status: AttendanceStatus
    note: AttendanceNote | None = None

    @field_validator("note", mode="before")
    @classmethod
    def empty_note_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class AttendanceSheetRequest(CustomBaseModel):
    entries: list[AttendanceEntryRequest]

    @model_validator(mode="after")
    def placement_ids_must_be_unique(self):
        placement_ids = [entry.placement_id for entry in self.entries]
        if len(placement_ids) != len(set(placement_ids)):
            raise ValueError("Each placement may appear only once")
        return self


class AttendanceEntryResponse(CustomBaseModel):
    attendance_record_id: uuid.UUID | None
    placement_id: uuid.UUID
    enrollment_id: uuid.UUID
    student_id: uuid.UUID
    first_name: str
    last_name: str
    status: AttendanceStatus
    note: str | None
    updated_at: datetime | None


class AttendanceSheetResponse(CustomBaseModel):
    submission_id: uuid.UUID | None
    classroom_id: uuid.UUID
    classroom_name: str
    school_date: date
    submitted: bool
    submitted_by_workos_user_id: str | None
    submitted_at: datetime | None
    updated_by_workos_user_id: str | None
    updated_at: datetime | None
    entries: list[AttendanceEntryResponse]


class GuardianAttendanceResponse(CustomBaseModel):
    attendance_record_id: uuid.UUID
    student_id: uuid.UUID
    classroom_id: uuid.UUID
    classroom_name: str
    academic_year_id: uuid.UUID
    academic_year_name: str
    school_date: date
    status: AttendanceStatus
    note: str | None
    updated_at: datetime


class AttendanceStatusCounts(CustomBaseModel):
    present: int = 0
    absent: int = 0
    late: int = 0
    excused: int = 0


class AdminClassAttendanceResponse(CustomBaseModel):
    classroom_id: uuid.UUID
    classroom_name: str
    academic_year_id: uuid.UUID
    academic_year_name: str
    school_date: date
    status: str
    active_student_count: int
    recorded_student_count: int
    counts: AttendanceStatusCounts
    submission_id: uuid.UUID | None
    submitted_by_workos_user_id: str | None
    submitted_at: datetime | None
    updated_by_workos_user_id: str | None
    updated_at: datetime | None


class AdminAttendanceSummaryResponse(CustomBaseModel):
    school_date: date
    expected_classroom_count: int
    submitted_classroom_count: int
    missing_classroom_count: int
    classrooms: list[AdminClassAttendanceResponse] = Field(default_factory=list)
