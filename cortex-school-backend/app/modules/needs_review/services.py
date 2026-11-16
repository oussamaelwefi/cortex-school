import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import utcnow
from modules.academic_years.models import (
    AcademicCalendar,
    AcademicYear,
    AcademicYearStatus,
    CalendarEntry,
)
from modules.attendance.models import AttendanceSubmission
from modules.attendance.services import EXCLUDED_CALENDAR_ENTRY_TYPES
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
)
from modules.members.services import load_member_summaries
from modules.needs_review.schemas import (
    AssignmentAction,
    AttendanceAction,
    InvitationAction,
    NeedsReviewCategory,
    NeedsReviewItem,
    NeedsReviewResponse,
    NeedsReviewSeverity,
    RegistrationAction,
    StudentUpdateAction,
)
from modules.schools.models import School
from modules.student_registration.models import (
    StudentRegistrationRequest,
    StudentRegistrationStatus,
)
from modules.student_updates.acknowledgements import overdue_guardian_acknowledgements
from modules.student_updates.models import (
    StudentUpdate,
    StudentUpdateNotification,
    StudentUpdateRecipient,
)
from modules.students.models import GuardianStudent, Student


REGISTRATION_URGENT_AFTER = timedelta(days=2)
INVITATION_STALE_AFTER = timedelta(days=3)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Candidate:
    item: NeedsReviewItem
    teacher_user_id: str | None = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _local_cutoff(
    school_date: date,
    cutoff_time: time,
    timezone_name: str,
) -> datetime:
    timezone_info = ZoneInfo(timezone_name)
    return datetime.combine(school_date, cutoff_time, timezone_info).astimezone(
        timezone.utc
    )


def _timestamp_bounds(
    timezone_name: str,
    date_from: date | None,
    date_to: date | None,
) -> tuple[datetime | None, datetime | None]:
    timezone_info = ZoneInfo(timezone_name)
    start = (
        datetime.combine(date_from, time.min, timezone_info).astimezone(timezone.utc)
        if date_from is not None
        else None
    )
    end = (
        datetime.combine(
            date_to + timedelta(days=1), time.min, timezone_info
        ).astimezone(timezone.utc)
        if date_to is not None
        else None
    )
    return start, end


async def _get_school(session: AsyncSession, organization_id: str) -> School:
    school = await session.get(School, organization_id)
    if school is None:
        raise LookupError("School not found")
    return school


async def _get_active_year(
    session: AsyncSession,
    organization_id: str,
    school_date: date,
) -> AcademicYear | None:
    return await session.scalar(
        select(AcademicYear)
        .where(
            AcademicYear.organization_id == organization_id,
            AcademicYear.status == AcademicYearStatus.ACTIVE,
            AcademicYear.starts_on <= school_date,
            AcademicYear.ends_on >= school_date,
        )
        .order_by(AcademicYear.starts_on.desc(), AcademicYear.id)
        .limit(1)
    )


async def _instructional_dates(
    session: AsyncSession,
    year: AcademicYear,
    school: School,
    start: date,
    end: date,
) -> list[date]:
    excluded_ranges = list(
        (
            await session.execute(
                select(CalendarEntry.starts_on, CalendarEntry.ends_on)
                .join(
                    AcademicCalendar,
                    AcademicCalendar.id == CalendarEntry.academic_calendar_id,
                )
                .where(
                    AcademicCalendar.academic_year_id == year.id,
                    CalendarEntry.entry_type.in_(EXCLUDED_CALENDAR_ENTRY_TYPES),
                    CalendarEntry.ends_on >= start,
                    CalendarEntry.starts_on <= end,
                )
            )
        ).all()
    )
    weekdays = set(school.instructional_weekdays)
    result: list[date] = []
    current = start
    while current <= end:
        is_excluded = any(
            starts_on <= current <= ends_on
            for starts_on, ends_on in excluded_ranges
        )
        if current.weekday() in weekdays and not is_excluded:
            result.append(current)
        current += timedelta(days=1)
    return result


