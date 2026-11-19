import asyncio
import json
import uuid
from datetime import timedelta

import httpx
import pytest
from ai.chat import run as chat
from core.db import SessionLocal, utcnow
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from main import app
from modules.academic_years.models import (
    AcademicCalendar,
    CalendarEntry,
    CalendarEntryType,
)
from modules.ai import chat_data
from modules.ai.chat_data import SchoolDataAccess, SchoolDataQuery
from modules.attendance.models import (
    AttendanceRecord,
    AttendanceStatus,
    AttendanceSubmission,
)
from modules.classrooms.models import (
    ClassEnrollment,
    TeacherAssignment,
    TeacherAssignmentRole,
)
from modules.enrollments.models import Enrollment
from modules.invitations.models import Invitation
from modules.publications.models import PublicationRecipient, SchoolPublication
from modules.reminders.policy import add_policy
from modules.student_registration.models import (
    StudentRegistrationRequest,
    StudentRegistrationStatus,
)
from modules.student_updates.models import (
    GuardianUpdateState,
    StudentUpdate,
    StudentUpdateRecipient,
    StudentUpdateStatus,
    StudentUpdateTargetType,
)
from modules.students.models import GuardianStudent, Student
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from test_publications import ORG, OTHER, headers, seed


def user(role, name=None, organization=ORG):
    return {
        "user_id": f"user_{name or {'admin': 'Admin', 'teacher': 'TeacherA', 'guardian': 'GuardianA'}[role]}",
        "organization_id": organization,
        "claims": {
            "roles": ["school_admin" if role == "admin" else role],
            "permissions": ["school:manage"] if role == "admin" else [],
        },
    }


