import os

import pytest_asyncio
from sqlalchemy import text

os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "root")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "postgres")

from core.db import SCHEMA_NAME, SessionLocal


@pytest_asyncio.fixture
async def db_session():
    async with SessionLocal() as session:
        table_names = (
            await session.execute(
                text(
                    """
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = :schema
                      AND tablename <> 'alembic_version'
                    ORDER BY tablename
                    """
                ),
                {"schema": SCHEMA_NAME},
            )
        ).scalars().all()
        if table_names:
            qualified_tables = ", ".join(
                f'"{SCHEMA_NAME}"."{table_name}"' for table_name in table_names
            )
            await session.execute(
                text(f"TRUNCATE TABLE {qualified_tables} CASCADE")
            )
            await session.commit()
        yield session
