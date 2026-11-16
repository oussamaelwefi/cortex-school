from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, TimestampMixin, create_sql_enum, uuid_pk


class UserRoles(StrEnum):
    SCHOOL_ADMIN = "school_admin"
    TEACHER = "teacher"
    GUARDIAN = "guardian"


class InvitationSendStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class Invitation(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_invitation_email"),
        Index(
            "ix_invitation_org_status_state_expiry",
            "organization_id",
            "send_status",
            "workos_state",
            "expires_at",
        ),
    )

    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_slug: Mapped[UserRoles | None] = mapped_column(
        create_sql_enum(UserRoles, "user_roles_enum"), nullable=True
    )
    expires_in_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    send_status: Mapped[InvitationSendStatus] = mapped_column(
        String(32), default=InvitationSendStatus.PENDING, nullable=False
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workos_invitation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workos_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
