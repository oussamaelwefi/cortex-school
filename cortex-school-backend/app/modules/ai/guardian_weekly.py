import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.openrouter import (
    OpenRouterNotConfiguredError,
    get_guardian_weekly_explanation_chain,
)
from core.config import settings
from core.db import utcnow
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.ai.schemas import (
    GuardianWeeklyAttendance,
    GuardianWeeklyAttendanceCounts,
    GuardianWeeklyExplanationModelResult,
    GuardianWeeklyExplanationResponse,
    GuardianWeeklyExplanationSource,
    GuardianWeeklyExplanationText,
    TeacherDraftLanguage,
)
from modules.ai.services import (
    RateLimitExceededError,
    RateLimitUnavailableError,
    _contains_unsafe_text,
    _consume_rate_limit,
    _extract_chain_result,
    _safe_error_category,
)
from modules.attendance.models import (
    AttendanceRecord,
    AttendanceStatus,
    AttendanceSubmission,
)
from modules.attendance.services import (
    _current_school_date,
    _is_instructional_day,
)
from modules.classrooms.models import ClassEnrollment, Classroom
from modules.enrollments.models import Enrollment
from modules.guardian_family.services import (
    _guardian_scope,
    _school_datetime_bounds,
)
from modules.schools.models import School
from modules.student_updates.models import (
    StudentUpdate,
    StudentUpdateRecipient,
)
from modules.students.models import GuardianStudent, Student
from prompts.registry import PROMPTS
from prompts.utils import render_template


logger = logging.getLogger(__name__)

MAX_WEEKLY_UPDATE_SOURCES = 20
MAX_UPDATE_BODY_CHARS = 2000


@dataclass(frozen=True)
class _WeeklySource:
    key: str
    kind: str
    record_id: uuid.UUID
    label: str
    content: str
    school_date: date | None
    href: str
    updated_at: datetime


@dataclass(frozen=True)
class _WeeklySources:
    sources: list[_WeeklySource]
    expected_attendance_dates: list[date]
    placement_dates: list[date]
    submitted_attendance_dates: list[date]
    attendance_counts: dict[str, int]
    attendance_source_keys: list[str]
    updates_truncated: bool
    update_bodies_truncated: bool


class GuardianWeeklyExplanationValidationError(ValueError):
    pass


_FALLBACK_COPY = {
    "en": {
        "overview": (
            "This week includes {attendance_count} submitted attendance "
            "record(s) and {update_count} school update(s)."
        ),
        "attendance": (
            "Submitted attendance: present {present}, absent {absent}, "
            "late {late}, excused {excused}."
        ),
        "missing": "Attendance was not submitted for: {dates}.",
        "no_placement": (
            "Attendance was not expected because no classroom placement was "
            "found for the instructional dates in this period."
        ),
        "updates_truncated": (
            "Some school updates were omitted from this explanation. Open "
            "Family for the complete list."
        ),
        "body_truncated": (
            "Some update text was shortened. Open the source for the full "
            "context."
        ),
        "ai_unavailable": (
            "AI explanation was unavailable. The official records below are "
            "shown."
        ),
        "no_sources": "No submitted attendance or school updates were found for this week.",
    },
    "fr": {
        "overview": (
            "Cette semaine comprend {attendance_count} relevé(s) de présence "
            "soumis et {update_count} mise(s) à jour de l'école."
        ),
        "attendance": (
            "Présences soumises : présent {present}, absent {absent}, "
            "retard {late}, excusé {excused}."
        ),
        "missing": "La présence n'a pas été soumise pour : {dates}.",
        "no_placement": (
            "La présence n'était pas attendue car aucune classe n'était "
            "associée aux jours d'enseignement de cette période."
        ),
        "updates_truncated": (
            "Certaines mises à jour ont été omises de cette explication. "
            "Ouvrez Family pour voir la liste complète."
        ),
        "body_truncated": (
            "Le texte de certaines mises à jour a été raccourci. Ouvrez la "
            "source pour le contexte complet."
        ),
        "ai_unavailable": (
            "L'explication IA n'est pas disponible. Les informations "
            "officielles sont affichées ci-dessous."
        ),
        "no_sources": "Aucune présence soumise ni mise à jour scolaire n'a été trouvée cette semaine.",
    },
    "ar": {
        "overview": (
            "يتضمن هذا الأسبوع {attendance_count} سجل حضور مُرسل و{update_count} "
            "تحديثاً مدرسياً."
        ),
        "attendance": (
            "الحضور المُرسل: حاضر {present}، غائب {absent}، متأخر {late}، "
            "بعذر {excused}."
        ),
        "missing": "لم يُرسل الحضور للأيام التالية: {dates}.",
        "no_placement": (
            "لم يكن الحضور متوقعاً لعدم وجود فصل مرتبط بأيام الدراسة في هذه "
            "الفترة."
        ),
        "updates_truncated": (
            "تم حذف بعض التحديثات من هذا الشرح. افتح قسم العائلة للاطلاع على "
            "القائمة الكاملة."
        ),
        "body_truncated": (
            "تم اختصار نص بعض التحديثات. افتح المصدر للاطلاع على السياق الكامل."
        ),
        "ai_unavailable": (
            "شرح الذكاء الاصطناعي غير متاح. نعرض السجلات الرسمية أدناه."
        ),
        "no_sources": "لم يتم العثور على حضور مُرسل أو تحديثات مدرسية لهذا الأسبوع.",
    },
}