async def prepare(session, monkeypatch):
    data = await seed(session, monkeypatch)
    members = data["members"]
    members[ORG].extend(
        [
            {
                "id": "user_Admin",
                "name": "School administrator",
                "roles": ["school_admin"],
                "status": "active",
            },
            {
                "id": "user_TeacherOther",
                "name": "Other teacher",
                "roles": ["teacher"],
                "status": "active",
            },
            {
                "id": "user_GuardianOther",
                "name": "Other guardian",
                "roles": ["guardian"],
                "status": "active",
            },
        ]
    )
    for items in members.values():
        for item in items:
            item["email"] = f"{item['id']}@example.invalid"

    async def viewer(current_user, role):
        uid, org = current_user["user_id"], current_user["organization_id"]
        if not any(
            item["id"] == uid and role in item["roles"] for item in members.get(org, [])
        ):
            raise HTTPException(403, "Membership revoked")
        return uid, org

    async def school_members(org):
        return members[org]

    monkeypatch.setattr(chat_data, "_active_viewer", viewer)
    monkeypatch.setattr(chat_data, "list_school_members", school_members)
    today = utcnow().astimezone(__import__("zoneinfo").ZoneInfo("Africa/Tunis")).date()
    a, b, foreign = data["classes"]
    await session.execute(
        delete(TeacherAssignment).where(
            TeacherAssignment.classroom_id == b.id,
            TeacherAssignment.teacher_workos_user_id == "user_TeacherA",
        )
    )
    session.add(
        TeacherAssignment(
            classroom_id=b.id,
            teacher_workos_user_id="user_TeacherOther",
            role=TeacherAssignmentRole.LEAD,
            effective_from=today - timedelta(days=20),
        )
    )
    other = Student(
        id=uuid.uuid4(),
        organization_id=ORG,
        first_name="Unrelated",
        last_name="Student",
    )
    session.add(other)
    await session.flush()
    enrollment = Enrollment(
        id=uuid.uuid4(), student_id=other.id, academic_year_id=b.academic_year_id
    )
    session.add(enrollment)
    await session.flush()
    placement = ClassEnrollment(
        id=uuid.uuid4(),
        classroom_id=b.id,
        enrollment_id=enrollment.id,
        effective_from=today - timedelta(days=20),
    )
    session.add(placement)
    session.add(
        GuardianStudent(
            student_id=other.id, guardian_workos_user_id="user_GuardianOther"
        )
    )
    await session.flush()
    for classroom, teacher in (
        (a, "user_TeacherA"),
        (b, "user_TeacherOther"),
        (foreign, "user_ForeignTeacher"),
    ):
        submission = AttendanceSubmission(
            id=uuid.uuid4(),
            classroom_id=classroom.id,
            school_date=today,
            submitted_by_workos_user_id=teacher,
            updated_by_workos_user_id=teacher,
            submitted_at=utcnow(),
        )
        session.add(submission)
        await session.flush()
        placements = (
            await session.scalars(
                select(ClassEnrollment).where(
                    ClassEnrollment.classroom_id == classroom.id,
                    ClassEnrollment.effective_until.is_(None),
                )
            )
        ).all()
        for item in placements:
            session.add(
                AttendanceRecord(
                    submission_id=submission.id,
                    class_enrollment_id=item.id,
                    school_date=today,
                    status=AttendanceStatus.ABSENT,
                    updated_by_workos_user_id=teacher,
                )
            )
    for year_id, title in (
        (a.academic_year_id, "School A holiday"),
        (foreign.academic_year_id, "FOREIGN SECRET holiday"),
    ):
        calendar = AcademicCalendar(id=uuid.uuid4(), academic_year_id=year_id)
        session.add(calendar)
        await session.flush()
        session.add(
            CalendarEntry(
                academic_calendar_id=calendar.id,
                entry_type=CalendarEntryType.HOLIDAY,
                title=title,
                starts_on=today,
                ends_on=today,
            )
        )
    notices = []
    for classroom, child, teacher, title in (
        (a, data["children"][0], "user_TeacherA", "Reading authorization"),
        (b, other, "user_TeacherOther", "UNRELATED SECRET update"),
        (foreign, data["children"][3], "user_ForeignTeacher", "FOREIGN SECRET update"),
    ):
        notice = StudentUpdate(
            id=uuid.uuid4(),
            organization_id=ORG if classroom != foreign else OTHER,
            classroom_id=classroom.id,
            teacher_workos_user_id=teacher,
            target_type=StudentUpdateTargetType.STUDENTS,
            title=title,
            body="Bring the signed authorization.",
            requires_acknowledgement=True,
            due_at=utcnow() - timedelta(hours=2),
        )
        session.add(notice)
        await session.flush()
        recipient = StudentUpdateRecipient(
            id=uuid.uuid4(),
            student_update_id=notice.id,
            student_id=child.id,
            class_enrollment_id=await session.scalar(
                select(ClassEnrollment.id)
                .join(Enrollment)
                .where(
                    Enrollment.student_id == child.id,
                    ClassEnrollment.classroom_id == classroom.id,
                )
            ),
            status=StudentUpdateStatus.ACKNOWLEDGED
            if classroom == a
            else StudentUpdateStatus.ASSIGNED,
        )
        session.add(recipient)
        await session.flush()
        if classroom == a:
            session.add_all(
                [
                    GuardianUpdateState(
                        recipient_id=recipient.id,
                        guardian_workos_user_id="user_GuardianA",
                        acknowledged_at=utcnow(),
                        read_at=utcnow(),
                    ),
                    GuardianUpdateState(
                        recipient_id=recipient.id,
                        guardian_workos_user_id="user_GuardianB",
                        read_at=utcnow(),
                    ),
                ]
            )
        notices.append(notice)
    for org, owner, title, roles in (
        (ORG, "user_GuardianA", "Message for my family", ["guardian"]),
        (ORG, "user_GuardianOther", "UNRELATED SECRET publication", ["guardian"]),
        (OTHER, "user_GuardianA", "FOREIGN SECRET publication", ["guardian"]),
        (ORG, "user_TeacherA", "Message for my teacher", ["teacher"]),
    ):
        pub = SchoolPublication(
            id=uuid.uuid4(),
            organization_id=org,
            author_user_id="user_Admin",
            idempotency_key=uuid.uuid4(),
            payload_hash="a" * 64,
            title=title,
            body="Message body.",
            target_kind="guardians",
            target_ids=[owner],
            recipient_count=1,
        )
        session.add(pub)
        await session.flush()
        session.add(
            PublicationRecipient(
                publication_id=pub.id,
                user_id=owner,
                name=owner,
                roles=roles,
                student_ids=[],
            )
        )
    for org, owner, name, year in (
        (ORG, "user_GuardianA", "My pending child", a.academic_year_id),
        (ORG, "user_GuardianOther", "UNRELATED SECRET child", a.academic_year_id),
        (OTHER, "user_GuardianA", "FOREIGN SECRET child", foreign.academic_year_id),
    ):
        session.add(
            StudentRegistrationRequest(
                organization_id=org,
                guardian_workos_user_id=owner,
                child_first_name=name,
                child_last_name="Registration",
                academic_year_id=year,
                status=StudentRegistrationStatus.PENDING,
            )
        )
    for org, email in (
        (ORG, "visible@example.invalid"),
        (OTHER, "FOREIGN-SECRET@example.invalid"),
    ):
        session.add(
            Invitation(
                organization_id=org,
                email=email,
                first_name="Invite",
                error_message="CREDENTIAL_SECRET",
                send_status="sent",
            )
        )
    await session.commit()
    await add_policy(
        session,
        ORG,
        "Règlement des sorties scolaires",
        [
            (
                "Article 1",
                "Une autorisation parentale signée est requise pour la sortie pédagogique.",
            )
        ],
    )
    await add_policy(
        session,
        OTHER,
        "FOREIGN SECRET policy",
        [("Article 1", "Sortie pédagogique FOREIGN SECRET details.")],
    )
    data.update(
        other_student=other.id,
        own_update=notices[0].id,
        other_update=notices[1].id,
        today=today,
    )
    return data


