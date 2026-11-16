import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


def required_text(max_length: int):
    return StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)


class SchoolPolicyCreate(BaseModel):
    title: Annotated[str, required_text(200)]
    text: Annotated[str, required_text(16000)]


class SchoolPolicyResponse(BaseModel):
    id: uuid.UUID
    title: str
    passage_count: int
    has_pdf: bool = False


class SchoolPolicyFileResponse(BaseModel):
    id: uuid.UUID
    title: str


class PolicySource(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    title: str
    heading: str
    excerpt: str


class GuardianPolicySource(PolicySource):
    has_pdf: bool


class ReminderDraft(BaseModel):
    message: Annotated[str, required_text(1200)] | None
    source_ids: Annotated[list[uuid.UUID], Field(max_length=3)]


class ReminderPreparation(BaseModel):
    message: Annotated[str, required_text(1200)] | None = None


class ReminderApproval(BaseModel):
    message: Annotated[str, required_text(1200)]
    include_policy_sources: bool = True


class ReminderStudent(BaseModel):
    recipient_id: uuid.UUID
    name: str


class ReminderRecipient(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    guardian_id: str
    guardian_name: str | None
    students: list[ReminderStudent]
    status: Literal["pending", "sent", "skipped", "failed"]
    outcome_reason: str | None


class ReminderProposalResponse(BaseModel):
    id: uuid.UUID
    status: Literal["draft", "queued", "completed"]
    message: str
    sources: list[PolicySource]
    recipients: list[ReminderRecipient]
    approved_at: datetime | None
    completed_at: datetime | None


class ReminderReviewResponse(BaseModel):
    update_id: uuid.UUID
    title: str
    due_at: datetime | None
    needs_reminder: bool
    pending_guardian_count: int
    proposal: ReminderProposalResponse | None
