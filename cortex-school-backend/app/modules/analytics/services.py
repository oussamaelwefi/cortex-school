import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import Date, and_, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import utcnow
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.analytics.schemas import (
    AnalyticsBucket,
    AnalyticsSnapshot,
    AnalyticsTotals,
    AttendanceCounts,
    ClassroomAttendance,
    SchoolAnalyticsResponse,
)
from modules.attendance.models import AttendanceRecord, AttendanceStatus, AttendanceSubmission
from modules.classrooms.models import Classroom
from modules.enrollments.models import Enrollment
from modules.invitations.models import Invitation, InvitationSendStatus
from modules.schools.models import School
from modules.student_registration.models import StudentRegistrationRequest, StudentRegistrationStatus
from modules.student_updates.acknowledgements import overdue_guardian_acknowledgements
from modules.student_updates.models import GuardianUpdateState, StudentUpdate, StudentUpdateRecipient
from modules.students.models import GuardianStudent, Student


def _trend_buckets(period: AnalyticsBucket, *, daily: bool) -> list[AnalyticsBucket]:
    buckets = []
    start = period.start
    while start <= period.end:
        end = start if daily else min(start + timedelta(days=6 - start.weekday()), period.end)
        buckets.append(AnalyticsBucket(start=start, end=end))
        start = end + timedelta(days=1)
    return buckets


async def _attendance_rows(
    session: AsyncSession, organization_id: str, start: date, end: date
):
    record, submission = AttendanceRecord, AttendanceSubmission
    return await session.execute(
        select(
            submission.school_date,
            Classroom.id,
            Classroom.name,
            AcademicYear.name.label("academic_year"),
            *(func.count().filter(record.status == status).label(status.value)
              for status in AttendanceStatus),
            func.count(distinct(submission.id)).label("submissions"),
        )
        .select_from(submission)
        .join(record, record.submission_id == submission.id)
        .join(Classroom, Classroom.id == submission.classroom_id)
        .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
        .where(
            AcademicYear.organization_id == organization_id,
            submission.school_date.between(start, end),
        )
        .group_by(submission.school_date, Classroom.id, Classroom.name, AcademicYear.name)
        .order_by(Classroom.name, AcademicYear.name, Classroom.id)
    )


async def _communication_rows(
    session: AsyncSession, organization_id: str, start: datetime, as_of: datetime
):
    update, recipient, state = StudentUpdate, StudentUpdateRecipient, GuardianUpdateState
    day = cast(func.timezone(start.tzinfo.key, update.created_at), Date)
    return await session.execute(
        select(
            day.label("school_date"),
            func.count(distinct(update.id)).label("published"),
            func.count(GuardianStudent.id).label("required"),
            func.count(state.id).filter(state.acknowledged_at <= as_of).label("received"),
        )
        .select_from(update)
        .outerjoin(recipient, and_(
            update.requires_acknowledgement.is_(True),
            recipient.student_update_id == update.id,
        ))
        .outerjoin(Student, and_(Student.id == recipient.student_id, Student.organization_id == organization_id))
        .outerjoin(GuardianStudent, GuardianStudent.student_id == Student.id)
        .outerjoin(state, and_(
            state.recipient_id == recipient.id,
            state.guardian_workos_user_id == GuardianStudent.guardian_workos_user_id,
        ))
        .where(
            update.organization_id == organization_id,
            update.created_at >= start,
            update.created_at <= as_of,
        )
        .group_by(day)
    )


async def _registration_rows(
    session: AsyncSession, organization_id: str, start: datetime, as_of: datetime
):
    request = StudentRegistrationRequest
    day = cast(func.timezone(start.tzinfo.key, request.created_at), Date)
    return await session.execute(
        select(day.label("school_date"), request.status, func.count().label("requests"))
        .where(
            request.organization_id == organization_id,
            request.created_at >= start,
            request.created_at <= as_of,
        )
        .group_by(day, request.status)
    )


