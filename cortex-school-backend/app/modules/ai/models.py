import uuid
from datetime import datetime

from core.db import SCHEMA_NAME, Base, TimestampMixin, utcnow, uuid_pk
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class GuardianChatPreference(Base, TimestampMixin):
    """School-scoped AI consent, separate from access to normal school screens."""

    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.school.organization_id", ondelete="CASCADE"),
        primary_key=True,
    )
    guardian_user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    data_enabled: Mapped[bool] = mapped_column(
        default=True,
        server_default="true",
        nullable=False,
    )


class ChatConversation(Base, TimestampMixin):
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'teacher', 'guardian')", name="ck_chatconversation_role"),
        UniqueConstraint(
            "organization_id", "user_id", "role", "initial_request_id",
            name="uq_chatconversation_initial_request",
        ),
        Index("ix_chatconversation_owner_activity", "organization_id", "user_id", "role", "updated_at", "id"),
    )

    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.school.organization_id", ondelete="CASCADE"),
    )
    user_id: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    initial_request_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(100))
    next_turn: Mapped[int] = mapped_column(default=1)


class ChatMessage(Base):
    __table_args__ = (
        CheckConstraint("sender IN ('user', 'assistant')", name="ck_chatmessage_sender"),
        UniqueConstraint("conversation_id", "turn", "sender", name="uq_chatmessage_turn_sender"),
        UniqueConstraint("conversation_id", "request_id", "sender", name="uq_chatmessage_request_sender"),
    )

    id: Mapped[uuid_pk]
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.chatconversation.id", ondelete="CASCADE"),
    )
    turn: Mapped[int]
    request_id: Mapped[uuid.UUID]
    sender: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    school_data_revision: Mapped[int | None]
    lookups: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
