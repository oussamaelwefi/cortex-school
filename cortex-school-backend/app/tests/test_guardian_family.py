import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update

from core.auth import get_current_user
from core.db import utcnow
from main import app
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.ai.guardian_weekly import guardian_weekly_explanation_service
from modules.ai.schemas import (
    GuardianWeeklyExplanationRequest,
    GuardianWeeklyExplanationModelResult,
    GuardianWeeklyExplanationText,
)
from modules.attendance.models import (
    AttendanceRecord,
    AttendanceStatus,
    AttendanceSubmission,
)
from modules.classrooms.models import ClassEnrollment, Classroom
from modules.enrollments.models import Enrollment
from modules.guardian_family.services import (
    get_family_feed,
    get_family_overview,
    get_family_update_detail,
)
from modules.schools.models import Country, School
from modules.student_registration.models import (
    StudentRegistrationRequest,
    StudentRegistrationStatus,
)
from modules.student_registration.services import require_active_guardian
from modules.student_updates.models import (
    GuardianUpdateState,
    StudentUpdate,
    StudentUpdateActorRole,
    StudentUpdateEvent,
    StudentUpdateEventType,
    StudentUpdateRecipient,
    StudentUpdateStatus,
    StudentUpdateTargetType,
)
from modules.students.models import GuardianStudent, Student
from modules.student_updates.services import (
    acknowledge_guardian_update,
    add_guardian_reply,
)


ORG_A = "org_guardian_family_a"
ORG_B = "org_guardian_family_b"
GUARDIAN_A = "user_guardian_a"
GUARDIAN_OTHER = "user_guardian_other"
GUARDIAN_B = "user_guardian_b"


def test_guardian_weekly_contract_rejects_unbounded_or_unscoped_citations():
    with pytest.raises(ValidationError):
        GuardianWeeklyExplanationText(text="Too long", source_keys=["s1", "s1"])
    with pytest.raises(ValidationError):
        GuardianWeeklyExplanationText(text="x" * 501, source_keys=["s1"])
    with pytest.raises(ValidationError):
        GuardianWeeklyExplanationText(
            text="Contains a provider link",
            source_keys=["s1"],
            href="https://example.test",
        )
    with pytest.raises(ValidationError):
        GuardianWeeklyExplanationRequest(output_language="de")


def _stamp(value: datetime) -> datetime:
    return value.replace(microsecond=0)


