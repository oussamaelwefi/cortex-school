import asyncio
import uuid
from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from core.config import settings
from core.db import utcnow
from main import app
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.classrooms.models import (
    Classroom,
    ClassEnrollment,
    TeacherAssignment,
    TeacherAssignmentRole,
)
from modules.enrollments.models import Enrollment
from modules.publications import services
from modules.publications.models import PublicationRecipient, SchoolPublication
from modules.publications.schemas import PublicationCreateRequest, PublicationTarget
from modules.schools.models import Country, School
from modules.students.models import GuardianStudent, Student

ORG = "org_publications_a"
OTHER = "org_publications_b"


def headers(user="Admin", organization=ORG, role="school_admin"):
    return {"Authorization": f"Bearer user_{user}:{organization}:{role}"}


async def seed(session, monkeypatch):
    today = utcnow().astimezone(ZoneInfo("Africa/Tunis")).date()
    session.add(Country(code="TN", name="Tunisia", calling_code="+216"))
    await session.flush()
    session.add_all(
        [
            School(organization_id=organization, country_code="TN")
            for organization in (ORG, OTHER)
        ]
    )
    await session.flush()
    years = [
        AcademicYear(
            id=uuid.uuid4(),
            organization_id=organization,
            name="Current",
            starts_on=today - timedelta(days=90),
            ends_on=today + timedelta(days=90),
            status=AcademicYearStatus.ACTIVE,
        )
        for organization in (ORG, OTHER)
    ]
    session.add_all(years)
    await session.flush()
    classes = [
        Classroom(id=uuid.uuid4(), academic_year_id=years[0].id, name="6e A"),
        Classroom(id=uuid.uuid4(), academic_year_id=years[0].id, name="6e B"),
        Classroom(id=uuid.uuid4(), academic_year_id=years[1].id, name="Foreign class"),
    ]
    session.add_all(classes)
    children = [
        Student(
            id=uuid.uuid4(),
            organization_id=ORG if index < 3 else OTHER,
            first_name=name,
            last_name="Student",
        )
        for index, name in enumerate(("Yasmine", "Adam", "Former", "Foreign"))
    ]
    session.add_all(children)
    await session.flush()
    for index, child in enumerate(children):
        year = years[1] if index == 3 else years[0]
        enrollment = Enrollment(
            id=uuid.uuid4(), student_id=child.id, academic_year_id=year.id
        )
        session.add(enrollment)
        await session.flush()
        session.add(
            ClassEnrollment(
                classroom_id=classes[2].id if index == 3 else classes[0].id,
                enrollment_id=enrollment.id,
                effective_from=today - timedelta(days=30),
                effective_until=today if index == 2 else None,
            )
        )
    session.add_all(
        [
            GuardianStudent(
                student_id=children[0].id, guardian_workos_user_id="user_GuardianA"
            ),
            GuardianStudent(
                student_id=children[0].id, guardian_workos_user_id="user_GuardianB"
            ),
            GuardianStudent(
                student_id=children[1].id, guardian_workos_user_id="user_GuardianA"
            ),
            GuardianStudent(
                student_id=children[1].id, guardian_workos_user_id="user_Gone"
            ),
            GuardianStudent(
                student_id=children[2].id, guardian_workos_user_id="user_Former"
            ),
            GuardianStudent(
                student_id=children[3].id, guardian_workos_user_id="user_Foreign"
            ),
        ]
    )
    for classroom in classes[:2]:
        session.add(
            TeacherAssignment(
                classroom_id=classroom.id,
                teacher_workos_user_id="user_TeacherA",
                role=TeacherAssignmentRole.LEAD,
                effective_from=today - timedelta(days=20),
            )
        )
    session.add(
        TeacherAssignment(
            classroom_id=classes[0].id,
            teacher_workos_user_id="user_TeacherB",
            role=TeacherAssignmentRole.ASSISTANT,
            effective_from=today - timedelta(days=20),
            effective_until=today,
        )
    )
    await session.commit()
    members = {
        ORG: [
            {"id": f"user_{name}", "name": name, "roles": [role], "status": "active"}
            for name, role in (
                ("GuardianA", "guardian"),
                ("GuardianB", "guardian"),
                ("Former", "guardian"),
                ("TeacherA", "teacher"),
                ("TeacherB", "teacher"),
            )
        ],
        OTHER: [
            {
                "id": "user_Foreign",
                "name": "Foreign",
                "roles": ["guardian"],
                "status": "active",
            }
        ],
    }

    async def member_lookup(organization_id):
        return members[organization_id]

    async def viewer(current_user, role):
        user_id, organization_id = services._scope(current_user)
        if not any(
            item["id"] == user_id and role in item["roles"]
            for item in members.get(organization_id, [])
        ):
            raise HTTPException(
                403, "Active school membership is required for this inbox"
            )
        return user_id, organization_id

    def claims(token):
        user_id, organization_id, role = token.split(":")
        return {
            "sub": user_id,
            "org_id": organization_id,
            "roles": [role],
            "permissions": ["school:manage"] if role == "school_admin" else [],
        }

    monkeypatch.setattr(services, "_members", member_lookup)
    monkeypatch.setattr(services, "_active_viewer", viewer)
    monkeypatch.setattr("core.auth.verify_workos_access_token", claims)
    return {"classes": classes, "children": children, "members": members}