async def query(role, dataset, **filters):
    async with SessionLocal() as session:
        access = SchoolDataAccess(session, user(role), role)
        result = await access.query(SchoolDataQuery(dataset=dataset, **filters))
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,expected", [("admin", 4), ("teacher", 2), ("guardian", 2)]
)
async def test_student_lists_and_exact_counts_are_scoped(
    db_session, monkeypatch, role, expected
):
    data = await prepare(db_session, monkeypatch)
    result = await query(role, "students", limit=1)
    assert (
        result["total_count"] == expected
        and result["returned_count"] == 1
        and result["has_more"]
    )
    assert result["next_offset"] == 1
    assert "Foreign" not in json.dumps(result, default=str)
    for student_id in (data["children"][3].id, data["other_student"]):
        result = await query(role, "students", student_id=student_id)
        assert result["total_count"] == (
            1 if role == "admin" and student_id == data["other_student"] else 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,expected", [("admin", 3), ("teacher", 2), ("guardian", 2)]
)
async def test_attendance_filters_and_aggregates_stay_inside_scope(
    db_session, monkeypatch, role, expected
):
    data = await prepare(db_session, monkeypatch)
    result = await query(
        role,
        "attendance",
        date_from=data["today"],
        date_to=data["today"],
        status="absent",
        limit=1,
    )
    assert result["total_count"] == expected
    assert result["status_counts"] == {"absent": expected}
    assert result["missing_records_are_not_absences"] is True
    denied = await query(role, "attendance", classroom_id=data["classes"][2].id)
    assert denied["total_count"] == 0


@pytest.mark.asyncio
async def test_guardian_isolation_covers_updates_receipts_requests_and_publications(
    db_session, monkeypatch
):
    await prepare(db_session, monkeypatch)
    for dataset in ("updates", "acknowledgements", "registrations", "publications"):
        result = await query("guardian", dataset)
        raw = json.dumps(result, default=str)
        assert "FOREIGN SECRET" not in raw and "UNRELATED SECRET" not in raw
    pending = await query("guardian", "acknowledgements")
    assert pending["total_count"] == 0
    acknowledged = await query("guardian", "acknowledgements", status="acknowledged")
    assert acknowledged["total_count"] == 1
    assert acknowledged["items"][0]["guardian"] == "current user"
    assert acknowledged["items"][0]["acknowledged_at"] is not None
    assert (await query("guardian", "registrations"))["total_count"] == 1
    assert (await query("guardian", "publications"))["total_count"] == 1


@pytest.mark.asyncio
async def test_teacher_cannot_read_another_teachers_messages_or_admin_directory(
    db_session, monkeypatch
):
    data = await prepare(db_session, monkeypatch)
    for dataset in ("updates", "publications", "acknowledgements"):
        result = await query("teacher", dataset)
        assert "UNRELATED SECRET" not in json.dumps(result, default=str)
        assert "FOREIGN SECRET" not in json.dumps(result, default=str)
    assert (await query("teacher", "updates", record_id=data["other_update"]))[
        "total_count"
    ] == 0
    assert (await query("teacher", "classrooms"))["total_count"] == 1
    for dataset in ("members", "invitations", "registrations"):
        assert (await query("teacher", dataset))["status"] == "forbidden"