async def _seed_family(session):
    now = _stamp(utcnow())
    school_date = now.astimezone(ZoneInfo("Africa/Tunis")).date()
    year_start = school_date - timedelta(days=30)
    year_end = school_date + timedelta(days=300)

    country = Country(code="TN", name="Tunisia", calling_code="+216")
    school_a = School(
        organization_id=ORG_A,
        country_code=country.code,
        timezone="Africa/Tunis",
        instructional_weekdays=[0, 1, 2, 3, 4, 5, 6],
    )
    school_b = School(
        organization_id=ORG_B,
        country_code=country.code,
        timezone="Africa/Tunis",
        instructional_weekdays=[0, 1, 2, 3, 4, 5, 6],
    )
    year_a = AcademicYear(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        name="2026-2027",
        starts_on=year_start,
        ends_on=year_end,
        status=AcademicYearStatus.ACTIVE,
    )
    year_b = AcademicYear(
        id=uuid.uuid4(),
        organization_id=ORG_B,
        name="2026-2027",
        starts_on=year_start,
        ends_on=year_end,
        status=AcademicYearStatus.ACTIVE,
    )
    classroom_a = Classroom(id=uuid.uuid4(), academic_year_id=year_a.id, name="Blue Room")
    classroom_b = Classroom(id=uuid.uuid4(), academic_year_id=year_b.id, name="Green Room")

    child_one = Student(
        id=uuid.uuid4(),
        organization_id=ORG_A, first_name="Amina", last_name="Alpha"
    )
    child_two = Student(
        id=uuid.uuid4(),
        organization_id=ORG_A, first_name="Bilal", last_name="Alpha"
    )
    other_child = Student(
        id=uuid.uuid4(),
        organization_id=ORG_B, first_name="Chahine", last_name="Beta"
    )
    enrollment_one = Enrollment(
        id=uuid.uuid4(), student_id=child_one.id, academic_year_id=year_a.id
    )
    enrollment_two = Enrollment(
        id=uuid.uuid4(), student_id=child_two.id, academic_year_id=year_a.id
    )
    other_enrollment = Enrollment(
        id=uuid.uuid4(),
        student_id=other_child.id, academic_year_id=year_b.id
    )
    current_placement = ClassEnrollment(
        id=uuid.uuid4(),
        classroom_id=classroom_a.id,
        enrollment_id=enrollment_one.id,
        effective_from=year_start,
    )
    ended_placement = ClassEnrollment(
        id=uuid.uuid4(),
        classroom_id=classroom_a.id,
        enrollment_id=enrollment_two.id,
        effective_from=year_start,
        effective_until=school_date,
    )
    other_placement = ClassEnrollment(
        id=uuid.uuid4(),
        classroom_id=classroom_b.id,
        enrollment_id=other_enrollment.id,
        effective_from=year_start,
    )

    attendance_submission = AttendanceSubmission(
        id=uuid.uuid4(),
        classroom_id=classroom_a.id,
        school_date=school_date,
        submitted_by_workos_user_id="teacher_a",
        submitted_at=now,
        updated_by_workos_user_id="teacher_a",
    )
    today_attendance = AttendanceRecord(
        id=uuid.uuid4(),
        submission_id=attendance_submission.id,
        class_enrollment_id=current_placement.id,
        school_date=school_date,
        status=AttendanceStatus.PRESENT,
        note="Family-visible note",
        updated_by_workos_user_id="teacher_a",
    )
    old_submission = AttendanceSubmission(
        id=uuid.uuid4(),
        classroom_id=classroom_a.id,
        school_date=school_date - timedelta(days=1),
        submitted_by_workos_user_id="teacher_a",
        submitted_at=now - timedelta(days=1),
        updated_by_workos_user_id="teacher_a",
    )
    old_attendance = AttendanceRecord(
        id=uuid.uuid4(),
        submission_id=old_submission.id,
        class_enrollment_id=ended_placement.id,
        school_date=school_date - timedelta(days=1),
        status=AttendanceStatus.ABSENT,
        note=None,
        updated_by_workos_user_id="teacher_a",
    )

    update = StudentUpdate(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        classroom_id=classroom_a.id,
        teacher_workos_user_id="teacher_a",
        target_type=StudentUpdateTargetType.CLASSROOM,
        title="Bring the reading folder",
        body="Please bring it tomorrow.",
        requires_acknowledgement=True,
        allows_replies=True,
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=2),
    )
    closed_update = StudentUpdate(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        classroom_id=classroom_a.id,
        teacher_workos_user_id="teacher_a",
        target_type=StudentUpdateTargetType.STUDENTS,
        title="Closed response update",
        body="No reply is needed.",
        requires_acknowledgement=False,
        allows_replies=False,
        created_at=now - timedelta(hours=3),
        updated_at=now - timedelta(hours=3),
    )
    recipient = StudentUpdateRecipient(
        id=uuid.uuid4(),
        student_update_id=update.id,
        student_id=child_one.id,
        class_enrollment_id=current_placement.id,
        status=StudentUpdateStatus.ASSIGNED,
    )
    closed_recipient = StudentUpdateRecipient(
        id=uuid.uuid4(),
        student_update_id=closed_update.id,
        student_id=child_one.id,
        class_enrollment_id=current_placement.id,
        status=StudentUpdateStatus.ASSIGNED,
    )
    assigned_event = StudentUpdateEvent(
        id=uuid.uuid4(),
        recipient_id=recipient.id,
        event_type=StudentUpdateEventType.ASSIGNED,
        actor_workos_user_id="teacher_a",
        actor_role=StudentUpdateActorRole.TEACHER,
        new_status=StudentUpdateStatus.ASSIGNED,
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=2),
    )
    feedback_event = StudentUpdateEvent(
        id=uuid.uuid4(),
        recipient_id=recipient.id,
        event_type=StudentUpdateEventType.TEACHER_FEEDBACK,
        actor_workos_user_id="teacher_a",
        actor_role=StudentUpdateActorRole.TEACHER,
        content="Thanks for checking.",
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
    )
    other_guardian_event = StudentUpdateEvent(
        id=uuid.uuid4(),
        recipient_id=recipient.id,
        event_type=StudentUpdateEventType.GUARDIAN_REPLY,
        actor_workos_user_id=GUARDIAN_OTHER,
        actor_role=StudentUpdateActorRole.GUARDIAN,
        content="Another guardian reply.",
        created_at=now - timedelta(minutes=30),
        updated_at=now - timedelta(minutes=30),
    )
    closed_assigned_event = StudentUpdateEvent(
        id=uuid.uuid4(),
        recipient_id=closed_recipient.id,
        event_type=StudentUpdateEventType.ASSIGNED,
        actor_workos_user_id="teacher_a",
        actor_role=StudentUpdateActorRole.TEACHER,
        new_status=StudentUpdateStatus.ASSIGNED,
    )
    state = GuardianUpdateState(
        id=uuid.uuid4(),
        recipient_id=recipient.id,
        guardian_workos_user_id=GUARDIAN_A,
    )
    closed_state = GuardianUpdateState(
        id=uuid.uuid4(),
        recipient_id=closed_recipient.id,
        guardian_workos_user_id=GUARDIAN_A,
    )
    pending_request = StudentRegistrationRequest(
        id=uuid.uuid4(),
        guardian_workos_user_id=GUARDIAN_A,
        organization_id=ORG_A,
        child_first_name="Pending",
        child_last_name="Child",
        academic_year_id=year_a.id,
        status=StudentRegistrationStatus.PENDING,
    )
    rejected_request = StudentRegistrationRequest(
        id=uuid.uuid4(),
        guardian_workos_user_id=GUARDIAN_A,
        organization_id=ORG_A,
        child_first_name="Rejected",
        child_last_name="Child",
        academic_year_id=year_a.id,
        status=StudentRegistrationStatus.REJECTED,
        rejection_reason="Could not verify the request.",
    )

    session.add(country)
    await session.flush()
    session.add_all([school_a, school_b])
    await session.flush()
    session.add_all([year_a, year_b])
    await session.flush()
    session.add_all([classroom_a, classroom_b])
    await session.flush()
    session.add_all([child_one, child_two, other_child])
    await session.flush()
    session.add_all([enrollment_one, enrollment_two, other_enrollment])
    await session.flush()
    session.add_all([current_placement, ended_placement, other_placement])
    await session.flush()
    session.add_all([attendance_submission, old_submission])
    await session.flush()
    session.add_all([today_attendance, old_attendance])
    await session.flush()
    session.add_all([update, closed_update])
    await session.flush()
    session.add_all([recipient, closed_recipient])
    await session.flush()
    session.add_all(
        [
            assigned_event,
            feedback_event,
            other_guardian_event,
            closed_assigned_event,
            state,
            closed_state,
            pending_request,
            rejected_request,
            GuardianStudent(
                student_id=child_one.id, guardian_workos_user_id=GUARDIAN_A
            ),
            GuardianStudent(
                student_id=child_two.id, guardian_workos_user_id=GUARDIAN_A
            ),
            GuardianStudent(
                student_id=child_one.id, guardian_workos_user_id=GUARDIAN_OTHER
            ),
            GuardianStudent(
                student_id=other_child.id, guardian_workos_user_id=GUARDIAN_B
            ),
        ]
    )
    await session.commit()
    return {
        "school_date": school_date,
        "child_one": child_one.id,
        "child_two": child_two.id,
        "other_child": other_child.id,
        "recipient": recipient.id,
        "closed_recipient": closed_recipient.id,
    }