async def preview(client, kind, ids, auth=None):
    return await client.post(
        "/api/publications/preview/",
        headers=auth or headers(),
        json={"target": {"kind": kind, "ids": [str(value) for value in ids]}},
    )


async def publish(client, target, fingerprint, key=None, auth=None, **extra):
    return await client.post(
        "/api/publications/",
        headers=auth or headers(),
        json={
            "target": target,
            "title": "Réunion des familles",
            "body": "Une réunion est organisée à l’école.",
            "audience_hash": fingerprint,
            "idempotency_key": str(key or uuid.uuid4()),
            "confirmed": True,
            **extra,
        },
    )


def test_target_and_publication_contracts_reject_invalid_or_unconfirmed_requests():
    with pytest.raises(ValidationError):
        PublicationTarget(kind="students", ids=["not-a-uuid"])
    with pytest.raises(ValidationError):
        PublicationTarget(kind="guardians", ids=["user_A", "user_A"])
    with pytest.raises(ValidationError):
        PublicationTarget(kind="teachers", ids=[])
    with pytest.raises(ValidationError):
        PublicationCreateRequest(
            target={"kind": "guardians", "ids": ["user_A"]},
            title="Test",
            body="Message",
            audience_hash="a" * 64,
            idempotency_key=uuid.uuid4(),
            confirmed=False,
        )


@pytest.mark.asyncio
async def test_class_publication_reaches_families_and_current_teachers_once(
    db_session, monkeypatch
):
    seeded = await seed(db_session, monkeypatch)
    ids = [str(item.id) for item in seeded["classes"][:2]]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        options = (
            await client.get("/api/publications/audiences/", headers=headers())
        ).json()
        assert {item["name"] for item in options["classrooms"]} == {"6e A", "6e B"}
        result = (await preview(client, "classrooms", ids)).json()
        assert result["recipient_count"] == 3
        assert result["guardian_count"] == 2 and result["teacher_count"] == 1
        assert {item["id"] for item in result["recipients"]} == {
            "user_GuardianA",
            "user_GuardianB",
            "user_TeacherA",
        }
        assert (
            await db_session.scalar(select(func.count()).select_from(SchoolPublication))
            == 0
        )
        await db_session.rollback()
        created = await publish(
            client, {"kind": "classrooms", "ids": ids}, result["audience_hash"]
        )
        assert created.status_code == 201, created.text
        publication_id = created.json()["id"]
        for user, role, expected in (
            ("GuardianA", "guardian", 1),
            ("GuardianB", "guardian", 1),
            ("TeacherA", "teacher", 1),
            ("TeacherB", "teacher", 0),
            ("Former", "guardian", 0),
        ):
            inbox = await client.get(
                f"/api/publications/inbox/?role={role}",
                headers=headers(user=user, role=role),
            )
            assert inbox.status_code == 200, inbox.text
            assert inbox.json()["total_count"] == expected
        other = await client.get(
            "/api/publications/inbox/?role=guardian",
            headers=headers(user="Foreign", organization=OTHER, role="guardian"),
        )
        assert other.json()["items"] == []
        read = await client.post(
            f"/api/publications/inbox/{publication_id}/read/?role=guardian",
            headers=headers(user="GuardianA", role="guardian"),
        )
        assert read.status_code == 200 and read.json()["read_at"]
        again = await client.post(
            f"/api/publications/inbox/{publication_id}/read/?role=guardian",
            headers=headers(user="GuardianA", role="guardian"),
        )
        assert again.json()["read_at"] == read.json()["read_at"]
        unread = await client.get(
            "/api/publications/inbox/?role=guardian&unread_only=true",
            headers=headers(user="GuardianA", role="guardian"),
        )
        assert unread.json()["total_count"] == 0 and unread.json()["unread_count"] == 0
        detail = await client.get(
            f"/api/publications/{publication_id}/", headers=headers()
        )
        assert (
            detail.json()["read_count"] == 1 and len(detail.json()["recipients"]) == 3
        )
        assert (
            await client.get(
                f"/api/publications/{publication_id}/",
                headers=headers(organization=OTHER),
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/api/publications/inbox/{publication_id}/read/?role=guardian",
                headers=headers(user="Foreign", organization=OTHER, role="guardian"),
            )
        ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,ids,expected",
    [
        ("guardians", ["user_GuardianA"], {"user_GuardianA"}),
        ("teachers", ["user_TeacherB"], {"user_TeacherB"}),
        ("students", None, {"user_GuardianA", "user_GuardianB"}),
    ],
)
async def test_direct_targets_and_students_only_reach_the_intended_accounts(
    db_session, monkeypatch, kind, ids, expected
):
    seeded = await seed(db_session, monkeypatch)
    ids = ids or [str(seeded["children"][0].id)]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        audience = (await preview(client, kind, ids)).json()
        assert {item["id"] for item in audience["recipients"]} == expected
        response = await publish(
            client, {"kind": kind, "ids": ids}, audience["audience_hash"]
        )
        assert response.status_code == 201, response.text
        stored = (await db_session.scalars(select(PublicationRecipient))).all()
        assert {item.user_id for item in stored} == expected
        if kind == "students":
            assert all(
                item.roles == ["guardian"] and item.student_ids == ids
                for item in stored
            )