def _attendance_window(
    year: AcademicYear | None,
    school_date: date,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date] | None:
    if year is None:
        return None
    start = max(year.starts_on, date_from or year.starts_on)
    end = min(year.ends_on, date_to or school_date, school_date)
    if start > end:
        return None
    return start, end


async def _attendance_candidates(
    session: AsyncSession,
    organization_id: str,
    school: School,
    year: AcademicYear | None,
    school_date: date,
    local_now: datetime,
    date_from: date | None,
    date_to: date | None,
) -> list[_Candidate]:
    window = _attendance_window(year, school_date, date_from, date_to)
    if year is None or window is None:
        return []
    start, end = window
    instructional_dates = await _instructional_dates(
        session, year, school, start, end
    )
    if not instructional_dates:
        return []

    placement_rows = (
        await session.execute(
            select(
                Classroom.id,
                Classroom.name,
                ClassEnrollment.effective_from,
                ClassEnrollment.effective_until,
            )
            .join(Enrollment, Enrollment.id == ClassEnrollment.enrollment_id)
            .join(Student, Student.id == Enrollment.student_id)
            .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
            .where(
                Classroom.academic_year_id == year.id,
                Student.organization_id == organization_id,
                Enrollment.academic_year_id == year.id,
                ClassEnrollment.effective_from <= end,
                or_(
                    ClassEnrollment.effective_until.is_(None),
                    ClassEnrollment.effective_until > start,
                ),
            )
        )
    ).all()
    if not placement_rows:
        return []

    classroom_names = {classroom_id: name for classroom_id, name, _, _ in placement_rows}
    roster_intervals: dict[object, list[tuple[date, date | None]]] = {}
    for classroom_id, _, effective_from, effective_until in placement_rows:
        roster_intervals.setdefault(classroom_id, []).append(
            (effective_from, effective_until)
        )

    roster_pairs: set[tuple[object, date]] = set()
    for classroom_id, intervals in roster_intervals.items():
        for instructional_date in instructional_dates:
            if any(
                effective_from <= instructional_date
                and (
                    effective_until is None
                    or instructional_date < effective_until
                )
                for effective_from, effective_until in intervals
            ):
                roster_pairs.add((classroom_id, instructional_date))

    assignment_rows = (
        await session.execute(
            select(
                TeacherAssignment.classroom_id,
                TeacherAssignment.teacher_workos_user_id,
                TeacherAssignment.role,
                TeacherAssignment.effective_from,
                TeacherAssignment.effective_until,
            )
            .join(Classroom, Classroom.id == TeacherAssignment.classroom_id)
            .where(
                Classroom.academic_year_id == year.id,
                TeacherAssignment.effective_from <= end,
                or_(
                    TeacherAssignment.effective_until.is_(None),
                    TeacherAssignment.effective_until > start,
                ),
            )
        )
    ).all()
    assignment_by_pair: dict[tuple[object, date], list[tuple[str, TeacherAssignmentRole]]] = {}
    for classroom_id, teacher_id, role, effective_from, effective_until in assignment_rows:
        for instructional_date in instructional_dates:
            if effective_from <= instructional_date and (
                effective_until is None or instructional_date < effective_until
            ):
                assignment_by_pair.setdefault(
                    (classroom_id, instructional_date), []
                ).append((teacher_id, role))

    classroom_ids = list(classroom_names)
    submitted_pairs = {
        (classroom_id, submitted_date)
        for classroom_id, submitted_date in (
            await session.execute(
                select(
                    AttendanceSubmission.classroom_id,
                    AttendanceSubmission.school_date,
                )
                .join(Classroom, Classroom.id == AttendanceSubmission.classroom_id)
                .where(
                    Classroom.academic_year_id == year.id,
                    AttendanceSubmission.classroom_id.in_(classroom_ids),
                    AttendanceSubmission.school_date >= start,
                    AttendanceSubmission.school_date <= end,
                )
            )
        ).all()
    }

    missing_assignment_dates: dict[object, list[date]] = {}
    candidates: list[_Candidate] = []
    for classroom_id, instructional_date in sorted(roster_pairs, key=lambda pair: (pair[1], str(pair[0]))):
        assignments = assignment_by_pair.get((classroom_id, instructional_date), [])
        if not assignments:
            missing_assignment_dates.setdefault(classroom_id, []).append(
                instructional_date
            )
            continue

        cutoff_at = _local_cutoff(
            instructional_date,
            school.attendance_cutoff_time,
            school.timezone,
        )
        if (
            instructional_date == school_date
            and local_now.time().replace(tzinfo=None)
            < school.attendance_cutoff_time
        ):
            continue
        if (classroom_id, instructional_date) in submitted_pairs:
            continue

        lead_first = sorted(
            assignments,
            key=lambda assignment: (
                assignment[1] != TeacherAssignmentRole.LEAD,
                assignment[0],
            ),
        )[0]
        candidates.append(
            _Candidate(
                item=NeedsReviewItem(
                    id=f"missing_attendance:{classroom_id}:{instructional_date.isoformat()}",
                    category=NeedsReviewCategory.MISSING_ATTENDANCE,
                    severity=NeedsReviewSeverity.URGENT,
                    title=f"{classroom_names[classroom_id]} attendance is missing",
                    reason="Attendance has not been submitted after the school cutoff.",
                    occurred_at=cutoff_at,
                    due_at=cutoff_at,
                    school_date=instructional_date,
                    classroom_name=classroom_names[classroom_id],
                    academic_year_name=year.name,
                    teacher_name=None,
                    action=AttendanceAction(
                        type="attendance",
                        classroom_id=classroom_id,
                        school_date=instructional_date,
                    ),
                ),
                teacher_user_id=lead_first[0],
            )
        )

    for classroom_id, dates in missing_assignment_dates.items():
        first_date = min(dates)
        cutoff_at = _local_cutoff(
            first_date,
            school.attendance_cutoff_time,
            school.timezone,
        )
        candidates.append(
            _Candidate(
                item=NeedsReviewItem(
                    id=f"missing_assignment:{classroom_id}",
                    category=NeedsReviewCategory.MISSING_ASSIGNMENT,
                    severity=NeedsReviewSeverity.URGENT,
                    title=f"{classroom_names[classroom_id]} needs a teacher assignment",
                    reason=(
                        "No active teacher assignment owns attendance for "
                        f"{first_date.isoformat()}."
                    ),
                    occurred_at=cutoff_at,
                    due_at=cutoff_at,
                    school_date=first_date,
                    classroom_name=classroom_names[classroom_id],
                    academic_year_name=year.name,
                    affected_date_count=len(dates),
                    action=AssignmentAction(
                        type="classroom_assignment",
                        academic_year_id=year.id,
                        classroom_id=classroom_id,
                    ),
                )
            )
        )
    return candidates


