"""CSV role selection, atomic validation, and queue handoff (no real mail)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.auth import get_current_user
from core.db import db_session as session_dependency
from modules.invitations import router as invitation_router
from modules.invitations.models import (
    Invitation,
    InvitationCsvRoleMode,
    InvitationSendStatus,
    UserRoles,
)
from modules.invitations.services import (
    InvitationCsvError,
    _send_workos_invitation,
    enqueue_invitation,
    parse_invitation_csv,
)
from core.config import settings


FIXED_MODES = [mode for mode in InvitationCsvRoleMode if mode != InvitationCsvRoleMode.MIXED]


@pytest.mark.parametrize("mode", FIXED_MODES)
@pytest.mark.parametrize("column", ["", ",role_slug"])
def test_fixed_modes_apply_to_every_row_and_ignore_role_column(mode, column):
    csv = f"email,first_name{column}\nFIRST@example.com,First"
    csv += ",not_a_role" if column else ""
    csv += "\nsecond@example.com,Second"
    csv += ",school_admin" if column else ""
    rows = parse_invitation_csv(csv, role_mode=mode)
    assert [row.role_slug for row in rows] == [UserRoles(mode)] * 2
    assert rows[0].email == "first@example.com"
    assert rows[0].first_name == "First"


def test_mixed_reads_each_role_and_normalizes_headers():
    rows = parse_invitation_csv(
        " Email , Role_Slug \nadmin@example.com,school_admin\n"
        "teacher@example.com,teacher\nparent@example.com,guardian\n",
        role_mode=InvitationCsvRoleMode.MIXED,
    )
    assert [row.role_slug for row in rows] == list(UserRoles)


@pytest.mark.parametrize("csv, error", [
    ("email\nparent@example.com\n", "require a role_slug column"),
    ("email,role_slug\nparent@example.com,\n", "Row 2 must include a role_slug"),
    ("email,role_slug\nparent@example.com,admin\n", "Row 2 has an invalid role_slug"),
])
def test_mixed_rejects_missing_or_invalid_roles(csv, error):
    with pytest.raises(InvitationCsvError, match=error):
        parse_invitation_csv(csv, role_mode=InvitationCsvRoleMode.MIXED)


@pytest_asyncio.fixture
async def upload_client(db_session, monkeypatch):
    app = FastAPI()
    app.include_router(invitation_router.router)
    user = {"user_id": "user_admin", "organization_id": "org_import_test",
            "claims": {"permissions": ["school:manage"]}}
    app.dependency_overrides[get_current_user] = lambda: user

    async def session_override():
        yield db_session

    app.dependency_overrides[session_dependency] = session_override
    queued = []

    async def fake_enqueue(session, invitation):
        queued.append((invitation.email, invitation.role_slug))
        return await enqueue_invitation(session, invitation, f"test-task-{len(queued)}")

    monkeypatch.setattr(invitation_router, "enqueue_invitation_task", fake_enqueue)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, session=db_session, queued=queued, user=user)


async def upload(context, csv, mode="mixed"):
    return await context.client.post(
        "/invitations/upload/", params={"role_mode": mode},
        files={"file": ("people.csv", csv.encode("utf-8-sig"), "text/csv")},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [*FIXED_MODES, InvitationCsvRoleMode.MIXED])
async def test_api_saves_and_queues_the_selected_roles(upload_client, mode):
    csv = "email,role_slug\nadmin@example.com,school_admin\nteacher@example.com,teacher\nparent@example.com,guardian\n"
    response = await upload(upload_client, csv, mode)
    assert response.status_code == 202, response.text
    data = response.json()
    roles = list(UserRoles) if mode == InvitationCsvRoleMode.MIXED else [UserRoles(mode)] * 3
    assert [row[1] for row in upload_client.queued] == roles
    assert [row["role_slug"] for row in data["invitations"]] == roles
    assert {row["organization_id"] for row in data["invitations"]} == {"org_import_test"}
    assert {row["send_status"] for row in data["invitations"]} == {"queued"}
    assert data["created_count"] == data["queued_count"] == 3
    assert data["failed_count"] == data["skipped_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_row", ["invalid-email,guardian", "other@example.com,", "other@example.com,admin", "good@example.com,teacher"])
async def test_invalid_batch_saves_and_queues_nothing(upload_client, bad_row):
    response = await upload(upload_client, f"email,role_slug\ngood@example.com,teacher\n{bad_row}\n")
    assert response.status_code == 400
    assert upload_client.queued == []
    assert (await upload_client.session.scalars(select(Invitation))).all() == []


@pytest.mark.asyncio
async def test_api_mixed_default_requires_role_column(upload_client):
    response = await upload_client.client.post(
        "/invitations/upload/", files={"file": ("people.csv", b"email\nperson@example.com\n", "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Mixed imports require a role_slug column."
    assert upload_client.queued == []


@pytest.mark.asyncio
async def test_unknown_mode_and_non_admin_cannot_queue(upload_client):
    assert (await upload(upload_client, "email\nperson@example.com\n", "admin")).status_code == 422
    upload_client.user["claims"]["permissions"] = []
    assert (await upload(upload_client, "email\nperson@example.com\n", "school_admin")).status_code == 403
    assert upload_client.queued == []


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [InvitationSendStatus.QUEUED, InvitationSendStatus.PROCESSING, InvitationSendStatus.SENT])
async def test_queued_or_sent_role_conflicts_reject_entire_batch(upload_client, state):
    invitation = Invitation(organization_id="org_import_test", email="existing@example.com",
                            first_name="Original", role_slug=UserRoles.TEACHER, send_status=state)
    upload_client.session.add(invitation)
    await upload_client.session.commit()
    response = await upload(upload_client, "email,first_name\nnew@example.com,New\nexisting@example.com,Changed\n", "guardian")
    assert response.status_code == 400
    assert "different role" in response.json()["detail"]
    assert upload_client.queued == []
    await upload_client.session.refresh(invitation)
    assert invitation.role_slug == UserRoles.TEACHER
    assert invitation.first_name == "Original"
    assert len((await upload_client.session.scalars(select(Invitation))).all()) == 1


@pytest.mark.asyncio
async def test_same_role_is_skipped_and_failed_role_can_be_corrected(upload_client):
    existing = Invitation(organization_id="org_import_test", email="sent@example.com",
                          role_slug=UserRoles.GUARDIAN, first_name="Original", send_status=InvitationSendStatus.SENT)
    retry = Invitation(organization_id="org_import_test", email="retry@example.com",
                       role_slug=UserRoles.TEACHER, send_status=InvitationSendStatus.FAILED)
    foreign = Invitation(organization_id="org_other", email="new@example.com",
                         role_slug=UserRoles.SCHOOL_ADMIN, send_status=InvitationSendStatus.SENT)
    upload_client.session.add_all([existing, retry, foreign])
    await upload_client.session.commit()
    response = await upload(upload_client, "email,first_name\nsent@example.com,Changed\nretry@example.com,Retry\nnew@example.com,New\n", "guardian")
    assert response.status_code == 202, response.text
    assert response.json()["skipped_count"] == 1
    assert response.json()["queued_count"] == 2
    assert response.json()["updated_count"] == 1
    assert response.json()["created_count"] == 1
    await upload_client.session.refresh(existing)
    await upload_client.session.refresh(foreign)
    assert existing.first_name == "Original"
    assert foreign.role_slug == UserRoles.SCHOOL_ADMIN
    assert upload_client.queued == [("retry@example.com", UserRoles.GUARDIAN), ("new@example.com", UserRoles.GUARDIAN)]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRoles))
async def test_workos_receives_each_exact_school_role(role):
    invitation = SimpleNamespace(email="person@example.com", organization_id="org_import_test", role_slug=role, expires_in_days=7)
    client = AsyncMock()
    with patch.object(settings, "WORKOS_API_KEY", "test-key"), patch("modules.invitations.services.AsyncWorkOSClient") as factory:
        factory.return_value.__aenter__.return_value = client
        await _send_workos_invitation(invitation)
    assert client.user_management.send_invitation.call_args.kwargs["role_slug"] == role.value
