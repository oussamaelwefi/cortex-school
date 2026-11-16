import uuid

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, SCHEMA_NAME, TimestampMixin, uuid_pk


class TutorBook(Base, TimestampMixin):
    __table_args__ = (UniqueConstraint("organization_id", "sha256", name="uq_tutorbook_school_hash"),)

    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.school.organization_id", ondelete="CASCADE"), index=True,
    )
    title: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    pdf: Mapped[bytes] = mapped_column(LargeBinary)
    page_count: Mapped[int]
    indexed_page_count: Mapped[int]


class TutorPassage(Base):
    __table_args__ = (
        UniqueConstraint("book_id", "page", "position", name="uq_tutorpassage_page_position"),
        CheckConstraint("page > 0 AND position >= 0", name="ck_tutorpassage_page_position"),
        Index("ix_tutorpassage_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[uuid_pk]
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA_NAME}.tutorbook.id", ondelete="CASCADE"))
    page: Mapped[int]
    position: Mapped[int]
    excerpt: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, search_text)", persisted=True),
    )