async def _registration_candidates(
    session: AsyncSession,
    organization_id: str,
    timezone_name: str,
    date_from: date | None,
    date_to: date | None,
    as_of: datetime,
) -> list[_Candidate]:
    start, end = _timestamp_bounds(timezone_name, date_from, date_to)
    query = (
        select(StudentRegistrationRequest, AcademicYear)
        .join(AcademicYear, AcademicYear.id == StudentRegistrationRequest.academic_year_id)
        .where(
            StudentRegistrationRequest.organization_id == organization_id,
            StudentRegistrationRequest.status == StudentRegistrationStatus.PENDING,
        )
        .order_by(StudentRegistrationRequest.created_at, StudentRegistrationRequest.id)
    )
    if start is not None:
        query = query.where(StudentRegistrationRequest.created_at >= start)
    if end is not None:
        query = query.where(StudentRegistrationRequest.created_at < end)

    candidates: list[_Candidate] = []
    for request, year in (await session.execute(query)).all():
        created_at = _as_utc(request.created_at)
        urgent = as_of - created_at >= REGISTRATION_URGENT_AFTER
        candidates.append(
            _Candidate(
                item=NeedsReviewItem(
                    id=f"registration:{request.id}",
                    category=NeedsReviewCategory.REGISTRATION,
                    severity=(
                        NeedsReviewSeverity.URGENT
                        if urgent
                        else NeedsReviewSeverity.WARNING
                    ),
                    title=(
                        "Registration request for "
                        f"{request.child_first_name} {request.child_last_name}"
                    ),
                    reason=(
                        "Waiting for school review."
                        if not urgent
                        else "Waiting for school review beyond the response window."
                    ),
                    occurred_at=created_at,
                    due_at=created_at + REGISTRATION_URGENT_AFTER,
                    school_date=created_at.astimezone(
                        ZoneInfo(timezone_name)
                    ).date(),
                    student_name=(
                        f"{request.child_first_name} {request.child_last_name}"
                    ),
                    academic_year_name=year.name,
                    action=RegistrationAction(
                        type="registration_request",
                        request_id=request.id,
                    ),
                )
            )
        )
    return candidates


