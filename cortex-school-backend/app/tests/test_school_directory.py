"""Admin directory organization boundaries, dated rosters, and attendance math."""
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from core.auth import get_current_user
from core.db import db_session as session_dependency
from modules.academic_years.models import AcademicYear
from modules.attendance.models import AttendanceRecord, AttendanceSubmission
from modules.classrooms.directory import get_school_directory
from modules.classrooms.models import Classroom, ClassEnrollment, TeacherAssignment
from modules.classrooms.router import router
from modules.enrollments.models import Enrollment
from modules.schools.models import Country, School
from modules.students.models import GuardianStudent, Student

TODAY = date(2026, 11, 18)
ADMIN = {"organization_id": "org_directory", "user_id": "user_admin", "claims": {"permissions": ["school:manage"]}}


@pytest_asyncio.fixture
async def school_data(db_session, monkeypatch):
    monkeypatch.setattr("modules.attendance.services.utcnow", lambda: datetime(2026, 11, 18, 10, tzinfo=timezone.utc))
    country = Country(code="TN", name="Tunisia", calling_code="+216")
    db_session.add(country)
    await db_session.flush()
    db_session.add_all([School(organization_id=org, country_code="TN") for org in ["org_directory", "org_foreign"]])
    await db_session.flush()
    year = AcademicYear(id=uuid.uuid4(), organization_id="org_directory", name="2026–2027", starts_on=date(2026, 9, 1), ends_on=date(2027, 6, 30), status="active")
    old = AcademicYear(id=uuid.uuid4(), organization_id="org_directory", name="2025–2026", starts_on=date(2025, 9, 1), ends_on=date(2026, 6, 30), status="closed")
    future = AcademicYear(id=uuid.uuid4(), organization_id="org_directory", name="2027–2028", starts_on=date(2027, 9, 1), ends_on=date(2028, 6, 30), status="draft")
    foreign_year = AcademicYear(id=uuid.uuid4(), organization_id="org_foreign", name="2026–2027", starts_on=year.starts_on, ends_on=year.ends_on, status="active")
    alice = Student(id=uuid.uuid4(), organization_id="org_directory", first_name="Alice", last_name="One")
    bob = Student(id=uuid.uuid4(), organization_id="org_directory", first_name="Bob", last_name="Two")
    carol = Student(id=uuid.uuid4(), organization_id="org_directory", first_name="Carol", last_name="Three")
    foreign = Student(id=uuid.uuid4(), organization_id="org_foreign", first_name="Private", last_name="Foreign")
    db_session.add_all([year, old, future, foreign_year, alice, bob, carol, foreign])
    await db_session.flush()
    classes = [Classroom(id=uuid.uuid4(), academic_year_id=y.id, name=name) for y, name in [(year,"6A"),(year,"6B"),(old,"Old class"),(foreign_year,"Private class"),(future,"Future class")]]
    db_session.add_all(classes)
    enrollments = [Enrollment(id=uuid.uuid4(), student_id=s.id, academic_year_id=y.id) for s,y in [(alice,year),(bob,year),(alice,old),(foreign,foreign_year),(alice,future)]]
    db_session.add_all(enrollments)
    await db_session.flush()
    placements = [
        ClassEnrollment(id=uuid.uuid4(), enrollment_id=enrollments[0].id, classroom_id=classes[0].id, effective_from=year.starts_on, effective_until=TODAY),
        ClassEnrollment(id=uuid.uuid4(), enrollment_id=enrollments[0].id, classroom_id=classes[1].id, effective_from=TODAY),
        ClassEnrollment(id=uuid.uuid4(), enrollment_id=enrollments[2].id, classroom_id=classes[2].id, effective_from=old.starts_on, effective_until=date(2026,7,1)),
        ClassEnrollment(id=uuid.uuid4(), enrollment_id=enrollments[3].id, classroom_id=classes[3].id, effective_from=year.starts_on),
        ClassEnrollment(id=uuid.uuid4(), enrollment_id=enrollments[4].id, classroom_id=classes[4].id, effective_from=future.starts_on),
    ]
    assignments = [TeacherAssignment(id=uuid.uuid4(), classroom_id=classes[1].id, teacher_workos_user_id=user, role=role, effective_from=start, effective_until=end) for user,role,start,end in [
        ("user_ended","lead",year.starts_on,TODAY), ("user_current","lead",TODAY,None),
        ("user_assistant","assistant",year.starts_on,None), ("user_future","assistant",date(2026,12,1),None),
    ]]
    db_session.add_all([*placements, *assignments])
    await db_session.commit()
    return NS(session=db_session, year=year, old=old, future=future, foreign_year=foreign_year, alice=alice, bob=bob, carol=carol, foreign=foreign, classes=classes, placements=placements)


