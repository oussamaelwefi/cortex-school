from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import update

from main import app
from modules.analytics import services
from modules.attendance.models import AttendanceRecord, AttendanceStatus, AttendanceSubmission
from modules.enrollments.models import Enrollment
from modules.invitations.models import Invitation, InvitationSendStatus
from modules.student_registration.models import StudentRegistrationRequest, StudentRegistrationStatus
from modules.student_updates.models import (
    GuardianUpdateState,
    StudentUpdate,
    StudentUpdateRecipient,
    StudentUpdateTargetType,
)
from modules.students.models import GuardianStudent
from test_needs_review import seed_classroom


@pytest.mark.asyncio
async def test_analytics_compares_school_local_periods_and_scopes_access(db_session, monkeypatch):
    school = await seed_classroom(db_session, organization_id="org_analytics")
    foreign = await seed_classroom(db_session, organization_id="org_other", classroom_name="Other school")
    empty = await seed_classroom(db_session, organization_id="org_empty")
    now = datetime(2026, 11, 15, 23, 20, tzinfo=timezone.utc)  # 16 Nov in Tunis
    current_timestamp = datetime(2026, 11, 9, 23, 15, tzinfo=timezone.utc)
    previous_timestamp = datetime(2026, 11, 9, 21, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(services, "utcnow", lambda: now)
    await db_session.execute(update(Enrollment).values(created_at=previous_timestamp))

    for seeded, school_day, status in [
        (school, date(2026, 11, 10), AttendanceStatus.LATE),
        (school, date(2026, 11, 9), AttendanceStatus.ABSENT),
        (foreign, date(2026, 11, 10), AttendanceStatus.PRESENT),
    ]:
        submission = AttendanceSubmission(
            classroom_id=seeded.classroom.id, school_date=school_day,
            submitted_by_workos_user_id="user_teacher", updated_by_workos_user_id="user_teacher",
            submitted_at=now,
        )
        db_session.add(submission)
        await db_session.flush()
        db_session.add(AttendanceRecord(
            submission_id=submission.id, class_enrollment_id=seeded.placement.id,
            school_date=school_day, status=status, updated_by_workos_user_id="user_teacher",
        ))

    db_session.add_all([
        GuardianStudent(student_id=school.student.id, guardian_workos_user_id="user_guardian"),
        GuardianStudent(student_id=school.student.id, guardian_workos_user_id="user_other_guardian"),
    ])
    notice = StudentUpdate(
        organization_id="org_analytics", classroom_id=school.classroom.id,
        teacher_workos_user_id="user_teacher", target_type=StudentUpdateTargetType.CLASSROOM,
        title="School notice", requires_acknowledgement=True, due_at=previous_timestamp,
        created_at=current_timestamp,
    )
    db_session.add(notice)
    await db_session.flush()
    recipient = StudentUpdateRecipient(
        student_update_id=notice.id, class_enrollment_id=school.placement.id, student_id=school.student.id,
    )
    db_session.add(recipient)
    await db_session.flush()
    db_session.add(GuardianUpdateState(
        recipient_id=recipient.id, guardian_workos_user_id="user_guardian", acknowledged_at=now,
    ))

    for org_id, seeded, request_status, timestamp in [
        ("org_analytics", school, StudentRegistrationStatus.PENDING, current_timestamp),
        ("org_analytics", school, StudentRegistrationStatus.APPROVED, previous_timestamp),
        ("org_other", foreign, StudentRegistrationStatus.PENDING, current_timestamp),
    ]:
        db_session.add(StudentRegistrationRequest(
            organization_id=org_id, guardian_workos_user_id="user_guardian",
            academic_year_id=seeded.year.id, child_first_name="Example", child_last_name="Student",
            status=request_status, created_at=timestamp,
        ))
    db_session.add(Invitation(
        organization_id="org_analytics", email="guardian@example.test",
        send_status=InvitationSendStatus.FAILED, created_at=current_timestamp,
    ))
    await db_session.commit()
    empty_org = empty.year.organization_id

    def claims(token):
        role, organization_id = token.split(":")
        return {
            "sub": f"user_{role}", "org_id": organization_id,
            "permissions": ["school:manage"] if role == "admin" else [],
        }

    monkeypatch.setattr("core.auth.verify_workos_access_token", claims)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path = "/api/analytics/"
        admin = {"Authorization": "Bearer admin:org_analytics"}
        response = await client.get(path, params={"days": 7}, headers=admin)
        assert response.status_code == 200, response.text
        report = response.json()
        assert (report["current"]["start"], report["current"]["end"]) == ("2026-11-10", "2026-11-16")
        assert (report["previous"]["start"], report["previous"]["end"]) == ("2026-11-03", "2026-11-09")
        current, previous = report["current"]["totals"], report["previous"]["totals"]
        assert current["attendance"] == {"present": 0, "late": 1, "absent": 0, "excused": 0, "submissions": 1}
        assert previous["attendance"]["absent"] == 1
        assert current["registrations"]["pending"] == previous["registrations"]["approved"] == 1
        assert current["updates_published"] == current["acknowledgements_received"] == 1
        assert current["acknowledgements_required"] == 2
        assert len(report["trend"]) == 7
        assert report["trend"][0]["totals"] == current
        assert report["trend"][-1]["totals"]["attendance"]["submissions"] == 0
        assert [row["id"] for row in report["classrooms"]] == [str(school.classroom.id)]
        assert report["snapshot"] == {
            "enrolled_students": 1,
            "pending_registrations": 1,
            "updates_with_overdue_acknowledgements": 1,
            "failed_invitations": 1,
        }

        weekly = (await client.get(path, params={"days": 30}, headers=admin)).json()
        assert weekly["current"]["start"] == "2026-10-18"
        assert weekly["trend"][1]["start"] == "2026-10-19"
        assert weekly["trend"][-1]["end"] == "2026-11-16"
        assert sum(bucket["totals"]["updates_published"] for bucket in weekly["trend"]) == 1
        other = await client.get(path, headers={"Authorization": "Bearer admin:org_other"})
        assert other.status_code == 200
        assert other.json()["current"]["totals"]["updates_published"] == 0
        assert other.json()["classrooms"][0]["name"] == "Other school"
        empty_report = await client.get(path, headers={"Authorization": f"Bearer admin:{empty_org}"})
        assert empty_report.status_code == 200
        assert empty_report.json()["classrooms"] == []
        assert (await client.get(path, params={"days": 365}, headers=admin)).status_code == 422
        assert (await client.get(path, headers={"Authorization": "Bearer guardian:org_analytics"})).status_code == 403
        assert (await client.get(path)).status_code == 401
