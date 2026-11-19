import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, SCHEMA_NAME, TimestampMixin, uuid_pk


class SchoolPublication(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "author_user_id",
            "idempotency_key",
            name="uq_publication_author_attempt",
        ),
        CheckConstraint(
            "target_kind IN ('classrooms','guardians','teachers','students')",
            name="ck_publication_target_kind",
        ),
        Index("ix_publication_org_created", "organization_id", "created_at"),
    )
    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.school.organization_id", ondelete="RESTRICT"),
        nullable=False,
    )
    author_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    target_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_ids: Mapped[list[str]] = mapped_column(ARRAY(String(255)), nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False)


class PublicationRecipient(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint(
            "publication_id", "user_id", name="uq_publication_recipient_user"
        ),
        Index("ix_publication_recipient_inbox", "user_id", "publication_id"),
    )
    id: Mapped[uuid_pk]
    publication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.schoolpublication.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False)
    student_ids: Mapped[list[str]] = mapped_column(ARRAY(String(36)), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