@pytest.mark.asyncio
async def test_family_overview_and_feed_are_scoped_and_safe(db_session):
    seeded = await _seed_family(db_session)
    guardian = {"user_id": GUARDIAN_A, "organization_id": ORG_A}

    overview = await get_family_overview(db_session, guardian)
    assert {child.id for child in overview[2]} == {seeded["child_one"], seeded["child_two"]}
    first_child = next(child for child in overview[2] if child.id == seeded["child_one"])
    second_child = next(child for child in overview[2] if child.id == seeded["child_two"])
    assert first_child.placement.state == "current"
    assert first_child.attendance.today.status == AttendanceStatus.PRESENT
    assert first_child.attendance.today.note == "Family-visible note"
    assert first_child.unread_update_count == 2
    assert first_child.needs_response_count == 1
    assert second_child.placement.state == "not_placed"
    assert second_child.attendance.today.state == "not_expected"
    assert {request.status for request in overview[3]} == {
        StudentRegistrationStatus.PENDING,
        StudentRegistrationStatus.REJECTED,
    }

    await db_session.rollback()
    feed = await get_family_feed(
        db_session,
        seeded["child_one"],
        guardian,
        limit=3,
        offset=0,
        unread_only=False,
        from_date=None,
        to_date=None,
    )
    assert feed.items
    assert feed.current_week_start == seeded["school_date"] - timedelta(
        days=seeded["school_date"].weekday()
    )
    assert feed.current_week_end == seeded["school_date"]
    assert feed.ai_guardian_weekly_explanation_enabled is False
    assert [item.occurred_at for item in feed.items] == sorted(
        (item.occurred_at for item in feed.items), reverse=True
    )
    payload = feed.model_dump_json()
    assert "teacher_a" not in payload
    assert GUARDIAN_OTHER not in payload
    assert any(item.type == "update_event" for item in feed.items)

    await db_session.rollback()
    with pytest.raises(HTTPException) as error:
        await get_family_feed(
            db_session,
            seeded["other_child"],
            guardian,
            limit=30,
            offset=0,
            unread_only=False,
            from_date=None,
            to_date=None,
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_family_route_mocks_membership_and_enforces_response_policies(db_session):
    seeded = await _seed_family(db_session)
    guardian = {"user_id": GUARDIAN_A, "organization_id": ORG_A}

    async def override_user():
        return guardian

    async def override_guardian():
        return guardian

    async def override_session():
        yield db_session

    from core.db import db_session as db_session_dependency

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[require_active_guardian] = override_guardian
    app.dependency_overrides[db_session_dependency] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/guardian/family/")
            assert response.status_code == 200
            assert response.json()["children"]
            wrong_student = await client.get(
                f"/api/guardian/family/students/{seeded['other_child']}/feed/"
            )
            assert wrong_student.status_code == 404
    finally:
        app.dependency_overrides.clear()

    await db_session.rollback()
    with pytest.raises(HTTPException) as acknowledgement_error:
        await acknowledge_guardian_update(
            db_session, seeded["closed_recipient"], guardian
        )
    assert acknowledgement_error.value.status_code == 409

    await db_session.rollback()
    with pytest.raises(HTTPException) as reply_error:
        await add_guardian_reply(
            db_session,
            seeded["closed_recipient"],
            "This must not be accepted",
            guardian,
        )
    assert reply_error.value.status_code == 409


@pytest.mark.asyncio
async def test_family_filters_are_paginated_and_recheck_authorization(db_session):
    seeded = await _seed_family(db_session)
    guardian = {"user_id": GUARDIAN_A, "organization_id": ORG_A}
    school_date = seeded["school_date"]

    await db_session.rollback()
    today_feed = await get_family_feed(
        db_session,
        seeded["child_one"],
        guardian,
        limit=2,
        offset=0,
        unread_only=False,
        from_date=school_date,
        to_date=school_date,
    )
    next_page = await get_family_feed(
        db_session,
        seeded["child_one"],
        guardian,
        limit=2,
        offset=2,
        unread_only=False,
        from_date=school_date,
        to_date=school_date,
    )
    assert today_feed.has_more
    assert set(item.id for item in today_feed.items).isdisjoint(
        item.id for item in next_page.items
    )
    assert all(
        item.type != "attendance" or item.school_date == school_date
        for item in today_feed.items + next_page.items
    )

    await db_session.rollback()
    state = await db_session.scalar(
        select(GuardianUpdateState).where(
            GuardianUpdateState.recipient_id == seeded["recipient"],
            GuardianUpdateState.guardian_workos_user_id == GUARDIAN_A,
        )
    )
    assert state is not None
    state.read_at = utcnow()
    await db_session.commit()

    unread_feed = await get_family_feed(
        db_session,
        seeded["child_one"],
        guardian,
        limit=30,
        offset=0,
        unread_only=True,
        from_date=None,
        to_date=None,
    )
    assert all(
        getattr(item, "recipient_id", None) != seeded["recipient"]
        for item in unread_feed.items
    )

    await db_session.rollback()
    with pytest.raises(HTTPException) as wrong_student_error:
        await get_family_update_detail(
            db_session,
            seeded["child_two"],
            seeded["recipient"],
            guardian,
        )
    assert wrong_student_error.value.status_code == 404

    await db_session.rollback()
    first_ack = await acknowledge_guardian_update(
        db_session, seeded["recipient"], guardian
    )
    first_acknowledged_at = first_ack[4].acknowledged_at
    first_event_count = await db_session.scalar(
        select(func.count(StudentUpdateEvent.id)).where(
            StudentUpdateEvent.recipient_id == seeded["recipient"],
            StudentUpdateEvent.event_type == StudentUpdateEventType.GUARDIAN_ACKNOWLEDGED,
        )
    )
    await db_session.rollback()
    second_ack = await acknowledge_guardian_update(
        db_session, seeded["recipient"], guardian
    )
    second_event_count = await db_session.scalar(
        select(func.count(StudentUpdateEvent.id)).where(
            StudentUpdateEvent.recipient_id == seeded["recipient"],
            StudentUpdateEvent.event_type == StudentUpdateEventType.GUARDIAN_ACKNOWLEDGED,
        )
    )
    assert second_ack[4].acknowledged_at == first_acknowledged_at
    assert second_event_count == first_event_count

    await db_session.rollback()
    with pytest.raises(HTTPException) as cross_family_reply_error:
        await add_guardian_reply(
            db_session,
            seeded["recipient"],
            "This guardian is not linked to the organization",
            {"user_id": GUARDIAN_B, "organization_id": ORG_B},
        )
    assert cross_family_reply_error.value.status_code == 404

    await db_session.rollback()
    await db_session.execute(
        delete(GuardianStudent).where(
            GuardianStudent.student_id == seeded["child_two"],
            GuardianStudent.guardian_workos_user_id == GUARDIAN_A,
        )
    )
    await db_session.commit()
    overview = await get_family_overview(db_session, guardian)
    assert {child.id for child in overview[2]} == {seeded["child_one"]}


class _WeeklyFakeChain:
    def __init__(self, result):
        self.result = result
        self.prompts = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return {
            "parsed": self.result,
            "raw": type(
                "RawMessage",
                (),
                {
                    "usage_metadata": {
                        "input_tokens": 50,
                        "output_tokens": 20,
                        "total_tokens": 70,
                    }
                },
            )(),
            "parsing_error": None,
        }


@pytest.mark.asyncio
async def test_guardian_weekly_explanation_is_scoped_and_grounded(
    db_session,
    monkeypatch,
):
    seeded = await _seed_family(db_session)
    guardian = {"user_id": GUARDIAN_A, "organization_id": ORG_A}
    await db_session.execute(
        update(School)
        .where(School.organization_id == ORG_A)
        .values(
            ai_guardian_weekly_explanation_enabled=True,
            ai_guardian_weekly_explanation_default_language="fr",
        )
    )
    await db_session.commit()

    async def consume_rate_limit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "modules.ai.guardian_weekly._consume_rate_limit",
        consume_rate_limit,
    )
    chain = _WeeklyFakeChain(
        GuardianWeeklyExplanationModelResult(
            overview=[
                GuardianWeeklyExplanationText(
                    text="The selected records cover attendance and school updates.",
                    source_keys=["s1", "s2"],
                )
            ],
            attendance_summary=GuardianWeeklyExplanationText(
                text="One attendance record was submitted.",
                source_keys=["s1"],
            ),
            school_updates=[
                GuardianWeeklyExplanationText(
                    text="Bring the reading folder.",
                    source_keys=["s2"],
                ),
            ],
        )
    )

    response = await guardian_weekly_explanation_service.generate(
        session=db_session,
        student_id=seeded["child_one"],
        current_user=guardian,
        output_language=None,
        request_id="weekly-request-1",
        chain=chain,
    )

    assert response.status == "generated"
    assert response.ai_generated is True
    assert response.output_language.value == "fr"
    assert response.attendance.counts.present == 1
    assert response.attendance.missing_dates
    assert [source.kind for source in response.sources] == [
        "attendance",
        "update",
        "update",
    ]
    assert response.sources[0].href.endswith(
        f"?from={seeded['school_date'].isoformat()}&to={seeded['school_date'].isoformat()}"
    )
    assert "Another guardian reply." not in chain.prompts[0]
    assert str(seeded["child_one"]) not in chain.prompts[0]
    assert "Bring the reading folder" in chain.prompts[0]