def _fallback_language(language: TeacherDraftLanguage) -> str:
    return language.value if language.value in _FALLBACK_COPY else "en"


def _safe_local_date(value: datetime, timezone_name: str) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(timezone_name)).date()


async def _get_linked_student(
    session: AsyncSession,
    student_id: uuid.UUID,
    guardian_id: str,
    organization_id: str,
) -> Student:
    student = await session.scalar(
        select(Student)
        .join(GuardianStudent, GuardianStudent.student_id == Student.id)
        .where(
            Student.id == student_id,
            Student.organization_id == organization_id,
            GuardianStudent.guardian_workos_user_id == guardian_id,
        )
    )
    if student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )
    return student


async def _attendance_expectations(
    session: AsyncSession,
    student_id: uuid.UUID,
    organization_id: str,
    school: School,
    week_start: date,
    week_end: date,
) -> tuple[list[date], list[date]]:
    years = list(
        (
            await session.scalars(
                select(AcademicYear)
                .where(
                    AcademicYear.organization_id == organization_id,
                    AcademicYear.status == AcademicYearStatus.ACTIVE,
                    AcademicYear.starts_on <= week_end,
                    AcademicYear.ends_on >= week_start,
                )
                .order_by(AcademicYear.starts_on.desc(), AcademicYear.id)
            )
        ).all()
    )
    placement_rows = list(
        (
            await session.execute(
                select(ClassEnrollment, AcademicYear)
                .join(
                    Enrollment,
                    Enrollment.id == ClassEnrollment.enrollment_id,
                )
                .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
                .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
                .where(
                    Enrollment.student_id == student_id,
                    AcademicYear.organization_id == organization_id,
                    AcademicYear.status == AcademicYearStatus.ACTIVE,
                    ClassEnrollment.effective_from <= week_end,
                    or_(
                        ClassEnrollment.effective_until.is_(None),
                        ClassEnrollment.effective_until > week_start,
                    ),
                )
            )
        ).all()
    )

    expected: list[date] = []
    placement_dates: list[date] = []
    current = week_start
    while current <= week_end:
        year = next(
            (
                candidate
                for candidate in years
                if candidate.starts_on <= current <= candidate.ends_on
            ),
            None,
        )
        has_placement = any(
            placement.effective_from <= current
            and (
                placement.effective_until is None
                or placement.effective_until > current
            )
            and academic_year.starts_on <= current <= academic_year.ends_on
            for placement, academic_year in placement_rows
        )
        if has_placement:
            placement_dates.append(current)
        if year is not None and has_placement and await _is_instructional_day(
            session, year, current, school
        ):
            expected.append(current)
        current += timedelta(days=1)
    return expected, placement_dates


