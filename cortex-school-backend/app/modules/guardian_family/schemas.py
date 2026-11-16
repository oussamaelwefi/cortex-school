import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from core.pydantic import CustomBaseModel
from modules.attendance.models import AttendanceStatus
from modules.student_registration.models import StudentRegistrationStatus
from modules.student_updates.models import (
    StudentUpdateActorRole,
    StudentUpdateEventType,
    StudentUpdateStatus,
    StudentUpdateTargetType,
)
from modules.student_updates.schemas import GuardianUpdateDetailResponse


class GuardianPlacementResponse(CustomBaseModel):
    state: Literal["current", "not_placed", "not_enrolled"]
    classroom_id: uuid.UUID | None = None
    classroom_name: str | None = None
    academic_year_id: uuid.UUID | None = None
    academic_year_name: str | None = None


class GuardianAttendanceSnapshot(CustomBaseModel):
    state: Literal["submitted", "not_submitted", "not_expected"]
    school_date: date | None = None
    status: AttendanceStatus | None = None
    note: str | None = None
    classroom_id: uuid.UUID | None = None
    classroom_name: str | None = None
    updated_at: datetime | None = None


class GuardianAttendanceSummary(CustomBaseModel):
    today: GuardianAttendanceSnapshot
    latest_submitted: GuardianAttendanceSnapshot | None = None


class GuardianUpdateSummary(CustomBaseModel):
    recipient_id: uuid.UUID
    update_id: uuid.UUID
    target_type: StudentUpdateTargetType
    title: str
    occurred_at: datetime
    author_label: str
    unread: bool
    requires_acknowledgement: bool
    acknowledged: bool
    needs_response: bool
    allows_replies: bool


class GuardianFamilyChildResponse(CustomBaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    placement: GuardianPlacementResponse
    attendance: GuardianAttendanceSummary
    latest_update: GuardianUpdateSummary | None = None
    unread_update_count: int
    needs_response_count: int


class GuardianRegistrationRequestResponse(CustomBaseModel):
    id: uuid.UUID
    child_first_name: str
    child_last_name: str
    academic_year_id: uuid.UUID
    academic_year_name: str
    status: StudentRegistrationStatus
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class GuardianFamilyOverviewResponse(CustomBaseModel):
    school_date: date
    school_timezone: str
    children: list[GuardianFamilyChildResponse]
    registration_requests: list[GuardianRegistrationRequestResponse]


class GuardianFamilyStudentResponse(CustomBaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    placement: GuardianPlacementResponse


class GuardianAttendanceActivity(CustomBaseModel):
    type: Literal["attendance"]
    id: uuid.UUID
    student_id: uuid.UUID
    occurred_at: datetime
    school_date: date
    status: AttendanceStatus
    note: str | None
    classroom_id: uuid.UUID
    classroom_name: str


class GuardianUpdateActivity(CustomBaseModel):
    type: Literal["update"]
    id: uuid.UUID
    student_id: uuid.UUID
    occurred_at: datetime
    recipient_id: uuid.UUID
    update_id: uuid.UUID
    classroom_id: uuid.UUID
    classroom_name: str
    target_type: StudentUpdateTargetType
    title: str
    body: str | None
    due_at: datetime | None
    author_label: str
    status: StudentUpdateStatus
    read_at: datetime | None
    acknowledged_at: datetime | None
    requires_acknowledgement: bool
    allows_replies: bool


class GuardianUpdateEventActivity(CustomBaseModel):
    type: Literal["update_event"]
    id: uuid.UUID
    student_id: uuid.UUID
    occurred_at: datetime
    recipient_id: uuid.UUID
    update_id: uuid.UUID
    classroom_id: uuid.UUID
    classroom_name: str
    title: str
    event_type: StudentUpdateEventType
    actor_role: StudentUpdateActorRole
    author_label: str
    content: str | None
    previous_status: StudentUpdateStatus | None
    new_status: StudentUpdateStatus | None


GuardianFamilyActivity = Annotated[
    GuardianAttendanceActivity
    | GuardianUpdateActivity
    | GuardianUpdateEventActivity,
    Field(discriminator="type"),
]


class GuardianFamilyFeedResponse(CustomBaseModel):
    student: GuardianFamilyStudentResponse
    school_date: date
    school_timezone: str
    current_week_start: date
    current_week_end: date
    ai_guardian_weekly_explanation_enabled: bool
    items: list[GuardianFamilyActivity]
    limit: int
    offset: int
    has_more: bool


class GuardianFamilyUpdateDetailResponse(GuardianUpdateDetailResponse):
    """Alias for the family route's safe update detail contract."""

    school_timezone: str
