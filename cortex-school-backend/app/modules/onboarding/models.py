from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, SCHEMA_NAME, TimestampMixin, uuid_pk


class SchoolRequestStatus(StrEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    FAILED = "failed"
    APPROVED = "approved"
    REJECTED = "rejected"


class SchoolRequest(TimestampMixin, Base):
    __table_args__ = (
        CheckConstraint("status IN ('pending','provisioning','failed','approved','rejected')", name="ck_schoolrequest_status"),
        Index("uq_schoolrequest_open_requester", "requester_user_id", unique=True,
              postgresql_where=text("status IN ('pending','provisioning','failed')")),
        Index("ix_schoolrequest_status_created", "status", "created_at"),
    )

    id: Mapped[uuid_pk]
    requester_user_id: Mapped[str] = mapped_column(String(255), index=True)
    requester_email: Mapped[str] = mapped_column(String(255))
    requester_name: Mapped[str] = mapped_column(String(255))
    school_name: Mapped[str] = mapped_column(String(255))
    country_code: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA_NAME}.country.code", ondelete="RESTRICT"))
    timezone: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=SchoolRequestStatus.PENDING)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    organization_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    membership_id: Mapped[str | None] = mapped_column(String(255))
    attempt_count: Mapped[int] = mapped_column(default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