async def _collect_sources(
    session: AsyncSession,
    student_id: uuid.UUID,
    organization_id: str,
    guardian_id: str,
    school: School,
    week_start: date,
    week_end: date,
) -> _WeeklySources:
    expected_dates, placement_dates = await _attendance_expectations(
        session,
        student_id,
        organization_id,
        school,
        week_start,
        week_end,
    )
    attendance_rows = list(
        (
            await session.execute(
                select(AttendanceRecord, Classroom.name)
                .join(
                    AttendanceSubmission,
                    AttendanceSubmission.id == AttendanceRecord.submission_id,
                )
                .join(
                    ClassEnrollment,
                    ClassEnrollment.id == AttendanceRecord.class_enrollment_id,
                )
                .join(
                    Enrollment,
                    Enrollment.id == ClassEnrollment.enrollment_id,
                )
                .join(Student, Student.id == Enrollment.student_id)
                .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
                .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
                .where(
                    Student.id == student_id,
                    Student.organization_id == organization_id,
                    AcademicYear.organization_id == organization_id,
                    AttendanceSubmission.school_date
                    == AttendanceRecord.school_date,
                    AttendanceRecord.school_date >= week_start,
                    AttendanceRecord.school_date <= week_end,
                )
                .order_by(
                    AttendanceRecord.school_date,
                    AttendanceRecord.updated_at.desc(),
                    AttendanceRecord.id.desc(),
                )
            )
        ).all()
    )

    attendance_by_date: dict[date, tuple[AttendanceRecord, str]] = {}
    for record, classroom_name in attendance_rows:
        attendance_by_date.setdefault(
            record.school_date,
            (record, classroom_name),
        )

    sources: list[_WeeklySource] = []
    attendance_counts = {status.value: 0 for status in AttendanceStatus}
    submitted_dates = sorted(attendance_by_date)
    attendance_source_keys: list[str] = []
    for index, school_date in enumerate(submitted_dates, start=1):
        record, classroom_name = attendance_by_date[school_date]
        key = f"s{index}"
        attendance_source_keys.append(key)
        attendance_counts[record.status.value] += 1
        note = f" Note: {record.note}" if record.note else ""
        sources.append(
            _WeeklySource(
                key=key,
                kind="attendance",
                record_id=record.id,
                label=f"Attendance · {school_date.isoformat()} · {record.status.value}",
                content=(
                    f"School date: {school_date.isoformat()}\n"
                    f"Status: {record.status.value}\n"
                    f"Classroom: {classroom_name}.{note}"
                ),
                school_date=school_date,
                href=(
                    f"/app/guardian/students/{student_id}"
                    f"?from={school_date.isoformat()}&to={school_date.isoformat()}"
                ),
                updated_at=record.updated_at,
            )
        )

    start_at, end_at = _school_datetime_bounds(
        school.timezone,
        week_start,
        week_end,
    )
    update_rows = list(
        (
            await session.execute(
                select(StudentUpdateRecipient, StudentUpdate, Classroom)
                .join(
                    StudentUpdate,
                    StudentUpdate.id == StudentUpdateRecipient.student_update_id,
                )
                .join(Classroom, Classroom.id == StudentUpdate.classroom_id)
                .join(Student, Student.id == StudentUpdateRecipient.student_id)
                .join(
                    GuardianStudent,
                    GuardianStudent.student_id == Student.id,
                )
                .where(
                    StudentUpdateRecipient.student_id == student_id,
                    StudentUpdate.organization_id == organization_id,
                    Student.organization_id == organization_id,
                    GuardianStudent.guardian_workos_user_id == guardian_id,
                    StudentUpdate.created_at >= start_at,
                    StudentUpdate.created_at < end_at,
                )
                .order_by(
                    StudentUpdate.created_at.desc(),
                    StudentUpdate.id.desc(),
                    StudentUpdateRecipient.id.desc(),
                )
                .limit(MAX_WEEKLY_UPDATE_SOURCES + 1)
            )
        ).all()
    )
    updates_truncated = len(update_rows) > MAX_WEEKLY_UPDATE_SOURCES
    update_rows = update_rows[:MAX_WEEKLY_UPDATE_SOURCES]
    update_bodies_truncated = False
    for index, (recipient, update, classroom) in enumerate(
        update_rows,
        start=len(sources) + 1,
    ):
        body = update.body or ""
        if len(body) > MAX_UPDATE_BODY_CHARS:
            body = body[: MAX_UPDATE_BODY_CHARS - 2].rstrip() + " …"
            update_bodies_truncated = True
        key = f"s{index}"
        sources.append(
            _WeeklySource(
                key=key,
                kind="update",
                record_id=update.id,
                label=update.title,
                content=(
                    f"School update title: {update.title}\n"
                    f"Target: {update.target_type.value}\n"
                    f"Classroom: {classroom.name}\n"
                    f"Content: {body or '[No additional body]'}"
                ),
                school_date=_safe_local_date(
                    update.created_at,
                    school.timezone,
                ),
                href=(
                    f"/app/guardian/students/{student_id}"
                    f"/updates/{recipient.id}"
                ),
                updated_at=update.updated_at,
            )
        )

    return _WeeklySources(
        sources=sources,
        expected_attendance_dates=expected_dates,
        placement_dates=placement_dates,
        submitted_attendance_dates=submitted_dates,
        attendance_counts=attendance_counts,
        attendance_source_keys=attendance_source_keys,
        updates_truncated=updates_truncated,
        update_bodies_truncated=update_bodies_truncated,
    )


