from datetime import timedelta

import pytest
from sqlalchemy import func, select

from core.db import utcnow
from modules.publications import services
from modules.publications.models import PublicationRecipient, SchoolPublication
from scripts import import_historical_publication as importer
from test_publications import ORG, seed


async def prepare(session, monkeypatch):
    seeded = await seed(session, monkeypatch)
    seeded["members"][ORG].append(
        {
            "id": "user_Admin",
            "name": "Administration",
            "roles": ["school_admin"],
            "status": "active",
        }
    )
    return seeded


@pytest.mark.asyncio
async def test_historical_import_preview_is_read_only(db_session, monkeypatch):
    await prepare(db_session, monkeypatch)
    result = await importer.import_publication(
        db_session, organization_id=ORG, published_at=utcnow() - timedelta(days=1)
    )
    assert result["status"] == "preview"
    assert result["recipient_count"] == 3
    assert (
        await db_session.scalar(select(func.count()).select_from(SchoolPublication))
        == 0
    )


@pytest.mark.asyncio
async def test_historical_import_persists_date_and_recipients_once(
    db_session, monkeypatch
):
    await prepare(db_session, monkeypatch)
    published_at = utcnow() - timedelta(days=1)
    result = await importer.import_publication(
        db_session, organization_id=ORG, published_at=published_at, apply=True
    )
    assert result["status"] == "imported"
    repeated = await importer.import_publication(
        db_session, organization_id=ORG, published_at=published_at, apply=True
    )
    assert repeated["status"] == "already_imported"
    assert repeated["publication_id"] == result["publication_id"]
    publication = await db_session.scalar(select(SchoolPublication))
    assert publication.created_at == published_at
    assert publication.author_user_id == "user_Admin"
    assert publication.recipient_count == 3
    recipients = (await db_session.scalars(select(PublicationRecipient))).all()
    assert {item.user_id for item in recipients} == {
        "user_GuardianA",
        "user_GuardianB",
        "user_TeacherA",
    }
    assert all(
        item.created_at == published_at and item.read_at is None for item in recipients
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(SchoolPublication))
        == 1
    )


@pytest.mark.asyncio
async def test_import_refuses_ambiguous_school_and_non_admin_author(
    db_session, monkeypatch
):
    await prepare(db_session, monkeypatch)
    with pytest.raises(ValueError, match="organization-id"):
        await importer.import_publication(db_session)
    with pytest.raises(ValueError, match="administrateur actif"):
        await importer.import_publication(
            db_session, organization_id=ORG, author_id="user_TeacherA"
        )
    assert (
        await db_session.scalar(select(func.count()).select_from(SchoolPublication))
        == 0
    )


@pytest.mark.asyncio
async def test_import_rolls_back_the_publication_if_receipt_insertion_fails(
    db_session, monkeypatch
):
    await prepare(db_session, monkeypatch)
    resolve = services._resolve_audience

    async def duplicate_recipient(*args):
        recipients, missing, fingerprint = await resolve(*args)
        return [*recipients, recipients[0]], missing, fingerprint

    monkeypatch.setattr(services, "_resolve_audience", duplicate_recipient)
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await importer.import_publication(
            db_session,
            organization_id=ORG,
            published_at=utcnow() - timedelta(days=1),
            apply=True,
        )
    assert (
        await db_session.scalar(select(func.count()).select_from(SchoolPublication))
        == 0
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(PublicationRecipient))
        == 0
    )
