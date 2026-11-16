import uuid
from datetime import datetime

from pydantic import EmailStr

from core.pydantic import CustomBaseModel
from modules.invitations.models import InvitationSendStatus, UserRoles


class InvitationResponse(CustomBaseModel):
    id: uuid.UUID
    organization_id: str
    created_by_user_id: str | None
    email: str
    first_name: str | None
    last_name: str | None
    role_slug: UserRoles | None
    expires_in_days: int
    send_status: InvitationSendStatus
    celery_task_id: str | None
    workos_invitation_id: str | None
    workos_state: str | None
    expires_at: datetime | None
    attempt_count: int
    error_message: str | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvitationUploadResponse(CustomBaseModel):
    created_count: int
    updated_count: int
    queued_count: int
    failed_count: int
    skipped_count: int
    invitations: list[InvitationResponse]


class InvitationCreateRequest(CustomBaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    role_slug: UserRoles = UserRoles.GUARDIAN