def _source_snapshot_id(sources: list[_WeeklySource]) -> str:
    snapshot = [
        {
            "id": str(source.record_id),
            "kind": source.kind,
            "school_date": (
                source.school_date.isoformat() if source.school_date else None
            ),
            "updated_at": source.updated_at.isoformat(),
        }
        for source in sources
    ]
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return digest[:16]


def _log_event(
    *,
    request_id: str,
    organization_id: str,
    guardian_id: str,
    student_id: uuid.UUID,
    date_from: date,
    date_to: date,
    output_language: TeacherDraftLanguage,
    source_count: int,
    source_snapshot_id: str,
    outcome: str,
    latency_ms: int,
    error_category: str | None = None,
    token_usage: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "guardian_weekly_explanation",
        extra={
            "event": "guardian_weekly_explanation",
            "request_id": request_id,
            "organization_id": organization_id,
            "guardian_id": guardian_id,
            "student_id": str(student_id),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "output_language": output_language.value,
            "source_count": source_count,
            "source_snapshot_id": source_snapshot_id,
            "outcome": outcome,
            "latency_ms": latency_ms,
            "prompt_version": PROMPTS["workflow_guardian_weekly_explanation"][
                "version"
            ],
            "model": settings.llm.OPENROUTER_MODEL or None,
            "token_usage": token_usage,
            "error_category": error_category,
        },
    )


def _source_responses(
    sources: list[_WeeklySource],
) -> list[GuardianWeeklyExplanationSource]:
    return [
        GuardianWeeklyExplanationSource(
            key=source.key,
            kind=source.kind,
            label=source.label,
            school_date=source.school_date,
            href=source.href,
        )
        for source in sources
    ]


def _attendance_response(
    weekly_sources: _WeeklySources,
    summary: GuardianWeeklyExplanationText | None,
) -> GuardianWeeklyAttendance:
    return GuardianWeeklyAttendance(
        counts=GuardianWeeklyAttendanceCounts(**weekly_sources.attendance_counts),
        submitted_dates=weekly_sources.submitted_attendance_dates,
        missing_dates=sorted(
            set(weekly_sources.expected_attendance_dates)
            - set(weekly_sources.submitted_attendance_dates)
        ),
        source_keys=weekly_sources.attendance_source_keys,
        summary=summary,
    )