@pytest.mark.asyncio
async def test_guardian_weekly_explanation_returns_deterministic_fallback(
    db_session,
    monkeypatch,
):
    seeded = await _seed_family(db_session)
    guardian = {"user_id": GUARDIAN_A, "organization_id": ORG_A}
    await db_session.execute(
        update(School)
        .where(School.organization_id == ORG_A)
        .values(ai_guardian_weekly_explanation_enabled=True)
    )
    await db_session.commit()

    async def consume_rate_limit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "modules.ai.guardian_weekly._consume_rate_limit",
        consume_rate_limit,
    )
    chain = _WeeklyFakeChain(
        GuardianWeeklyExplanationModelResult(
            overview=[
                GuardianWeeklyExplanationText(
                    text="This cites an unavailable source.",
                    source_keys=["s99"],
                )
            ]
        )
    )

    response = await guardian_weekly_explanation_service.generate(
        session=db_session,
        student_id=seeded["child_one"],
        current_user=guardian,
        output_language="en",
        request_id="weekly-request-2",
        chain=chain,
    )

    assert response.status == "fallback"
    assert response.ai_generated is False
    assert response.retryable is True
    assert [item.text for item in response.school_updates] == [
        "Bring the reading folder",
        "Closed response update",
    ]
    assert response.sources
    assert "unavailable source" not in response.model_dump_json()

    cross_section_chain = _WeeklyFakeChain(
        GuardianWeeklyExplanationModelResult(
            overview=[
                GuardianWeeklyExplanationText(
                    text="Wrong section source.",
                    source_keys=["s1"],
                )
            ],
            school_updates=[
                GuardianWeeklyExplanationText(
                    text="Attendance is not an update.",
                    source_keys=["s1"],
                )
            ],
        )
    )
    cross_section_response = await guardian_weekly_explanation_service.generate(
        session=db_session,
        student_id=seeded["child_one"],
        current_user=guardian,
        output_language="en",
        request_id="weekly-request-2b",
        chain=cross_section_chain,
    )
    assert cross_section_response.status == "fallback"