async def _invitation_candidates(
    session: AsyncSession,
    organization_id: str,
    timezone_name: str,
    date_from: date | None,
    date_to: date | None,
    as_of: datetime,
) -> list[_Candidate]:
    start, end = _timestamp_bounds(timezone_name, date_from, date_to)
    stale_cutoff = as_of - INVITATION_STALE_AFTER
    query = (
        select(Invitation)
        .where(
            Invitation.organization_id == organization_id,
            or_(
                Invitation.send_status == InvitationSendStatus.FAILED,
                func.lower(Invitation.workos_state).in_(("expired", "revoked")),
                Invitation.expires_at <= as_of,
                and_(
                    Invitation.expires_at.is_(None),
                    Invitation.sent_at.is_not(None),
                    Invitation.sent_at
                    + Invitation.expires_in_days * text("INTERVAL '1 day'")
                    <= as_of,
                ),
                and_(
                    Invitation.sent_at.is_not(None),
                    Invitation.sent_at <= stale_cutoff,
                ),
            ),
        )
        .order_by(Invitation.created_at, Invitation.id)
    )
    source_timestamp = func.coalesce(Invitation.sent_at, Invitation.created_at)
    if start is not None:
        query = query.where(source_timestamp >= start)
    if end is not None:
        query = query.where(source_timestamp < end)

    candidates: list[_Candidate] = []
    for invitation in (await session.scalars(query)).all():
        state = (invitation.workos_state or "").lower()
        if state == "accepted":
            continue
        created_at = _as_utc(invitation.sent_at or invitation.created_at)
        expires_at = invitation.expires_at
        if expires_at is None and invitation.sent_at is not None:
            expires_at = invitation.sent_at + timedelta(
                days=invitation.expires_in_days
            )
        expires_at = _as_utc(expires_at) if expires_at is not None else None
        failed = invitation.send_status == InvitationSendStatus.FAILED
        expired = state in {"expired", "revoked"} or (
            expires_at is not None and expires_at <= as_of
        )
        stale = created_at <= stale_cutoff and (
            invitation.sent_at is not None
            or invitation.workos_invitation_id is not None
            or invitation.send_status == InvitationSendStatus.SENT
        )
        if not (failed or expired or stale):
            continue

        if failed:
            severity = NeedsReviewSeverity.URGENT
            reason = "Sending the invitation failed."
            due_at = None
        elif expired:
            severity = NeedsReviewSeverity.URGENT
            reason = "The invitation is expired or revoked."
            due_at = expires_at
        else:
            severity = NeedsReviewSeverity.WARNING
            reason = "The invitation has not been accepted within the response window."
            due_at = created_at + INVITATION_STALE_AFTER

        candidates.append(
            _Candidate(
                item=NeedsReviewItem(
                    id=f"invitation:{invitation.id}",
                    category=NeedsReviewCategory.INVITATION,
                    severity=severity,
                    title=f"Invitation for {invitation.email}",
                    reason=reason,
                    occurred_at=created_at,
                    due_at=due_at,
                    school_date=created_at.astimezone(
                        ZoneInfo(timezone_name)
                    ).date(),
                    invitation_email=invitation.email,
                    invitation_role=invitation.role_slug,
                    action=InvitationAction(
                        type="invitation",
                        invitation_id=invitation.id,
                    ),
                )
            )
        )
    return candidates