def _validate_citations(
    result: GuardianWeeklyExplanationModelResult,
    sources: list[_WeeklySource],
) -> None:
    source_by_key = {source.key: source for source in sources}

    def validate_item(
        item: GuardianWeeklyExplanationText,
        *,
        expected_kind: str | None = None,
    ) -> None:
        for key in item.source_keys:
            source = source_by_key.get(key)
            if source is None:
                raise GuardianWeeklyExplanationValidationError(
                    "structured output cited an unknown source"
                )
            if expected_kind is not None and source.kind != expected_kind:
                raise GuardianWeeklyExplanationValidationError(
                    "structured output cited a source from the wrong section"
                )

    for item in result.overview:
        validate_item(item)
    if result.attendance_summary is not None:
        validate_item(result.attendance_summary, expected_kind="attendance")
    for item in result.school_updates:
        validate_item(item, expected_kind="update")
    if result.follow_up is not None:
        validate_item(result.follow_up)


def _prompt_source(source: _WeeklySource) -> dict[str, str]:
    return {
        "key": source.key,
        "kind": source.kind,
        "school_date": (
            source.school_date.isoformat() if source.school_date else "unknown"
        ),
        "title": source.label,
        "content": source.content,
    }


def _attendance_prompt_summary(weekly_sources: _WeeklySources) -> str:
    return json.dumps(
        {
            "counts": weekly_sources.attendance_counts,
            "submitted_dates": [
                value.isoformat()
                for value in weekly_sources.submitted_attendance_dates
            ],
            "missing_dates": [
                value.isoformat()
                for value in sorted(
                    set(weekly_sources.expected_attendance_dates)
                    - set(weekly_sources.submitted_attendance_dates)
                )
            ],
        },
        sort_keys=True,
    )


def _fallback_response(
    *,
    weekly_sources: _WeeklySources,
    student_id: uuid.UUID,
    date_from: date,
    date_to: date,
    school_timezone: str,
    output_language: TeacherDraftLanguage,
) -> GuardianWeeklyExplanationResponse:
    copy = _FALLBACK_COPY[_fallback_language(output_language)]
    source_responses = _source_responses(weekly_sources.sources)
    update_sources = [
        source for source in weekly_sources.sources if source.kind == "update"
    ]
    attendance_summary = None
    if weekly_sources.attendance_source_keys:
        attendance_summary = GuardianWeeklyExplanationText(
            text=copy["attendance"].format(**weekly_sources.attendance_counts),
            source_keys=weekly_sources.attendance_source_keys,
        )
    overview = [
        GuardianWeeklyExplanationText(
            text=copy["overview"].format(
                attendance_count=len(weekly_sources.submitted_attendance_dates),
                update_count=len(update_sources),
            ),
            source_keys=[source.key for source in weekly_sources.sources],
        )
    ]
    school_updates = [
        GuardianWeeklyExplanationText(
            text=source.label,
            source_keys=[source.key],
        )
        for source in update_sources
    ]
    limitations = [copy["ai_unavailable"]]
    missing_dates = sorted(
        set(weekly_sources.expected_attendance_dates)
        - set(weekly_sources.submitted_attendance_dates)
    )
    if missing_dates:
        limitations.append(
            copy["missing"].format(
                dates=", ".join(value.isoformat() for value in missing_dates)
            )
        )
    elif not weekly_sources.placement_dates and not weekly_sources.submitted_attendance_dates:
        limitations.append(copy["no_placement"])
    if weekly_sources.updates_truncated:
        limitations.append(copy["updates_truncated"])
    if weekly_sources.update_bodies_truncated:
        limitations.append(copy["body_truncated"])
    return GuardianWeeklyExplanationResponse(
        status="fallback",
        ai_generated=False,
        retryable=True,
        student_id=student_id,
        date_from=date_from,
        date_to=date_to,
        school_timezone=school_timezone,
        output_language=output_language,
        generated_at=utcnow(),
        overview=overview,
        attendance=_attendance_response(weekly_sources, attendance_summary),
        school_updates=school_updates,
        follow_up=None,
        limitations=limitations,
        sources=source_responses,
    )


