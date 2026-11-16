import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "root")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "postgres")

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, event, select, text

from core.db import SessionLocal, engine
from main import app
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.attendance import services as attendance_services
from modules.attendance.models import AttendanceStatus
from modules.classrooms.models import (
    ClassEnrollment,
    Classroom,
    TeacherAssignment,
    TeacherAssignmentRole,
)
from modules.enrollments.models import Enrollment
from modules.invitations.models import (
    Invitation,
    InvitationSendStatus,
    UserRoles,
)
from modules.needs_review import services as needs_review_services
from modules.needs_review.schemas import NeedsReviewCategory
from modules.needs_review.services import (
    _attendance_window,
    _local_cutoff,
    _timestamp_bounds,
    build_needs_review,
)
from modules.schools.models import Country, School
from modules.schools.schemas import SchoolAttendanceSettingsRequest
from modules.student_registration.models import (
    StudentRegistrationRequest,
    StudentRegistrationStatus,
)
from modules.student_updates.models import (
    GuardianUpdateState,
    StudentUpdate,
    StudentUpdateActorRole,
    StudentUpdateEvent,
    StudentUpdateEventType,
    StudentUpdateNotification,
    StudentUpdateNotificationType,
    StudentUpdateRecipient,
    StudentUpdateStatus,
    StudentUpdateTargetType,
)
from modules.student_updates.schemas import StudentUpdateCreateRequest
from modules.students.models import GuardianStudent, Student