async def record(data, placement, day, status, updated_hour=10):
    submission = AttendanceSubmission(id=uuid.uuid4(), classroom_id=placement.classroom_id, school_date=day, submitted_by_workos_user_id="user_teacher", updated_by_workos_user_id="user_teacher", submitted_at=datetime(2026,11,18,10,tzinfo=timezone.utc))
    data.session.add(submission)
    await data.session.flush()
    data.session.add(AttendanceRecord(submission_id=submission.id, class_enrollment_id=placement.id, school_date=day, status=status, updated_by_workos_user_id="user_teacher", updated_at=datetime(2026,11,18,updated_hour,tzinfo=timezone.utc)))
    await data.session.commit()


@pytest.mark.asyncio
async def test_rosters_follow_transfer_and_assignment_exclusive_end_dates(school_data):
    data = school_data
    result = await get_school_directory(data.session, data.year.id, ADMIN)
    assert result.roster_date == TODAY
    assert {s.id for s in result.students} == {data.alice.id, data.bob.id, data.carol.id}
    by_class = {c.name:c for c in result.classrooms}
    assert by_class["6A"].student_ids == []
    assert by_class["6B"].student_ids == [data.alice.id]
    assert {a.teacher_workos_user_id for a in by_class["6B"].teachers} == {"user_current", "user_assistant"}
    alice = next(s for s in result.students if s.id == data.alice.id)
    bob = next(s for s in result.students if s.id == data.bob.id)
    carol = next(s for s in result.students if s.id == data.carol.id)
    assert alice.classroom_id == data.classes[1].id
    assert bob.enrollment_id and bob.classroom_id is None
    assert carol.enrollment_id is None
    assert alice.attendance.rate is None and alice.attendance.recorded_days == 0


@pytest.mark.asyncio
async def test_year_to_date_rate_counts_recorded_days_once_across_transfer(school_data):
    data = school_data
    await record(data, data.placements[0], date(2026,11,16), "present")
    await record(data, data.placements[0], date(2026,11,17), "absent")
    await record(data, data.placements[0], TODAY, "absent", 9)
    await record(data, data.placements[1], TODAY, "late", 11)
    await record(data, data.placements[1], date(2026,11,19), "absent")
    await record(data, data.placements[2], date(2026,6,1), "absent")
    await record(data, data.placements[3], TODAY, "present")
    result = await get_school_directory(data.session, data.year.id, ADMIN)
    attendance = next(s for s in result.students if s.id == data.alice.id).attendance
    assert attendance.recorded_days == 3
    assert (attendance.present, attendance.absent, attendance.late) == (1,1,1)
    assert attendance.rate == pytest.approx(200/3)
    assert result.attendance_from == data.year.starts_on
    assert result.attendance_through == TODAY


@pytest.mark.asyncio
async def test_closed_and_future_years_have_honest_dated_rosters_and_rates(school_data):
    data = school_data
    await record(data, data.placements[2], date(2026,6,1), "excused")
    old = await get_school_directory(data.session, data.old.id, ADMIN)
    assert old.roster_date == old.attendance_through == data.old.ends_on
    alice = next(s for s in old.students if s.id == data.alice.id)
    assert alice.classroom_id == data.classes[2].id
    assert alice.attendance.rate == 0 and alice.attendance.excused == 1
    future = await get_school_directory(data.session, data.future.id, ADMIN)
    assert future.roster_date == data.future.starts_on
    assert future.attendance_through is None
    assert next(s for s in future.students if s.id == data.alice.id).attendance.rate is None


