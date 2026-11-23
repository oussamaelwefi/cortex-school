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


class TutorClassBook(Base, TimestampMixin):
    __table_args__ = (UniqueConstraint("organization_id", "sha256", name="uq_tutor_class_book_school_hash"),)

    id: Mapped[uuid_pk]
    organization_id: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA_NAME}.school.organization_id", ondelete="CASCADE"))
    sha256: Mapped[str] = mapped_column(String(64))
    pdf: Mapped[bytes] = mapped_column(LargeBinary)
    page_count: Mapped[int]
    indexed_page_count: Mapped[int]


class TutorClassMaterial(Base, TimestampMixin):
    __table_args__ = (
        UniqueConstraint("classroom_id", "book_id", name="uq_tutor_class_material_class_book"),
        CheckConstraint("grade_level BETWEEN 1 AND 13", name="ck_tutor_class_material_grade"),
    )

    id: Mapped[uuid_pk]
    classroom_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.classroom.id", ondelete="CASCADE"),
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_NAME}.tutorclassbook.id", ondelete="CASCADE"), index=True,
    )
    title: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(100))
    grade_level: Mapped[int | None]
    published_by: Mapped[str] = mapped_column(String(255))


class IndexedPassage:
    id: Mapped[uuid_pk]
    page: Mapped[int]
    position: Mapped[int]
    excerpt: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, search_text)", persisted=True),
    )


class TutorPassage(IndexedPassage, Base):
    __table_args__ = (
        UniqueConstraint("book_id", "page", "position", name="uq_tutorpassage_page_position"),
        CheckConstraint("page > 0 AND position >= 0", name="ck_tutorpassage_page_position"),
        Index("ix_tutorpassage_search_vector", "search_vector", postgresql_using="gin"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA_NAME}.tutorbook.id", ondelete="CASCADE"))


class TutorClassPassage(IndexedPassage, Base):
    __table_args__ = (
        UniqueConstraint("book_id", "page", "position", name="uq_tutorclasspassage_page_position"),
        CheckConstraint("page > 0 AND position >= 0", name="ck_tutorclasspassage_page_position"),
        Index("ix_tutorclasspassage_search_vector", "search_vector", postgresql_using="gin"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA_NAME}.tutorclassbook.id", ondelete="CASCADE"))