FIXED_NOW = datetime(2026, 9, 3, 15, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr(needs_review_services, "utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(attendance_services, "utcnow", lambda: FIXED_NOW)
    return FIXED_NOW


@dataclass(frozen=True)
class ClassroomSeed:
    year: AcademicYear
    classroom: Classroom
    student: Student
    placement: ClassEnrollment
    teacher_id: str | None


async def seed_classroom(
    session,
    *,
    organization_id: str,
    school: School | None = None,
    classroom_name: str = "Primary class",
    teacher_id: str | None = "user_teacher",
) -> ClassroomSeed:
    if school is None:
        school = await session.get(School, organization_id)
    if school is None:
        country = await session.scalar(select(Country).where(Country.code == "TN"))
        if country is None:
            country = Country(code="TN", name="Tunisia", calling_code="+216")
            session.add(country)
            await session.flush()
        school = School(
            organization_id=organization_id,
            country_code=country.code,
            timezone="Africa/Tunis",
            instructional_weekdays=[0, 1, 2, 3, 4],
            attendance_cutoff_time=time(10),
        )
        session.add(school)
        await session.flush()

    year = await session.scalar(
        select(AcademicYear).where(
            AcademicYear.organization_id == organization_id,
            AcademicYear.status == AcademicYearStatus.ACTIVE,
        )
    )
    if year is None:
        year = AcademicYear(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name="2026/27",
            starts_on=date(2026, 9, 3),
            ends_on=date(2026, 12, 31),
            status=AcademicYearStatus.ACTIVE,
        )
        session.add(year)
        await session.flush()

    classroom = Classroom(
        id=uuid.uuid4(),
        academic_year_id=year.id,
        name=classroom_name,
    )
    student = Student(
        id=uuid.uuid4(),
        organization_id=organization_id,
        first_name="Ada",
        last_name=classroom_name.replace(" ", ""),
    )
    session.add_all([classroom, student])
    await session.flush()

    enrollment = Enrollment(
        id=uuid.uuid4(),
        student_id=student.id,
        academic_year_id=year.id,
    )
    session.add(enrollment)
    await session.flush()

    placement = ClassEnrollment(
        id=uuid.uuid4(),
        classroom_id=classroom.id,
        enrollment_id=enrollment.id,
        effective_from=date(2026, 9, 3),
    )
    session.add(placement)

    if teacher_id is not None:
        session.add(
            TeacherAssignment(
                id=uuid.uuid4(),
                classroom_id=classroom.id,
                teacher_workos_user_id=teacher_id,
                role=TeacherAssignmentRole.LEAD,
                effective_from=date(2026, 9, 3),
            )
        )
    await session.flush()
    return ClassroomSeed(year, classroom, student, placement, teacher_id)


async def cleanup_organization(session, organization_id: str) -> None:
    params = {"organization_id": organization_id}
    statements = (
        "DELETE FROM backend_schema.notification WHERE organization_id = :organization_id",
        "DELETE FROM backend_schema.guardianupdatestate WHERE recipient_id IN (SELECT r.id FROM backend_schema.studentupdaterecipient r JOIN backend_schema.studentupdate u ON u.id = r.student_update_id WHERE u.organization_id = :organization_id)",
        "DELETE FROM backend_schema.studentupdateevent WHERE recipient_id IN (SELECT r.id FROM backend_schema.studentupdaterecipient r JOIN backend_schema.studentupdate u ON u.id = r.student_update_id WHERE u.organization_id = :organization_id)",
        "DELETE FROM backend_schema.studentupdaterecipient WHERE student_update_id IN (SELECT id FROM backend_schema.studentupdate WHERE organization_id = :organization_id)",
        "DELETE FROM backend_schema.studentupdate WHERE organization_id = :organization_id",
        "DELETE FROM backend_schema.attendancerecord WHERE submission_id IN (SELECT s.id FROM backend_schema.attendancesubmission s JOIN backend_schema.classroom c ON c.id = s.classroom_id JOIN backend_schema.academicyear y ON y.id = c.academic_year_id WHERE y.organization_id = :organization_id)",
        "DELETE FROM backend_schema.attendancesubmission WHERE classroom_id IN (SELECT c.id FROM backend_schema.classroom c JOIN backend_schema.academicyear y ON y.id = c.academic_year_id WHERE y.organization_id = :organization_id)",
        "DELETE FROM backend_schema.studentregistrationrequest WHERE organization_id = :organization_id",
        "DELETE FROM backend_schema.guardianstudent WHERE student_id IN (SELECT id FROM backend_schema.student WHERE organization_id = :organization_id)",
        "DELETE FROM backend_schema.classenrollment WHERE classroom_id IN (SELECT c.id FROM backend_schema.classroom c JOIN backend_schema.academicyear y ON y.id = c.academic_year_id WHERE y.organization_id = :organization_id) OR enrollment_id IN (SELECT e.id FROM backend_schema.enrollment e JOIN backend_schema.academicyear y ON y.id = e.academic_year_id WHERE y.organization_id = :organization_id)",
        "DELETE FROM backend_schema.teacherassignment WHERE classroom_id IN (SELECT c.id FROM backend_schema.classroom c JOIN backend_schema.academicyear y ON y.id = c.academic_year_id WHERE y.organization_id = :organization_id)",
        "DELETE FROM backend_schema.classroom WHERE academic_year_id IN (SELECT id FROM backend_schema.academicyear WHERE organization_id = :organization_id)",
        "DELETE FROM backend_schema.enrollment WHERE academic_year_id IN (SELECT id FROM backend_schema.academicyear WHERE organization_id = :organization_id)",
        "DELETE FROM backend_schema.invitation WHERE organization_id = :organization_id",
        "DELETE FROM backend_schema.calendarentry WHERE academic_calendar_id IN (SELECT id FROM backend_schema.academiccalendar WHERE academic_year_id IN (SELECT id FROM backend_schema.academicyear WHERE organization_id = :organization_id))",
        "DELETE FROM backend_schema.academiccalendar WHERE academic_year_id IN (SELECT id FROM backend_schema.academicyear WHERE organization_id = :organization_id)",
        "DELETE FROM backend_schema.academicyear WHERE organization_id = :organization_id",
        "DELETE FROM backend_schema.student WHERE organization_id = :organization_id",
        "DELETE FROM backend_schema.school WHERE organization_id = :organization_id",
    )
    for statement in statements:
        await session.execute(text(statement), params)
    await session.commit()


@pytest.mark.asyncio
async def test_needs_review_categories_privacy_counts_and_pagination(
    db_session,
    fixed_clock,
):
    organization_id = f"org_needs_review_{uuid.uuid4().hex}"
    seed = await seed_classroom(session=db_session, organization_id=organization_id)
    second = await seed_classroom(
        session=db_session,
        organization_id=organization_id,
        classroom_name="Unassigned class",
        teacher_id=None,
    )

    for created_at, first_name in (
        (FIXED_NOW - timedelta(hours=1), "Fresh"),
        (FIXED_NOW - timedelta(days=2), "Boundary"),
    ):
        db_session.add(
            StudentRegistrationRequest(
                id=uuid.uuid4(),
                guardian_workos_user_id=f"guardian_{first_name.lower()}",
                organization_id=organization_id,
                child_first_name=first_name,
                child_last_name="Registration",
                academic_year_id=seed.year.id,
                status=StudentRegistrationStatus.PENDING,
                created_at=created_at,
                updated_at=created_at,
            )
        )

    db_session.add_all(
        [
            Invitation(
                id=uuid.uuid4(),
                organization_id=organization_id,
                email="failed@example.com",
                role_slug=UserRoles.TEACHER,
                expires_in_days=7,
                send_status=InvitationSendStatus.FAILED,
                created_at=FIXED_NOW - timedelta(hours=2),
                updated_at=FIXED_NOW - timedelta(hours=2),
            ),
            Invitation(
                id=uuid.uuid4(),
                organization_id=organization_id,
                email="stale@example.com",
                role_slug=UserRoles.GUARDIAN,
                expires_in_days=7,
                send_status=InvitationSendStatus.SENT,
                workos_state="pending",
                sent_at=FIXED_NOW - timedelta(days=3),
                created_at=FIXED_NOW - timedelta(days=3),
                updated_at=FIXED_NOW - timedelta(days=3),
            ),
            Invitation(
                id=uuid.uuid4(),
                organization_id=organization_id,
                email="accepted@example.com",
                role_slug=UserRoles.GUARDIAN,
                expires_in_days=1,
                send_status=InvitationSendStatus.SENT,
                workos_state="accepted",
                expires_at=FIXED_NOW - timedelta(days=1),
                sent_at=FIXED_NOW - timedelta(days=2),
                created_at=FIXED_NOW - timedelta(days=2),
                updated_at=FIXED_NOW - timedelta(days=2),
            ),
        ]
    )

    guardian_one = GuardianStudent(
        id=uuid.uuid4(),
        student_id=seed.student.id,
        guardian_workos_user_id="guardian_one",
    )
    guardian_two = GuardianStudent(
        id=uuid.uuid4(),
        student_id=seed.student.id,
        guardian_workos_user_id="guardian_two",
    )
    db_session.add_all([guardian_one, guardian_two])

    required_update = StudentUpdate(
        id=uuid.uuid4(),
        organization_id=organization_id,
        classroom_id=seed.classroom.id,
        teacher_workos_user_id="user_teacher",
        target_type=StudentUpdateTargetType.CLASSROOM,
        title="Required update",
        body="PRIVATE MESSAGE BODY MUST NOT BE IN QUEUE",
        due_at=FIXED_NOW - timedelta(days=1),
        requires_acknowledgement=True,
        created_at=FIXED_NOW - timedelta(days=2),
        updated_at=FIXED_NOW - timedelta(days=2),
    )
    required_recipient = StudentUpdateRecipient(
        id=uuid.uuid4(),
        student_update_id=required_update.id,
        student_id=seed.student.id,
        class_enrollment_id=seed.placement.id,
        status=StudentUpdateStatus.ASSIGNED,
    )
    db_session.add_all([required_update, required_recipient])
    await db_session.flush()
    db_session.add(
        GuardianUpdateState(
            id=uuid.uuid4(),
            recipient_id=required_recipient.id,
            guardian_workos_user_id="guardian_one",
            acknowledged_at=FIXED_NOW - timedelta(hours=2),
        )
    )

    optional_update = StudentUpdate(
        id=uuid.uuid4(),
        organization_id=organization_id,
        classroom_id=seed.classroom.id,
        teacher_workos_user_id="user_teacher",
        target_type=StudentUpdateTargetType.CLASSROOM,
        title="Optional update",
        body="OPTIONAL MESSAGE BODY",
        due_at=FIXED_NOW - timedelta(days=1),
        requires_acknowledgement=False,
        created_at=FIXED_NOW - timedelta(days=1),
        updated_at=FIXED_NOW - timedelta(days=1),
    )
    optional_recipient = StudentUpdateRecipient(
        id=uuid.uuid4(),
        student_update_id=optional_update.id,
        student_id=seed.student.id,
        class_enrollment_id=seed.placement.id,
        status=StudentUpdateStatus.ASSIGNED,
    )
    db_session.add_all([optional_update, optional_recipient])
    await db_session.flush()

    optional_event = StudentUpdateEvent(
        id=uuid.uuid4(),
        recipient_id=optional_recipient.id,
        event_type=StudentUpdateEventType.ASSIGNED,
        actor_workos_user_id="user_teacher",
        actor_role=StudentUpdateActorRole.TEACHER,
        new_status=StudentUpdateStatus.ASSIGNED,
    )
    db_session.add(optional_event)
    await db_session.flush()
    db_session.add(
        StudentUpdateNotification(
            id=uuid.uuid4(),
            organization_id=organization_id,
            guardian_workos_user_id="guardian_one",
            recipient_id=optional_recipient.id,
            event_id=optional_event.id,
            notification_type=StudentUpdateNotificationType.UPDATE_ASSIGNED,
        )
    )
    await db_session.flush()

    response = await build_needs_review(
        db_session,
        organization_id=organization_id,
        categories=None,
        severities=None,
        date_from=None,
        date_to=None,
        limit=100,
        offset=0,
    )
    categories = [item.category for item in response.items]
    assert categories.count(NeedsReviewCategory.REGISTRATION) == 2
    assert categories.count(NeedsReviewCategory.INVITATION) == 2
    assert categories.count(NeedsReviewCategory.MISSING_ATTENDANCE) == 1
    assert categories.count(NeedsReviewCategory.MISSING_ASSIGNMENT) == 1
    assert categories.count(NeedsReviewCategory.ACKNOWLEDGEMENT) == 1
    assert response.informational_unread_update_count == 1
    assert response.category_counts[NeedsReviewCategory.INVITATION] == 2
    assert response.severity_counts["urgent"] >= 3
    assert response.severity_counts["warning"] >= 2
    assert response.items[0].severity.value == "urgent"
    assert next(item for item in response.items if item.student_name == "Fresh Registration").severity.value == "warning"
    assert next(item for item in response.items if item.student_name == "Boundary Registration").severity.value == "urgent"
    acknowledgement = next(
        item for item in response.items if item.category == NeedsReviewCategory.ACKNOWLEDGEMENT
    )
    assert acknowledgement.outstanding_acknowledgement_count == 1
    assert seed.classroom.name in acknowledgement.title
    assert "PRIVATE MESSAGE BODY" not in response.model_dump_json()
    assert "guardian_one" not in response.model_dump_json()

    page_one = await build_needs_review(
        db_session,
        organization_id=organization_id,
        categories=None,
        severities=None,
        date_from=None,
        date_to=None,
        limit=2,
        offset=0,
    )
    page_two = await build_needs_review(
        db_session,
        organization_id=organization_id,
        categories=None,
        severities=None,
        date_from=None,
        date_to=None,
        limit=2,
        offset=2,
    )
    assert page_one.has_more is True
    assert page_one.next_offset == 2
    assert not {item.id for item in page_one.items} & {item.id for item in page_two.items}

    await cleanup_organization(db_session, organization_id)


@pytest.mark.asyncio
async def test_needs_review_query_is_bounded_and_workos_failure_keeps_items(
    db_session,
    fixed_clock,
    monkeypatch,
):
    organization_id = f"org_needs_review_queries_{uuid.uuid4().hex}"
    seed = await seed_classroom(session=db_session, organization_id=organization_id)
    await db_session.flush()

    statements: list[str] = []

    def count_query(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count_query)
    try:
        monkeypatch.setattr(
            needs_review_services,
            "load_member_summaries",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("WorkOS unavailable")),
        )
        response = await build_needs_review(
            db_session,
            organization_id=organization_id,
            categories={NeedsReviewCategory.MISSING_ATTENDANCE},
            severities=None,
            date_from=date(2026, 9, 3),
            date_to=date(2026, 9, 3),
            limit=50,
            offset=0,
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_query)

    assert response.total_count == 1
    assert response.items[0].teacher_name is None
    assert len(statements) <= 8
    await cleanup_organization(db_session, organization_id)


@pytest.mark.asyncio
async def test_missing_attendance_disappears_after_teacher_submission(
    db_session,
    fixed_clock,
    monkeypatch,
):
    organization_id = f"org_needs_review_flow_{uuid.uuid4().hex}"
    seed = await seed_classroom(session=db_session, organization_id=organization_id)
    await db_session.flush()

    try:
        await db_session.commit()

        def verify_token(token):
            if token == "admin-token":
                return {
                    "sub": "user_admin",
                    "org_id": organization_id,
                    "permissions": ["school:manage"],
                }
            return {
                "sub": seed.teacher_id,
                "org_id": organization_id,
                "role": UserRoles.TEACHER.value,
                "roles": [UserRoles.TEACHER.value],
            }

        monkeypatch.setattr("core.auth.verify_workos_access_token", verify_token)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            before = await client.get(
                "/api/needs-review?category=missing_attendance&date_from=2026-09-03&date_to=2026-09-03",
                headers={"Authorization": "Bearer admin-token"},
            )
            assert before.status_code == 200
            assert before.json()["total_count"] == 1

            submitted = await client.put(
                f"/api/teacher/classrooms/{seed.classroom.id}/attendance/2026-09-03",
                headers={"Authorization": "Bearer teacher-token"},
                json={
                    "entries": [
                        {
                            "placement_id": str(seed.placement.id),
                            "status": AttendanceStatus.PRESENT.value,
                        }
                    ]
                },
            )
            assert submitted.status_code == 200
            assert submitted.json()["submitted"] is True

            after = await client.get(
                "/api/needs-review?category=missing_attendance&date_from=2026-09-03&date_to=2026-09-03",
                headers={"Authorization": "Bearer admin-token"},
            )
            assert after.status_code == 200
            assert after.json()["total_count"] == 0
    finally:
        await cleanup_organization(db_session, organization_id)


@pytest.mark.asyncio
async def test_needs_review_isolation_and_permission_boundary(db_session, fixed_clock, monkeypatch):
    first_org = f"org_needs_review_a_{uuid.uuid4().hex}"
    second_org = f"org_needs_review_b_{uuid.uuid4().hex}"
    first = await seed_classroom(session=db_session, organization_id=first_org)
    second = await seed_classroom(session=db_session, organization_id=second_org)
    for seed, organization_id in ((first, first_org), (second, second_org)):
        db_session.add(
            StudentRegistrationRequest(
                id=uuid.uuid4(),
                guardian_workos_user_id=f"guardian_{organization_id}",
                organization_id=organization_id,
                child_first_name="Scoped",
                child_last_name=organization_id[-4:],
                academic_year_id=seed.year.id,
                status=StudentRegistrationStatus.PENDING,
            )
        )
    await db_session.flush()

    first_response = await build_needs_review(
        db_session,
        organization_id=first_org,
        categories={NeedsReviewCategory.REGISTRATION},
        severities=None,
        date_from=None,
        date_to=None,
        limit=50,
        offset=0,
    )
    second_response = await build_needs_review(
        db_session,
        organization_id=second_org,
        categories={NeedsReviewCategory.REGISTRATION},
        severities=None,
        date_from=None,
        date_to=None,
        limit=50,
        offset=0,
    )
    assert first_response.total_count == second_response.total_count == 1
    assert first_response.items[0].id != second_response.items[0].id

    await db_session.commit()
    monkeypatch.setattr(
        "core.auth.verify_workos_access_token",
        lambda _token: {
            "sub": "user_with_permission",
            "org_id": first_org,
            "permissions": ["school:manage"],
        },
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/needs-review?category=registration&limit=1",
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["items"][0]["category"] == "registration"
    assert "guardian_" not in response.text

    monkeypatch.setattr(
        "core.auth.verify_workos_access_token",
        lambda _token: {
            "sub": "user_without_permission",
            "org_id": first_org,
            "permissions": [],
        },
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/needs-review",
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 403
    await cleanup_organization(db_session, first_org)
    await cleanup_organization(db_session, second_org)


def test_needs_review_time_and_source_contract_boundaries():
    assert _local_cutoff(date(2026, 9, 3), time(10), "Africa/Tunis") == datetime(
        2026, 9, 3, 9, tzinfo=timezone.utc
    )
    start, end = _timestamp_bounds(
        "America/New_York", date(2026, 3, 8), date(2026, 3, 8)
    )
    assert start == datetime(2026, 3, 8, 5, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 9, 4, tzinfo=timezone.utc)
    year = AcademicYear(
        id=uuid.uuid4(),
        organization_id="org",
        name="year",
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 31),
        status=AcademicYearStatus.ACTIVE,
    )
    assert _attendance_window(year, date(2026, 9, 3), date(2026, 9, 4), None) is None
    assert _attendance_window(year, date(2026, 9, 3), None, date(2026, 9, 2))[1] == date(2026, 9, 2)

    settings = SchoolAttendanceSettingsRequest(
        timezone="Africa/Tunis",
        instructional_weekdays=[0, 1, 2, 3, 4],
    )
    assert settings.attendance_cutoff_time == time(10)
    with pytest.raises(ValueError, match="due_at is required"):
        StudentUpdateCreateRequest(
            classroom_id=uuid.uuid4(),
            title="Needs acknowledgement",
            requires_acknowledgement=True,
            target={"type": "classroom"},
        )