async def _acknowledgement_candidates(
    session: AsyncSession,
    organization_id: str,
    timezone_name: str,
    date_from: date | None,
    date_to: date | None,
    as_of: datetime,
) -> list[_Candidate]:
    start, end = _timestamp_bounds(timezone_name, date_from, date_to)
    query = overdue_guardian_acknowledgements(
        select(
            StudentUpdate,
            Classroom,
            func.count(
                func.distinct(GuardianStudent.guardian_workos_user_id)
            ).label("outstanding_count"),
        ).select_from(StudentUpdate)
        .join(Classroom, Classroom.id == StudentUpdate.classroom_id),
        organization_id,
        as_of,
    ).group_by(StudentUpdate.id, Classroom.id).order_by(StudentUpdate.due_at, StudentUpdate.id)
    if start is not None:
        query = query.where(StudentUpdate.due_at >= start)
    if end is not None:
        query = query.where(StudentUpdate.due_at < end)

    candidates: list[_Candidate] = []
    for update, classroom, outstanding_count in (await session.execute(query)).all():
        due_at = _as_utc(update.due_at)
        candidates.append(
            _Candidate(
                item=NeedsReviewItem(
                    id=f"acknowledgement:{update.id}",
                    category=NeedsReviewCategory.ACKNOWLEDGEMENT,
                    severity=NeedsReviewSeverity.URGENT,
                    title=f"Acknowledgement overdue for {classroom.name}",
                    reason=(
                        f"{outstanding_count} guardian acknowledgement"
                        f"{'' if outstanding_count == 1 else 's'} remain outstanding."
                    ),
                    occurred_at=due_at,
                    due_at=due_at,
                    school_date=due_at.astimezone(
                        ZoneInfo(timezone_name)
                    ).date(),
                    classroom_name=classroom.name,
                    outstanding_acknowledgement_count=int(outstanding_count),
                    action=StudentUpdateAction(
                        type="student_update",
                        update_id=update.id,
                    ),
                )
            )
        )
    return candidates


async def _informational_unread_count(
    session: AsyncSession,
    organization_id: str,
    timezone_name: str,
    date_from: date | None,
    date_to: date | None,
) -> int:
    start, end = _timestamp_bounds(timezone_name, date_from, date_to)
    query = (
        select(func.count(func.distinct(StudentUpdate.id)))
        .join(
            StudentUpdateRecipient,
            StudentUpdateRecipient.student_update_id == StudentUpdate.id,
        )
        .join(
            StudentUpdateNotification,
            StudentUpdateNotification.recipient_id == StudentUpdateRecipient.id,
        )
        .where(
            StudentUpdate.organization_id == organization_id,
            StudentUpdate.requires_acknowledgement.is_(False),
            StudentUpdateNotification.read_at.is_(None),
        )
    )
    if start is not None:
        query = query.where(StudentUpdateNotification.created_at >= start)
    if end is not None:
        query = query.where(StudentUpdateNotification.created_at < end)
    return int(await session.scalar(query) or 0)