@pytest.mark.asyncio
async def test_idempotency_and_changed_audience_prevent_duplicate_or_unreviewed_delivery(
    db_session, monkeypatch
):
    seeded = await seed(db_session, monkeypatch)
    target = {"kind": "students", "ids": [str(seeded["children"][0].id)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        audience = (await preview(client, target["kind"], target["ids"])).json()
        key = uuid.uuid4()
        created, repeated = await asyncio.gather(
            publish(client, target, audience["audience_hash"], key),
            publish(client, target, audience["audience_hash"], key),
        )
        assert created.status_code == repeated.status_code == 201
        assert created.json()["id"] == repeated.json()["id"]
        assert (
            await publish(
                client, target, audience["audience_hash"], key, title="Changed title"
            )
        ).status_code == 409
        seeded["members"][ORG] = [
            item for item in seeded["members"][ORG] if item["id"] != "user_GuardianB"
        ]
        changed = await publish(client, target, audience["audience_hash"])
        assert changed.status_code == 409 and "recipients have changed" in changed.text
        assert (
            await db_session.scalar(select(func.count()).select_from(SchoolPublication))
            == 1
        )
        assert (
            await db_session.scalar(
                select(func.count()).select_from(PublicationRecipient)
            )
            == 2
        )


@pytest.mark.asyncio
async def test_cross_school_and_wrong_role_targets_are_rejected_without_writes(
    db_session, monkeypatch
):
    seeded = await seed(db_session, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for kind, ids in (
            ("classrooms", [seeded["classes"][2].id]),
            ("students", [seeded["children"][3].id]),
            ("guardians", ["user_Foreign"]),
            ("teachers", ["user_GuardianA"]),
        ):
            assert (await preview(client, kind, ids)).status_code == 422
        for user, role in (("TeacherA", "teacher"), ("GuardianA", "guardian")):
            auth = headers(user=user, role=role)
            assert (
                await client.get("/api/publications/", headers=auth)
            ).status_code == 403
            assert (
                await client.get("/api/publications/audiences/", headers=auth)
            ).status_code == 403
            assert (
                await preview(client, "guardians", ["user_GuardianA"], auth=auth)
            ).status_code == 403
            assert (
                await publish(
                    client,
                    {"kind": "guardians", "ids": ["user_GuardianA"]},
                    "a" * 64,
                    auth=auth,
                )
            ).status_code == 403
        assert (await client.get("/api/publications/")).status_code == 401
        assert (
            await db_session.scalar(select(func.count()).select_from(SchoolPublication))
            == 0
        )


@pytest.mark.asyncio
async def test_unlinked_guardians_lose_student_publications_but_keep_direct_messages(
    db_session, monkeypatch
):
    seeded = await seed(db_session, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        publications = []
        for target in (
            {"kind": "students", "ids": [str(seeded["children"][0].id)]},
            {"kind": "guardians", "ids": ["user_GuardianA"]},
        ):
            audience = (await preview(client, target["kind"], target["ids"])).json()
            publications.append(
                (await publish(client, target, audience["audience_hash"])).json()
            )
        await db_session.execute(
            delete(GuardianStudent).where(
                GuardianStudent.guardian_workos_user_id == "user_GuardianA",
                GuardianStudent.student_id == seeded["children"][0].id,
            )
        )
        await db_session.commit()
        auth = headers(user="GuardianA", role="guardian")
        inbox = (
            await client.get("/api/publications/inbox/?role=guardian", headers=auth)
        ).json()
        assert [item["id"] for item in inbox["items"]] == [publications[1]["id"]]
        assert (
            await client.post(
                f"/api/publications/inbox/{publications[0]['id']}/read/?role=guardian",
                headers=auth,
            )
        ).status_code == 404
        denied = await client.get("/api/publications/inbox/?role=teacher", headers=auth)
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_missing_guardians_are_reported_and_empty_audiences_do_not_publish(
    db_session, monkeypatch
):
    seeded = await seed(db_session, monkeypatch)
    await db_session.execute(
        delete(GuardianStudent).where(
            GuardianStudent.student_id == seeded["children"][1].id
        )
    )
    await db_session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        audience = await preview(client, "classrooms", [seeded["classes"][0].id])
        assert audience.json()["students_without_guardians"] == ["Adam Student"]
        empty = await preview(client, "students", [seeded["children"][1].id])
        assert empty.status_code == 422 and "No active recipients" in empty.text
        assert (
            await db_session.scalar(select(func.count()).select_from(SchoolPublication))
            == 0
        )


@pytest.mark.asyncio
async def test_recipient_lookup_failure_does_not_publish_or_bypass_membership(
    db_session, monkeypatch
):
    lookup = services._members
    await seed(db_session, monkeypatch)

    async def unavailable(organization_id):
        raise services.MemberLookupUnavailable("provider unavailable")

    monkeypatch.setattr(services, "_members", lookup)
    monkeypatch.setattr(services, "list_school_members", unavailable)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await preview(client, "guardians", ["user_GuardianA"])
        ).status_code == 503
        response = await publish(
            client, {"kind": "guardians", "ids": ["user_GuardianA"]}, "a" * 64
        )
        assert response.status_code == 503
        assert (
            await db_session.scalar(select(func.count()).select_from(SchoolPublication))
            == 0
        )


@pytest.mark.asyncio
async def test_search_is_literal_and_lists_are_paginated(db_session, monkeypatch):
    await seed(db_session, monkeypatch)
    target = {"kind": "guardians", "ids": ["user_GuardianA"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        audience = (await preview(client, "guardians", target["ids"])).json()
        for title in ("Réunion 100%", "Réunion générale"):
            assert (
                await publish(client, target, audience["audience_hash"], title=title)
            ).status_code == 201
        result = (
            await client.get(
                "/api/publications/", params={"search": "100%"}, headers=headers()
            )
        ).json()
        assert (
            result["total_count"] == 1 and result["items"][0]["title"] == "Réunion 100%"
        )
        page = (
            await client.get(
                "/api/publications/",
                params={"limit": 1, "offset": 1},
                headers=headers(),
            )
        ).json()
        assert page["total_count"] == 2 and len(page["items"]) == 1
        assert page["items"][0]["title"] == "Réunion 100%"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["organization", "user", "status", "role"])
async def test_live_membership_check_rejects_mismatched_provider_memberships(
    monkeypatch, invalid
):
    monkeypatch.setattr(settings, "WORKOS_API_KEY", "test-key")
    membership = SimpleNamespace(
        organization_id=ORG,
        user_id="user_GuardianA",
        status="active",
        roles=[SimpleNamespace(slug="guardian")],
    )
    if invalid == "organization":
        membership.organization_id = OTHER
    elif invalid == "user":
        membership.user_id = "user_SomeoneElse"
    elif invalid == "status":
        membership.status = "inactive"
    else:
        membership.roles = [SimpleNamespace(slug="teacher")]

    class Client:
        def __init__(self, **kwargs):
            self.organization_membership = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def list_organization_memberships(self, **kwargs):
            return SimpleNamespace(data=[membership])

    monkeypatch.setattr(services, "AsyncWorkOSClient", Client)
    with pytest.raises(HTTPException) as failure:
        await services._active_viewer(
            {"user_id": "user_GuardianA", "organization_id": ORG}, "guardian"
        )
    assert failure.value.status_code == 403
