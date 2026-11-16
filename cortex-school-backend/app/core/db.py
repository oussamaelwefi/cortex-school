import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, AsyncGenerator

from sqlalchemy import DateTime, Enum as SQLAEnum, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from core.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_sql_enum(enum_type: type[Enum], name: str | None = None) -> SQLAEnum:
    def get_enum_values(enum_class: type[Enum]) -> list[str]:
        return [member.value for member in enum_class]

    if name is None:
        name = enum_type.__name__.lower()
    name = name[:63]

    return SQLAEnum(
        enum_type,
        values_callable=get_enum_values,
        name=name,
        inherit_schema=True,
    )


SCHEMA_NAME = settings.database.SCHEMA_NAME
DATABASE_URI = settings.database.DATABASE_URI


class Base(DeclarativeBase):
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower()

    metadata = MetaData(
        schema=SCHEMA_NAME,
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


engine: AsyncEngine = create_async_engine(DATABASE_URI, echo=False)
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def close_db_connections():
    await engine.dispose()


uuid_pk = Annotated[
    uuid.UUID,
    mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