def _sort_key(candidate: _Candidate) -> tuple[int, datetime, str, str]:
    item = candidate.item
    sort_at = item.due_at or item.occurred_at or datetime.max.replace(
        tzinfo=timezone.utc
    )
    severity_rank = 0 if item.severity == NeedsReviewSeverity.URGENT else 1
    return severity_rank, _as_utc(sort_at), item.category.value, item.id


async def build_needs_review(
    session: AsyncSession,
    *,
    organization_id: str | None,
    categories: set[NeedsReviewCategory] | None,
    severities: set[NeedsReviewSeverity] | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> NeedsReviewResponse:
    if not organization_id:
        raise ValueError("Authenticated user must belong to an organization")

    as_of = utcnow()
    school = await _get_school(session, organization_id)
    try:
        timezone_info = ZoneInfo(school.timezone)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError("School timezone is not a valid IANA timezone") from exc
    local_now = as_of.astimezone(timezone_info)
    school_date = local_now.date()
    active_year = await _get_active_year(session, organization_id, school_date)

    selected_categories = categories or set(NeedsReviewCategory)
    candidates: list[_Candidate] = []
    if NeedsReviewCategory.REGISTRATION in selected_categories:
        candidates.extend(
            await _registration_candidates(
                session,
                organization_id,
                school.timezone,
                date_from,
                date_to,
                as_of,
            )
        )
    if NeedsReviewCategory.INVITATION in selected_categories:
        candidates.extend(
            await _invitation_candidates(
                session,
                organization_id,
                school.timezone,
                date_from,
                date_to,
                as_of,
            )
        )
    if (
        NeedsReviewCategory.MISSING_ATTENDANCE in selected_categories
        or NeedsReviewCategory.MISSING_ASSIGNMENT in selected_categories
    ):
        attendance_candidates = await _attendance_candidates(
            session,
            organization_id,
            school,
            active_year,
            school_date,
            local_now,
            date_from,
            date_to,
        )
        candidates.extend(
            candidate
            for candidate in attendance_candidates
            if candidate.item.category in selected_categories
        )
    if NeedsReviewCategory.ACKNOWLEDGEMENT in selected_categories:
        candidates.extend(
            await _acknowledgement_candidates(
                session,
                organization_id,
                school.timezone,
                date_from,
                date_to,
                as_of,
            )
        )

    if severities:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.item.severity in severities
        ]

    candidates.sort(key=_sort_key)
    category_counts = {category: 0 for category in NeedsReviewCategory}
    severity_counts = {severity: 0 for severity in NeedsReviewSeverity}
    for candidate in candidates:
        category_counts[candidate.item.category] += 1
        severity_counts[candidate.item.severity] += 1

    visible_candidates = candidates[offset : offset + limit]
    teacher_ids = {
        candidate.teacher_user_id
        for candidate in visible_candidates
        if candidate.teacher_user_id is not None
    }
    try:
        teacher_summaries = await load_member_summaries(
            organization_id,
            teacher_ids,
            tolerate_errors=True,
        )
    except Exception:
        logger.warning("needs_review_member_enrichment_unavailable", exc_info=True)
        teacher_summaries = {}
    items = [
        candidate.item.model_copy(
            update={
                "teacher_name": (
                    teacher_summaries[candidate.teacher_user_id].name
                    if candidate.teacher_user_id in teacher_summaries
                    else candidate.item.teacher_name
                )
            }
        )
        for candidate in visible_candidates
    ]
    total_count = len(candidates)
    next_offset = offset + limit if offset + limit < total_count else None

    return NeedsReviewResponse(
        as_of=as_of,
        school_date=school_date,
        attendance_cutoff_time=school.attendance_cutoff_time,
        total_count=total_count,
        category_counts=category_counts,
        severity_counts=severity_counts,
        informational_unread_update_count=await _informational_unread_count(
            session,
            organization_id,
            school.timezone,
            date_from,
            date_to,
        ),
        limit=limit,
        offset=offset,
        has_more=next_offset is not None,
        next_offset=next_offset,
        items=items,
    )
