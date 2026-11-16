import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from core.pydantic import CustomBaseModel
from modules.reminders.schemas import GuardianPolicySource
from modules.student_updates.models import (
    StudentUpdateActorRole,
    StudentUpdateEventType,
    StudentUpdateNotificationType,
    StudentUpdateStatus,
    StudentUpdateTargetType,
)


UpdateTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
UpdateText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
]


class ClassroomTarget(CustomBaseModel):
    type: Literal["classroom"]


class StudentsTarget(CustomBaseModel):
    type: Literal["students"]
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def student_ids_must_be_unique(self):
        if len(self.student_ids) != len(set(self.student_ids)):
            raise ValueError("Each student may appear only once")
        return self


UpdateTarget = Annotated[
    ClassroomTarget | StudentsTarget,
    Field(discriminator="type"),
]


class StudentUpdateCreateRequest(CustomBaseModel):
    classroom_id: uuid.UUID
    title: UpdateTitle
    body: UpdateText | None = None
    due_at: datetime | None = None
    requires_acknowledgement: bool = False
    allows_replies: bool = True
    target: UpdateTarget

    @field_validator("body", mode="before")
    @classmethod
    def empty_body_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("due_at")
    @classmethod
    def due_at_must_have_timezone(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value

    @model_validator(mode="after")
    def acknowledgement_requires_deadline(self):
        if self.requires_acknowledgement and self.due_at is None:
            raise ValueError(
                "due_at is required when acknowledgement is required"
            )
        return self


class StudentUpdateAudiencePreviewRequest(CustomBaseModel):
    classroom_id: uuid.UUID
    target: UpdateTarget


class StudentUpdateAudiencePreviewResponse(CustomBaseModel):
    classroom_id: uuid.UUID
    target_type: StudentUpdateTargetType
    student_names: list[str]
    student_count: int
    unique_guardian_count: int


class StudentUpdateStatusRequest(CustomBaseModel):
    status: StudentUpdateStatus


class StudentUpdateMessageRequest(CustomBaseModel):
    content: UpdateText


class StudentUpdateEventResponse(CustomBaseModel):
    id: uuid.UUID
    recipient_id: uuid.UUID
    event_type: StudentUpdateEventType
    actor_workos_user_id: str
    actor_role: StudentUpdateActorRole
    content: str | None
    previous_status: StudentUpdateStatus | None
    new_status: StudentUpdateStatus | None
    created_at: datetime


class GuardianUpdateEventResponse(CustomBaseModel):
    id: uuid.UUID
    recipient_id: uuid.UUID
    event_type: StudentUpdateEventType
    actor_role: StudentUpdateActorRole
    author_label: str
    content: str | None
    previous_status: StudentUpdateStatus | None
    new_status: StudentUpdateStatus | None
    created_at: datetime


class StudentUpdateRecipientResponse(CustomBaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    class_enrollment_id: uuid.UUID
    first_name: str
    last_name: str
    status: StudentUpdateStatus
    acknowledged_at: datetime | None
    completed_at: datetime | None
    is_overdue: bool
    created_at: datetime
    updated_at: datetime


class StudentUpdateResponse(CustomBaseModel):
    id: uuid.UUID
    organization_id: str
    classroom_id: uuid.UUID
    classroom_name: str
    teacher_workos_user_id: str
    target_type: StudentUpdateTargetType
    title: str
    body: str | None
    due_at: datetime | None
    requires_acknowledgement: bool
    allows_replies: bool
    recipient_count: int
    recipients: list[StudentUpdateRecipientResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class GuardianFeedItemResponse(CustomBaseModel):
    recipient_id: uuid.UUID
    update_id: uuid.UUID
    student_id: uuid.UUID
    student_first_name: str
    student_last_name: str
    classroom_id: uuid.UUID
    classroom_name: str
    target_type: StudentUpdateTargetType
    author_label: str
    title: str
    body: str | None
    due_at: datetime | None
    requires_acknowledgement: bool
    allows_replies: bool
    status: StudentUpdateStatus
    is_overdue: bool
    read_at: datetime | None
    acknowledged_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GuardianUpdateDetailResponse(GuardianFeedItemResponse):
    history: list[GuardianUpdateEventResponse] = Field(default_factory=list)


class StudentUpdateNotificationResponse(CustomBaseModel):
    id: uuid.UUID
    recipient_id: uuid.UUID
    event_id: uuid.UUID
    notification_type: StudentUpdateNotificationType
    student_id: uuid.UUID
    student_first_name: str
    student_last_name: str
    update_id: uuid.UUID
    update_title: str
    message: str | None = None
    policy_sources: list[GuardianPolicySource] = Field(default_factory=list)
    read_at: datetime | None
    created_at: datetime


class AdminStudentUpdateItemResponse(CustomBaseModel):
    recipient_id: uuid.UUID
    update_id: uuid.UUID
    classroom_id: uuid.UUID
    classroom_name: str
    student_id: uuid.UUID
    student_first_name: str
    student_last_name: str
    teacher_workos_user_id: str
    title: str
    due_at: datetime | None
    requires_acknowledgement: bool
    status: StudentUpdateStatus
    is_overdue: bool
    created_at: datetime
    updated_at: datetime


class AdminStudentUpdateSummaryResponse(CustomBaseModel):
    assigned: int
    acknowledged: int
    completed: int
    overdue: int
    unread_notifications: int