def _empty_response(
    *,
    weekly_sources: _WeeklySources,
    student_id: uuid.UUID,
    date_from: date,
    date_to: date,
    school_timezone: str,
    output_language: TeacherDraftLanguage,
) -> GuardianWeeklyExplanationResponse:
    copy = _FALLBACK_COPY[_fallback_language(output_language)]
    limitations = [copy["no_sources"]]
    if not weekly_sources.placement_dates and not weekly_sources.submitted_attendance_dates:
        limitations.append(copy["no_placement"])
    return GuardianWeeklyExplanationResponse(
        status="empty",
        ai_generated=False,
        retryable=False,
        student_id=student_id,
        date_from=date_from,
        date_to=date_to,
        school_timezone=school_timezone,
        output_language=output_language,
        generated_at=utcnow(),
        overview=[],
        attendance=_attendance_response(weekly_sources, None),
        school_updates=[],
        follow_up=None,
        limitations=limitations,
        sources=[],
    )


def _generated_response(
    *,
    result: GuardianWeeklyExplanationModelResult,
    weekly_sources: _WeeklySources,
    student_id: uuid.UUID,
    date_from: date,
    date_to: date,
    school_timezone: str,
    output_language: TeacherDraftLanguage,
) -> GuardianWeeklyExplanationResponse:
    limitations: list[str] = []
    if weekly_sources.expected_attendance_dates:
        missing_dates = sorted(
            set(weekly_sources.expected_attendance_dates)
            - set(weekly_sources.submitted_attendance_dates)
        )
        if missing_dates:
            limitations.append(
                "Attendance was not submitted for: "
                + ", ".join(value.isoformat() for value in missing_dates)
                + "."
            )
    if weekly_sources.updates_truncated:
        limitations.append(
            "Some school updates were omitted from this explanation. Open Family for the complete list."
        )
    if weekly_sources.update_bodies_truncated:
        limitations.append(
            "Some update text was shortened. Open the source for the full context."
        )
    if not weekly_sources.placement_dates and not weekly_sources.submitted_attendance_dates:
        limitations.append(
            "Attendance was not expected because no classroom placement was found for the instructional dates in this period."
        )
    return GuardianWeeklyExplanationResponse(
        status="generated",
        ai_generated=True,
        retryable=False,
        student_id=student_id,
        date_from=date_from,
        date_to=date_to,
        school_timezone=school_timezone,
        output_language=output_language,
        generated_at=utcnow(),
        overview=result.overview,
        attendance=_attendance_response(
            weekly_sources,
            result.attendance_summary,
        ),
        school_updates=result.school_updates,
        follow_up=result.follow_up,
        limitations=limitations,
        sources=_source_responses(weekly_sources.sources),
    )