@pytest.mark.asyncio
async def test_guardian_weekly_explanation_empty_does_not_call_provider(
    db_session,
    monkeypatch,
):
    await _seed_family(db_session)
    guardian = {"user_id": GUARDIAN_A, "organization_id": ORG_A}
    await db_session.execute(
        update(School)
        .where(School.organization_id == ORG_A)
        .values(ai_guardian_weekly_explanation_enabled=True)
    )
    empty_student = Student(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        first_name="Empty",
        last_name="Child",
    )
    db_session.add(empty_student)
    await db_session.flush()
    db_session.add(
        GuardianStudent(
            student_id=empty_student.id,
            guardian_workos_user_id=GUARDIAN_A,
        )
    )
    await db_session.commit()

    async def consume_rate_limit(*args, **kwargs):
        raise AssertionError("empty explanations must not consume the rate limit")

    monkeypatch.setattr(
        "modules.ai.guardian_weekly._consume_rate_limit",
        consume_rate_limit,
    )
    chain = _WeeklyFakeChain(None)

    response = await guardian_weekly_explanation_service.generate(
        session=db_session,
        student_id=empty_student.id,
        current_user=guardian,
        output_language=None,
        request_id="weekly-request-empty",
        chain=chain,
    )

    assert response.status == "empty"
    assert response.retryable is False
    assert chain.prompts == []


@pytest.mark.asyncio
async def test_guardian_weekly_explanation_rechecks_feature_and_child_scope(
    db_session,
):
    seeded = await _seed_family(db_session)
    guardian = {"user_id": GUARDIAN_A, "organization_id": ORG_A}
    chain = _WeeklyFakeChain(
        GuardianWeeklyExplanationModelResult(
            overview=[
                GuardianWeeklyExplanationText(
                    text="Unused.",
                    source_keys=["s1"],
                )
            ]
        )
    )

    with pytest.raises(HTTPException) as disabled_error:
        await guardian_weekly_explanation_service.generate(
            session=db_session,
            student_id=seeded["child_one"],
            current_user=guardian,
            output_language=None,
            request_id="weekly-request-3",
            chain=chain,
        )
    assert disabled_error.value.status_code == 403
    assert chain.prompts == []

    await db_session.rollback()
    with pytest.raises(HTTPException) as wrong_student_error:
        await guardian_weekly_explanation_service.generate(
            session=db_session,
            student_id=seeded["other_child"],
            current_user=guardian,
            output_language=None,
            request_id="weekly-request-4",
            chain=chain,
        )
    assert wrong_student_error.value.status_code == 404
