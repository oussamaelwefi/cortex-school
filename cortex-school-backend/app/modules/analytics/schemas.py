import uuid
from datetime import date

from pydantic import BaseModel, Field


class DateRange(BaseModel):
    start: date
    end: date


class AttendanceCounts(BaseModel):
    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0
    submissions: int = 0

    def add(self, other: "AttendanceCounts") -> None:
        for field in type(self).model_fields:
            setattr(self, field, getattr(self, field) + getattr(other, field))


class RegistrationCounts(BaseModel):
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    withdrawn: int = 0


class AnalyticsTotals(BaseModel):
    attendance: AttendanceCounts = Field(default_factory=AttendanceCounts)
    registrations: RegistrationCounts = Field(default_factory=RegistrationCounts)
    updates_published: int = 0
    acknowledgements_required: int = 0
    acknowledgements_received: int = 0


class AnalyticsBucket(DateRange):
    totals: AnalyticsTotals = Field(default_factory=AnalyticsTotals)


class ClassroomAttendance(BaseModel):
    id: uuid.UUID
    name: str
    academic_year: str
    attendance: AttendanceCounts = Field(default_factory=AttendanceCounts)


class AnalyticsSnapshot(BaseModel):
    enrolled_students: int
    pending_registrations: int
    updates_with_overdue_acknowledgements: int
    failed_invitations: int


class SchoolAnalyticsResponse(BaseModel):
    current: AnalyticsBucket
    previous: AnalyticsBucket
    trend: list[AnalyticsBucket]
    classrooms: list[ClassroomAttendance]
    snapshot: AnalyticsSnapshot