class GuardianWeeklyExplanationService:
    async def generate(
        self,
        *,
        session: AsyncSession,
        student_id: uuid.UUID,
        current_user: dict,
        output_language: TeacherDraftLanguage | None,
        request_id: str,
        chain: Any | None = None,
    ) -> GuardianWeeklyExplanationResponse:
        guardian_id, organization_id = _guardian_scope(current_user)
        student = await _get_linked_student(
            session,
            student_id,
            guardian_id,
            organization_id,
        )
        school = await session.get(School, organization_id)
        if school is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="School not found",
            )
        if not school.ai_guardian_weekly_explanation_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="AI guardian weekly explanations are disabled for this school",
            )

        selected_language = output_language
        if selected_language is not None and not isinstance(
            selected_language,
            TeacherDraftLanguage,
        ):
            selected_language = TeacherDraftLanguage(selected_language)
        if selected_language is None:
            try:
                selected_language = TeacherDraftLanguage(
                    school.ai_guardian_weekly_explanation_default_language
                )
            except ValueError:
                selected_language = TeacherDraftLanguage.AUTO

        school_date = _current_school_date(school)
        date_from = school_date - timedelta(days=school_date.weekday())
        date_to = school_date
        started_at = time.monotonic()
        weekly_sources = await _collect_sources(
            session,
            student.id,
            organization_id,
            guardian_id,
            school,
            date_from,
            date_to,
        )
        source_snapshot_id = _source_snapshot_id(weekly_sources.sources)

        def log_event(
            *,
            outcome: str,
            error_category: str | None = None,
            token_usage: dict[str, Any] | None = None,
        ) -> None:
            _log_event(
                request_id=request_id,
                organization_id=organization_id,
                guardian_id=guardian_id,
                student_id=student.id,
                date_from=date_from,
                date_to=date_to,
                output_language=selected_language,
                source_count=len(weekly_sources.sources),
                source_snapshot_id=source_snapshot_id,
                outcome=outcome,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                error_category=error_category,
                token_usage=token_usage,
            )

        if not weekly_sources.sources:
            log_event(outcome="empty")
            return _empty_response(
                weekly_sources=weekly_sources,
                student_id=student.id,
                date_from=date_from,
                date_to=date_to,
                school_timezone=school.timezone,
                output_language=selected_language,
            )

        try:
            await _consume_rate_limit(
                organization_id,
                guardian_id,
                namespace="guardian-weekly",
            )
        except RateLimitExceededError:
            log_event(outcome="failed", error_category="rate_limited")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "AI explanation limit reached. Continue with the Family feed."
                ),
            )
        except RateLimitUnavailableError:
            log_event(
                outcome="failed",
                error_category="rate_limit_unavailable",
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "AI explanations are temporarily unavailable. Continue with the Family feed."
                ),
            )

        prompt = render_template(
            PROMPTS["workflow_guardian_weekly_explanation"]["template"],
            {
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "output_language": selected_language.value,
                "attendance_summary": _attendance_prompt_summary(weekly_sources),
                "sources": [_prompt_source(source) for source in weekly_sources.sources],
            },
        )

        try:
            explanation_chain = (
                chain
                if chain is not None
                else get_guardian_weekly_explanation_chain()
            )
            result, token_usage = _extract_chain_result(
                await explanation_chain.ainvoke(prompt),
                GuardianWeeklyExplanationModelResult,
            )
            _validate_citations(result, weekly_sources.sources)
            if _contains_unsafe_text(
                item.text
                for item in (
                    [*result.overview, *result.school_updates]
                    + ([result.attendance_summary] if result.attendance_summary else [])
                    + ([result.follow_up] if result.follow_up else [])
                )
            ):
                raise GuardianWeeklyExplanationValidationError(
                    "structured output failed the safety gate"
                )
        except asyncio.CancelledError:
            log_event(outcome="cancelled")
            raise
        except OpenRouterNotConfiguredError:
            log_event(outcome="fallback", error_category="not_configured")
            return _fallback_response(
                weekly_sources=weekly_sources,
                student_id=student.id,
                date_from=date_from,
                date_to=date_to,
                school_timezone=school.timezone,
                output_language=selected_language,
            )
        except Exception as exc:
            error_category = (
                "unsafe_output"
                if isinstance(exc, GuardianWeeklyExplanationValidationError)
                and "safety" in str(exc)
                else _safe_error_category(exc)
            )
            log_event(outcome="fallback", error_category=error_category)
            return _fallback_response(
                weekly_sources=weekly_sources,
                student_id=student.id,
                date_from=date_from,
                date_to=date_to,
                school_timezone=school.timezone,
                output_language=selected_language,
            )

        log_event(outcome="generated", token_usage=token_usage)
        return _generated_response(
            result=result,
            weekly_sources=weekly_sources,
            student_id=student.id,
            date_from=date_from,
            date_to=date_to,
            school_timezone=school.timezone,
            output_language=selected_language,
        )


guardian_weekly_explanation_service = GuardianWeeklyExplanationService()