async def _current_snapshot(
    session: AsyncSession, organization_id: str, today: date, as_of: datetime
) -> AnalyticsSnapshot:
    enrolled = (
        select(func.count(distinct(Enrollment.student_id)))
        .join(AcademicYear, AcademicYear.id == Enrollment.academic_year_id)
        .join(Student, Student.id == Enrollment.student_id)
        .where(
            AcademicYear.organization_id == organization_id,
            Student.organization_id == organization_id,
            AcademicYear.status == AcademicYearStatus.ACTIVE,
            AcademicYear.starts_on <= today,
            AcademicYear.ends_on >= today,
            Enrollment.created_at <= as_of,
        )
    )
    pending = select(func.count(StudentRegistrationRequest.id)).where(
        StudentRegistrationRequest.organization_id == organization_id,
        StudentRegistrationRequest.status == StudentRegistrationStatus.PENDING,
        StudentRegistrationRequest.created_at <= as_of,
    )
    overdue = overdue_guardian_acknowledgements(
        select(func.count(distinct(StudentUpdate.id))).select_from(StudentUpdate),
        organization_id,
        as_of,
    )
    failed_invitations = select(func.count(Invitation.id)).where(
        Invitation.organization_id == organization_id,
        Invitation.send_status == InvitationSendStatus.FAILED,
        Invitation.created_at <= as_of,
    )
    row = (await session.execute(select(
        enrolled.scalar_subquery().label("enrolled_students"),
        pending.scalar_subquery().label("pending_registrations"),
        overdue.scalar_subquery().label("updates_with_overdue_acknowledgements"),
        failed_invitations.scalar_subquery().label("failed_invitations"),
    ))).one()
    return AnalyticsSnapshot(**row._mapping)


async def build_school_analytics(
    session: AsyncSession, organization_id: str, *, days: int
) -> SchoolAnalyticsResponse:
    school = await session.get(School, organization_id)
    if school is None:
        raise HTTPException(404, "School not found")
    try:
        timezone = ZoneInfo(school.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(500, "School timezone is invalid") from exc

    as_of = utcnow()
    today = as_of.astimezone(timezone).date()
    current = AnalyticsBucket(start=today - timedelta(days=days - 1), end=today)
    previous = AnalyticsBucket(
        start=current.start - timedelta(days=days),
        end=current.start - timedelta(days=1),
    )
    trend = _trend_buckets(current, daily=days == 7)
    buckets_by_day = {
        bucket.start + timedelta(days=offset): bucket
        for bucket in trend
        for offset in range((bucket.end - bucket.start).days + 1)
    }
    classrooms: dict[uuid.UUID, ClassroomAttendance] = {}

    def aggregates(day: date) -> tuple[AnalyticsTotals, ...]:
        bucket = buckets_by_day.get(day)
        return (current.totals, bucket.totals) if bucket else (previous.totals,)

    for row in await _attendance_rows(session, organization_id, previous.start, today):
        counts = AttendanceCounts(
            present=row.present, late=row.late, absent=row.absent,
            excused=row.excused, submissions=row.submissions,
        )
        for totals in aggregates(row.school_date):
            totals.attendance.add(counts)
        if row.school_date >= current.start:
            if row.id not in classrooms:
                classrooms[row.id] = ClassroomAttendance(
                    id=row.id, name=row.name, academic_year=row.academic_year,
                )
            classrooms[row.id].attendance.add(counts)

    start = datetime.combine(previous.start, time.min, tzinfo=timezone)
    for row in await _communication_rows(session, organization_id, start, as_of):
        for totals in aggregates(row.school_date):
            totals.updates_published += row.published
            totals.acknowledgements_required += row.required
            totals.acknowledgements_received += row.received

    for row in await _registration_rows(session, organization_id, start, as_of):
        for totals in aggregates(row.school_date):
            status = row.status.value
            setattr(totals.registrations, status, getattr(totals.registrations, status) + row.requests)

    return SchoolAnalyticsResponse(
        current=current,
        previous=previous,
        trend=trend,
        classrooms=list(classrooms.values()),
        snapshot=await _current_snapshot(session, organization_id, today, as_of),
    )