@pytest.mark.asyncio
async def test_foreign_year_cannot_be_read(school_data):
    with pytest.raises(HTTPException) as error:
        await get_school_directory(school_data.session, school_data.foreign_year.id, ADMIN)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_endpoint_requires_admin_permission_and_returns_typed_directory(school_data):
    app = FastAPI(); app.include_router(router)
    user = {**ADMIN, "claims": {"permissions": []}}
    app.dependency_overrides[get_current_user] = lambda: user
    async def session_override():
        yield school_data.session
    app.dependency_overrides[session_dependency] = session_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path = f"/academic-years/{school_data.year.id}/directory/"
        assert (await client.get(path)).status_code == 403
        user["claims"]["permissions"] = ["school:manage"]
        response = await client.get(path)
        assert response.status_code == 200, response.text
        assert len(response.json()["classrooms"]) == 2
        assert len(response.json()["students"]) == 3


@pytest.mark.asyncio
async def test_guardian_links_and_member_relationships_are_scoped_and_current(school_data):
    from modules.members.services import enrich_member_relationships
    data = school_data
    data.session.add_all([
        GuardianStudent(student_id=student.id, guardian_workos_user_id="user_guardian")
        for student in [data.alice, data.bob, data.foreign]
    ])
    data.session.add(TeacherAssignment(classroom_id=data.classes[3].id, teacher_workos_user_id="user_current", role="lead", effective_from=data.year.starts_on))
    await data.session.commit()
    directory = await get_school_directory(data.session, data.year.id, ADMIN)
    assert next(s for s in directory.students if s.id == data.alice.id).guardian_ids == ["user_guardian"]
    assert next(s for s in directory.students if s.id == data.carol.id).guardian_ids == []
    members = [{"id": id, "membership_id": f"membership_{id}", "name": id, "email": "person@example.test", "roles": roles, "status": "active"} for id,roles in [("user_guardian",["guardian"]),("user_current",["teacher"]),("user_ended",["teacher"])]]
    enriched = {member["id"]:member for member in await enrich_member_relationships(data.session, "org_directory", members)}
    assert {child["id"] for child in enriched["user_guardian"]["children"]} == {data.alice.id, data.bob.id}
    assert [c["name"] for c in enriched["user_current"]["classrooms"]] == ["6B"]
    assert enriched["user_current"]["classrooms"][0]["academic_year_id"] == data.year.id
    assert enriched["user_ended"]["classrooms"] == []


@pytest.mark.asyncio
async def test_student_and_member_endpoints_return_linked_relationships(school_data, monkeypatch):
    from unittest.mock import AsyncMock
    from modules.members.router import router as members_router
    from modules.students.router import router as students_router
    data = school_data
    data.session.add(GuardianStudent(student_id=data.alice.id, guardian_workos_user_id="user_guardian"))
    await data.session.commit()
    monkeypatch.setattr("modules.members.router.list_school_members", AsyncMock(return_value=[{
        "id":"user_guardian", "membership_id":"membership_guardian", "name":"Parent One",
        "email":"parent@example.test", "roles":["guardian"], "status":"active",
    }]))
    app = FastAPI(); app.include_router(members_router); app.include_router(students_router)
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    async def session_override():
        yield data.session
    app.dependency_overrides[session_dependency] = session_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        members = await client.get("/members/")
        assert members.status_code == 200, members.text
        assert members.json()[0]["children"] == [{"id":str(data.alice.id), "name":"Alice One"}]
        students = (await client.get("/students/")).json()
        assert next(s for s in students if s["id"] == str(data.alice.id))["guardian_ids"] == ["user_guardian"]
        detail = await client.get(f"/students/{data.alice.id}/")
        assert detail.json()["guardian_ids"] == ["user_guardian"]
        updated = await client.patch(f"/students/{data.alice.id}/", json={"first_name":"Updated"})
        assert updated.json()["guardian_ids"] == ["user_guardian"]
        assert (await client.get(f"/students/{data.foreign.id}/")).status_code == 404