@pytest.mark.asyncio
async def test_admin_queries_other_datasets_and_policy_search_are_school_scoped(
    db_session, monkeypatch
):
    await prepare(db_session, monkeypatch)
    for dataset in (
        "overview",
        "academic_years",
        "classrooms",
        "enrollments",
        "calendar",
        "registrations",
        "invitations",
        "members",
        "updates",
        "publications",
    ):
        result = await query("admin", dataset)
        assert result["status"] == "ok", dataset
        assert "FOREIGN SECRET" not in json.dumps(result, default=str)
        assert "CREDENTIAL_SECRET" not in json.dumps(result, default=str)
    for role in ("admin", "teacher", "guardian"):
        async with SessionLocal() as session:
            access = SchoolDataAccess(session, user(role), role)
            result = await access.search_policies(["autorisation", "sortie"])
            assert len(result["items"]) == 1
            assert "FOREIGN SECRET" not in json.dumps(result)
            source = access.sources[result["items"][0]["source_id"]]
            assert (
                source.excerpt
                == "Une autorisation parentale signée est requise pour la sortie pédagogique."
            )


@pytest.mark.asyncio
async def test_database_transaction_is_read_only_and_permission_is_rechecked(
    db_session, monkeypatch
):
    await prepare(db_session, monkeypatch)
    async with SessionLocal() as session:
        access = SchoolDataAccess(session, user("guardian"), "guardian")
        await access.query(SchoolDataQuery(dataset="students"))
        assert await session.scalar(text("SHOW transaction_read_only")) == "on"
        with pytest.raises(DBAPIError):
            session.add(
                Student(organization_id=ORG, first_name="Forbidden", last_name="Write")
            )
            await session.flush()

    async def revoked(*args):
        raise HTTPException(403, "Membership revoked")

    monkeypatch.setattr(chat_data, "_active_viewer", revoked)
    with pytest.raises(HTTPException):
        await query("guardian", "students")


def test_roles_and_filter_parameters_cannot_be_escalated():
    with pytest.raises(HTTPException):
        SchoolDataAccess(None, user("guardian"), "admin")
    with pytest.raises(ValidationError):
        SchoolDataQuery(dataset="students", organization_id=OTHER)
    with pytest.raises(ValidationError):
        SchoolDataQuery(dataset="execute_sql")
    with pytest.raises(ValidationError):
        SchoolDataQuery(dataset="students", limit=500)
    with pytest.raises(ValidationError):
        SchoolDataQuery(
            dataset="attendance", date_from="2024-01-01", date_to="2026-11-19"
        )


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []

    def bind_tools(self, tools, **kwargs):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        self.messages.append(list(messages))
        return AIMessage(content="", tool_calls=[next(self.responses)])


def call(name, args, index=1):
    return {"id": f"call-{index}", "name": name, "args": args}


@pytest.mark.asyncio
async def test_agent_looks_up_records_returns_real_sources_and_rejects_invented_citations(
    db_session, monkeypatch
):
    await prepare(db_session, monkeypatch)
    model = Model(
        [
            call("QuerySchoolData", {"dataset": "students"}),
            call(
                "ChatAnswer", {"reply": "Deux enfants [S99].", "source_ids": ["S99"]}, 2
            ),
            call(
                "ChatAnswer",
                {
                    "reply": "Vous avez deux enfants liés à votre compte [S1].",
                    "source_ids": ["S1"],
                },
                3,
            ),
        ]
    )
    async with SessionLocal() as session:
        result = await chat.school_reply(
            session,
            user("guardian"),
            "Quels sont mes enfants ?",
            role="guardian",
            model=model,
        )
    assert result["sources"][0].id == "S1" and result["sources"][0].href == "/family"
    assert result["reply"].endswith("[S1].")
    messages = "\n".join(
        str(message.content) for turn in model.messages for message in turn
    )
    assert "Yasmine" in messages and "Adam" in messages
    assert "UNRELATED SECRET" not in messages and "FOREIGN SECRET" not in messages
    assert "invalid_sources" in messages


