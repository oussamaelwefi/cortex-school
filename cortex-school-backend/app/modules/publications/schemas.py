import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, StringConstraints, model_validator
from typing_extensions import Annotated

from core.pydantic import CustomBaseModel


class PublicationTarget(CustomBaseModel):
    kind: Literal["classrooms", "guardians", "teachers", "students"]
    ids: list[str] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_identifiers(self):
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("Choose each recipient only once")
        if self.kind in {"classrooms", "students"}:
            self.ids = [str(uuid.UUID(value)) for value in self.ids]
            if len(set(self.ids)) != len(self.ids):
                raise ValueError("Choose each recipient only once")
        elif any(
            not value.startswith("user_") or len(value) > 255 or not value[5:].isalnum()
            for value in self.ids
        ):
            raise ValueError("Invalid school member identifier")
        return self


class PublicationPreviewRequest(CustomBaseModel):
    target: PublicationTarget


class PublicationCreateRequest(PublicationPreviewRequest):
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    body: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
    ]
    audience_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    idempotency_key: uuid.UUID
    confirmed: Literal[True]


class PublicationOption(CustomBaseModel):
    id: str
    name: str


class PublicationAudienceOptions(CustomBaseModel):
    classrooms: list[PublicationOption]
    guardians: list[PublicationOption]
    teachers: list[PublicationOption]
    students: list[PublicationOption]


class PublicationPreviewRecipient(CustomBaseModel):
    id: str
    name: str
    roles: list[str]


class PublicationPreviewResponse(CustomBaseModel):
    audience_hash: str
    recipient_count: int
    guardian_count: int
    teacher_count: int
    recipients: list[PublicationPreviewRecipient]
    students_without_guardians: list[str]


class PublicationResponse(CustomBaseModel):
    id: uuid.UUID
    title: str
    body: str
    target_kind: str
    target_ids: list[str]
    recipient_count: int
    read_count: int
    created_at: datetime


class PublicationReceipt(PublicationPreviewRecipient):
    read_at: datetime | None


class PublicationDetailResponse(PublicationResponse):
    recipients: list[PublicationReceipt]


class PublicationListResponse(CustomBaseModel):
    items: list[PublicationResponse]
    total_count: int


class PublicationInboxItem(CustomBaseModel):
    id: uuid.UUID
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None


class PublicationInboxResponse(CustomBaseModel):
    items: list[PublicationInboxItem]
    total_count: int
    unread_count: int
