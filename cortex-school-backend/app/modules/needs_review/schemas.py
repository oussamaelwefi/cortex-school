import uuid
from datetime import date, datetime, time
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from core.pydantic import CustomBaseModel
from modules.invitations.models import UserRoles


class NeedsReviewCategory(StrEnum):
    REGISTRATION = "registration"
    INVITATION = "invitation"
    MISSING_ATTENDANCE = "missing_attendance"
    MISSING_ASSIGNMENT = "missing_assignment"
    ACKNOWLEDGEMENT = "acknowledgement"


class NeedsReviewSeverity(StrEnum):
    WARNING = "warning"
    URGENT = "urgent"


class RegistrationAction(CustomBaseModel):
    type: Literal["registration_request"]
    request_id: uuid.UUID


class InvitationAction(CustomBaseModel):
    type: Literal["invitation"]
    invitation_id: uuid.UUID


class AttendanceAction(CustomBaseModel):
    type: Literal["attendance"]
    classroom_id: uuid.UUID
    school_date: date


class AssignmentAction(CustomBaseModel):
    type: Literal["classroom_assignment"]
    academic_year_id: uuid.UUID
    classroom_id: uuid.UUID


class StudentUpdateAction(CustomBaseModel):
    type: Literal["student_update"]
    update_id: uuid.UUID


NeedsReviewAction = Annotated[
    RegistrationAction
    | InvitationAction
    | AttendanceAction
    | AssignmentAction
    | StudentUpdateAction,
    Field(discriminator="type"),
]


class NeedsReviewItem(CustomBaseModel):
    id: str
    category: NeedsReviewCategory
    severity: NeedsReviewSeverity
    title: str
    reason: str
    occurred_at: datetime | None
    due_at: datetime | None
    school_date: date | None
    classroom_name: str | None = None
    academic_year_name: str | None = None
    student_name: str | None = None
    invitation_email: str | None = None
    invitation_role: UserRoles | None = None
    teacher_name: str | None = None
    outstanding_acknowledgement_count: int | None = None
    affected_date_count: int | None = None
    action: NeedsReviewAction


class NeedsReviewResponse(CustomBaseModel):
    as_of: datetime
    school_date: date
    attendance_cutoff_time: time
    total_count: int
    category_counts: dict[NeedsReviewCategory, int]
    severity_counts: dict[NeedsReviewSeverity, int]
    informational_unread_update_count: int
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None
    items: list[NeedsReviewItem] = Field(default_factory=list)
