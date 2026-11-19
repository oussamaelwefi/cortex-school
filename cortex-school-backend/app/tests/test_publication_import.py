from datetime import datetime, timedelta
import uuid

import pytest
from sqlalchemy import func, select

from core.db import utcnow
from modules.publications import services
from modules.publications.models import PublicationRecipient, SchoolPublication
from scripts import import_historical_publication as importer
from test_publications import ORG, seed


def acknowledgement_options():
    return {
        "organization_id": ORG,
        "published_at": utcnow() - timedelta(days=1),
        "require_acknowledgement": True,
        "due_at": utcnow() - timedelta(hours=2),
    }


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


@pytest.mark.asyncio
async def test_acknowledgement_preview_is_read_only(db_session, monkeypatch):
    from modules.student_updates.models import StudentUpdate

    await prepare(db_session, monkeypatch)
    result = await importer.import_publication(db_session, **acknowledgement_options())
    assert result["status"] == "preview"
    assert result["module"] == "student_updates"
    assert result["requires_acknowledgement"] is True and result["overdue"] is True
    assert result["student_count"] == 2 and result["guardian_count"] == 2
    assert result["teacher_user_id"] == "user_TeacherA"
    assert "accuser réception" in result["body"]
    assert await db_session.scalar(select(func.count()).select_from(StudentUpdate)) == 0
    assert (
        await db_session.scalar(select(func.count()).select_from(SchoolPublication))
        == 0
    )


@pytest.mark.asyncio
async def test_overdue_import_enables_guardian_acknowledgement_and_admin_reminder_review(
    db_session, monkeypatch
):
    import httpx
    from main import app
    from modules.student_updates.models import (
        GuardianUpdateState,
        StudentUpdate,
        StudentUpdateEvent,
        StudentUpdateNotification,
        StudentUpdateRecipient,
    )
    from modules.reminders.models import ReminderProposal
    from test_publications import headers

    await prepare(db_session, monkeypatch)
    options = acknowledgement_options()
    result = await importer.import_publication(db_session, **options, apply=True)
    update_id = uuid.UUID(result["student_update_id"])
    notice = await db_session.get(StudentUpdate, update_id)
    assert notice.requires_acknowledgement is True and notice.allows_replies is True
    assert notice.due_at == options["due_at"] < utcnow()
    assert notice.created_at == options["published_at"]
    assert notice.teacher_workos_user_id == "user_TeacherA"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(StudentUpdateRecipient)
        )
        == 2
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(GuardianUpdateState))
        == 3
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(StudentUpdateNotification)
        )
        == 3
    )
    assert all(
        event.actor_role == "admin" and event.actor_workos_user_id == "user_Admin"
        for event in (await db_session.scalars(select(StudentUpdateEvent))).all()
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(SchoolPublication))
        == 0
    )
    await db_session.rollback()

    async def guardian_membership(*args):
        return None

    monkeypatch.setattr(
        "modules.student_registration.services._require_active_guardian",
        guardian_membership,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        review = await client.get(
            f"/api/student-updates/{update_id}/reminder", headers=headers()
        )
        assert review.status_code == 200, review.text
        assert review.json()["needs_reminder"] is True
        assert review.json()["pending_guardian_count"] >= 2
        assert review.json()["proposal"] is None
        queue = await client.get(
            "/api/needs-review/?category=acknowledgement", headers=headers()
        )
        assert queue.status_code == 200, queue.text
        assert any(
            item["action"]["update_id"] == str(update_id)
            for item in queue.json()["items"]
        )
        family = headers(user="GuardianA", role="guardian")
        feed = await client.get("/api/guardian/feed/", headers=family)
        assert feed.status_code == 200, feed.text
        items = [item for item in feed.json() if item["update_id"] == str(update_id)]
        assert len(items) == 2 and all(
            item["requires_acknowledgement"] and item["is_overdue"] for item in items
        )
        recipient_id = items[0]["recipient_id"]
        read = await client.post(
            f"/api/guardian/updates/{recipient_id}/read/", headers=family
        )
        assert read.json()["read_at"] and read.json()["acknowledged_at"] is None
        ack = await client.post(
            f"/api/guardian/updates/{recipient_id}/acknowledge/", headers=family
        )
        assert ack.status_code == 200 and ack.json()["acknowledged_at"]
    repeated = await importer.import_publication(db_session, **options, apply=True)
    assert repeated["status"] == "already_imported" and repeated[
        "student_update_id"
    ] == str(update_id)
    state = await db_session.scalar(
        select(GuardianUpdateState).where(
            GuardianUpdateState.recipient_id == uuid.UUID(recipient_id),
            GuardianUpdateState.guardian_workos_user_id == "user_GuardianA",
        )
    )
    assert state.acknowledged_at == datetime.fromisoformat(
        ack.json()["acknowledged_at"].replace("Z", "+00:00")
    )
    assert await db_session.scalar(select(func.count()).select_from(StudentUpdate)) == 1
    assert (
        await db_session.scalar(
            select(func.count()).select_from(StudentUpdateNotification)
        )
        == 3
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(ReminderProposal)) == 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ["future", "before_publication", "naive", "foreign_teacher", "unassigned_teacher"],
)
async def test_acknowledgement_import_rejects_invalid_dates_and_teacher_scope(
    db_session, monkeypatch, case
):
    from modules.student_updates.models import StudentUpdate

    await prepare(db_session, monkeypatch)
    options = acknowledgement_options()
    if case == "future":
        options["due_at"] = utcnow() + timedelta(hours=1)
    elif case == "before_publication":
        options["due_at"] = options["published_at"] - timedelta(hours=1)
    elif case == "naive":
        options["due_at"] = options["due_at"].replace(tzinfo=None)
    elif case == "foreign_teacher":
        options["teacher_id"] = "user_Foreign"
    else:
        options["teacher_id"] = "user_TeacherB"
    with pytest.raises(ValueError):
        await importer.import_publication(db_session, **options, apply=True)
    assert await db_session.scalar(select(func.count()).select_from(StudentUpdate)) == 0
    assert (
        await db_session.scalar(select(func.count()).select_from(SchoolPublication))
        == 0
    )


@pytest.mark.asyncio
async def test_acknowledgement_import_is_atomic_if_family_state_creation_fails(
    db_session, monkeypatch
):
    from modules.student_updates.models import (
        GuardianUpdateState,
        StudentUpdate,
        StudentUpdateEvent,
        StudentUpdateNotification,
        StudentUpdateRecipient,
    )

    await prepare(db_session, monkeypatch)
    original_flush = db_session.flush

    async def flush(*args, **kwargs):
        if any(isinstance(item, GuardianUpdateState) for item in db_session.new):
            raise RuntimeError("simulated receipt failure")
        await original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", flush)
    with pytest.raises(RuntimeError, match="simulated receipt failure"):
        await importer.import_publication(
            db_session, **acknowledgement_options(), apply=True
        )
    for model in (
        StudentUpdate,
        StudentUpdateRecipient,
        StudentUpdateEvent,
        GuardianUpdateState,
        StudentUpdateNotification,
    ):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
