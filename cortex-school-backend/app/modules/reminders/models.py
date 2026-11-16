import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Computed, DateTime, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, SCHEMA_NAME, TimestampMixin, uuid_pk


class SchoolPolicyFile(Base, TimestampMixin):
    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[bytes] = mapped_column(LargeBinary)


class SchoolPolicyPassage(Base, TimestampMixin):
    __table_args__ = (
        Index("ix_schoolpolicypassage_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[uuid_pk]
    document_id: Mapped[uuid.UUID] = mapped_column(index=True)
    organization_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(200))
    heading: Mapped[str] = mapped_column(String(150))
    excerpt: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, search_text)", persisted=True)
    )


class ReminderProposal(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint("update_id", name="uq_reminderproposal_update"),
        CheckConstraint("status IN ('draft', 'queued', 'completed')", name="ck_reminderproposal_status"),
        Index("ix_reminderproposal_queue", "status", "approved_at"),
    )

    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(String(255))
    update_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.studentupdate.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(16), default="draft")
    draft_message: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[dict]] = mapped_column(JSONB)
    approved_message: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReminderDelivery(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint("proposal_id", "guardian_id", name="uq_reminderdelivery_proposal_guardian"),
        CheckConstraint(
            "status IN ('pending', 'sent', 'skipped', 'failed')", name="ck_reminderdelivery_status"
        ),
    )

    id: Mapped[uuid_pk]
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.reminderproposal.id", ondelete="CASCADE")
    )
    guardian_id: Mapped[str] = mapped_column(String(255))
    guardian_name: Mapped[str | None] = mapped_column(String(255))
    students: Mapped[list[dict]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    outcome_reason: Mapped[str | None] = mapped_column(String(255))