@pytest.mark.asyncio
async def test_general_chat_needs_no_database_lookup_and_unknown_tools_cannot_write(
    monkeypatch,
):
    model = Model(
        [
            call("execute_sql", {"sql": "DELETE FROM student"}),
            call(
                "ChatAnswer",
                {"reply": "Je peux vous aider à rédiger un message.", "source_ids": []},
                2,
            ),
        ]
    )
    result = await chat.school_reply(
        None, user("teacher"), "Help me write a message.", model=model
    )
    assert result["sources"] == []
    assert "unsupported_tool" in str(model.messages[-1][-1].content)


@pytest.mark.asyncio
async def test_chat_endpoint_enforces_identity_and_passes_workspace_to_agent(
    db_session, monkeypatch
):
    await prepare(db_session, monkeypatch)
    model = Model(
        [
            call("QuerySchoolData", {"dataset": "students"}),
            call("ChatAnswer", {"reply": "Deux élèves [S1].", "source_ids": ["S1"]}, 2),
        ]
    )
    monkeypatch.setattr(chat, "get_chat_model", lambda: model)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai/chat/",
            headers=headers(user="TeacherA", role="teacher"),
            json={"message": "Mes élèves ?", "role": "teacher", "language": "fr"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["sources"][0]["href"] == "/classrooms"
        denied = await client.post(
            "/api/ai/chat/",
            headers=headers(user="GuardianA", role="guardian"),
            json={"message": "All pupils", "role": "admin"},
        )
        assert denied.status_code == 403
        assert (
            await client.post("/api/ai/chat/", json={"message": "hello"})
        ).status_code == 401


@pytest.mark.asyncio
async def test_chat_deadline_is_bounded_without_a_database(monkeypatch):
    class Slow(Model):
        async def ainvoke(self, messages):
            await asyncio.Future()

    monkeypatch.setattr(chat, "CHAT_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(chat.LLMProviderError) as failure:
        await chat.school_reply(None, user("guardian"), "Hello", model=Slow([]))
    assert failure.value.status_code == 504


@pytest.mark.asyncio
async def test_read_receipt_does_not_complete_another_guardians_acknowledgement(
    db_session, monkeypatch
):
    await prepare(db_session, monkeypatch)
    result = await query("teacher", "acknowledgements")
    assert result["total_count"] == 1
    assert result["items"][0]["read_at"] is not None
    assert result["items"][0]["acknowledged_at"] is None
    invalid = await query("teacher", "updates", unread_only=True)
    assert invalid["status"] == "invalid_filters"


@pytest.mark.asyncio
async def test_real_chat_adapter_serializes_tools_and_finishes_without_database():
    from langchain_openai import ChatOpenAI

    async def respond(request):
        body = json.loads(request.content)
        assert body["tool_choice"] == "required"
        assert body["parallel_tool_calls"] is False
        definitions = {item["function"]["name"]: item for item in body["tools"]}
        assert set(definitions) == {
            "QuerySchoolData",
            "SearchSchoolPolicies",
            "ChatAnswer",
        }
        properties = definitions["QuerySchoolData"]["function"]["parameters"][
            "properties"
        ]
        assert "organization_id" not in properties and "sql" not in properties
        return httpx.Response(
            200,
            json={
                "id": "chat-test",
                "object": "chat.completion",
                "created": 1,
                "model": "openai/gpt-4.1-mini",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "answer-1",
                                    "type": "function",
                                    "function": {
                                        "name": "ChatAnswer",
                                        "arguments": json.dumps(
                                            {"reply": "Bonjour !", "source_ids": []}
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(
            api_key="test-only",
            base_url="https://example.invalid/api/v1",
            model="openai/gpt-4.1-mini",
            http_async_client=client,
            max_retries=0,
        )
        result = await chat.school_reply(None, user("guardian"), "Bonjour", model=model)
    assert result == {"reply": "Bonjour !", "sources": []}


@pytest.mark.asyncio
async def test_provider_failure_does_not_expose_provider_body():
    from openai import BadRequestError

    class Failed(Model):
        async def ainvoke(self, messages):
            response = httpx.Response(
                400, request=httpx.Request("POST", "https://example.invalid")
            )
            raise BadRequestError("PRIVATE PROVIDER BODY", response=response, body={})

    with pytest.raises(chat.LLMProviderError) as error:
        await chat.school_reply(None, user("guardian"), "Hello", model=Failed([]))
    assert error.value.status_code == 503
    assert "PRIVATE" not in str(error.value)
