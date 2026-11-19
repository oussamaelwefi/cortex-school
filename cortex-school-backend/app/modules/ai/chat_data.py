"""Read-only school queries; identity and scope are never supplied by the model."""

import asyncio
import json
import re
from datetime import timedelta

from ai.chat.schemas import ChatRole, ChatSource, SchoolDataQuery
from core.db import utcnow
from fastapi import HTTPException
from modules.academic_years.models import (
    AcademicCalendar,
    AcademicYear,
    AcademicYearStatus,
    CalendarEntry,
)
from modules.ai.chat_access import access_state, blocked_guardians, protected_students
from modules.attendance.models import AttendanceRecord
from modules.attendance.services import _current_school_date
from modules.classrooms.models import ClassEnrollment, Classroom, TeacherAssignment
from modules.enrollments.models import Enrollment
from modules.invitations.models import Invitation
from modules.members.services import MemberLookupUnavailable, list_school_members
from modules.publications.models import PublicationRecipient, SchoolPublication
from modules.publications.services import _active_viewer, _inbox_conditions
from modules.reminders.models import SchoolPolicyPassage
from modules.reminders.policy import normalize_search
from modules.schools.models import School
from modules.student_registration.models import StudentRegistrationRequest
from modules.student_updates.models import (
    GuardianUpdateState,
    StudentUpdate,
    StudentUpdateRecipient,
    StudentUpdateStatus,
)
from modules.students.models import GuardianStudent, Student
from sqlalchemy import String, and_, any_, cast, exists, func, or_, select, text


def selected_role(current_user: dict, requested: ChatRole | None) -> ChatRole:
    claims = current_user.get("claims", {})
    roles = claims.get("roles", [])
    roles = set(roles if isinstance(roles, list) else [])
    roles.add(claims.get("role"))
    allowed = []
    if "school:manage" in claims.get("permissions", []):
        allowed.append("admin")
    allowed.extend(role for role in ("teacher", "guardian") if role in roles)
    role = requested or (allowed[0] if allowed else None)
    if (
        role not in allowed
        or not current_user.get("user_id")
        or not current_user.get("organization_id")
    ):
        raise HTTPException(
            403, "This chat workspace is not available for your school session."
        )
    return role


class SchoolDataAccess:
    def __init__(self, session, current_user, role):
        self.session = session
        self.user = current_user
        self.role = selected_role(current_user, role)
        self.user_id = current_user["user_id"]
        self.organization_id = current_user["organization_id"]
        self.ready = False
        self.sources: dict[str, ChatSource] = {}
        self._source_keys = {}
        self.members = None
        self.privacy_revision = None

    async def ensure_access(self):
        if not self.ready:
            await _active_viewer(
                self.user, "school_admin" if self.role == "admin" else self.role
            )
            # This is a fresh request session. PostgreSQL prevents accidental writes.
            await self.session.execute(text("SET TRANSACTION READ ONLY"))
            await self.session.execute(text("SET LOCAL statement_timeout = '4000ms'"))
        state = await access_state(self.session, self.user, self.role)
        if not state["effective_data_enabled"]:
            raise HTTPException(403, "Chat access to school data is turned off.")
        if (
            self.privacy_revision is not None
            and state["revision"] != self.privacy_revision
        ):
            raise HTTPException(
                409, "Chat privacy settings changed. Start a new question."
            )
        self.privacy_revision = state["revision"]
        school = await self.session.get(
            School, self.organization_id, populate_existing=True
        )
        if school is None:
            raise HTTPException(404, "School not found")
        self.today = _current_school_date(school)
        self.timezone = school.timezone
        self.ready = True

    def source(self, label, href=None, excerpt=None, key=None):
        key = key or (label, href)
        if key in self._source_keys:
            return self._source_keys[key]
        source_id = f"S{len(self.sources) + 1}"
        self.sources[source_id] = ChatSource(
            id=source_id, label=label, href=href, excerpt=excerpt
        )
        self._source_keys[key] = source_id
        return source_id

    def teacher_classes(self, upcoming=False):
        clauses = [
            AcademicYear.organization_id == self.organization_id,
            AcademicYear.status == AcademicYearStatus.ACTIVE,
            AcademicYear.ends_on >= self.today,
            TeacherAssignment.teacher_workos_user_id == self.user_id,
            or_(
                TeacherAssignment.effective_until.is_(None),
                TeacherAssignment.effective_until > self.today,
            ),
        ]
        if not upcoming:
            clauses.extend(
                [
                    AcademicYear.starts_on <= self.today,
                    TeacherAssignment.effective_from <= self.today,
                ]
            )
        return (
            select(Classroom.id)
            .join(AcademicYear)
            .join(TeacherAssignment, TeacherAssignment.classroom_id == Classroom.id)
            .where(*clauses)
        )

    def students(self):
        statement = select(Student.id).where(
            Student.organization_id == self.organization_id,
            Student.id.not_in(protected_students(self.organization_id)),
        )
        if self.role == "guardian":
            statement = statement.where(
                exists(
                    select(GuardianStudent.id).where(
                        GuardianStudent.student_id == Student.id,
                        GuardianStudent.guardian_workos_user_id == self.user_id,
                    )
                )
            )
        elif self.role == "teacher":
            statement = statement.where(
                exists(
                    select(ClassEnrollment.id)
                    .join(Enrollment, Enrollment.id == ClassEnrollment.enrollment_id)
                    .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
                    .where(
                        Enrollment.student_id == Student.id,
                        Enrollment.academic_year_id == Classroom.academic_year_id,
                        ClassEnrollment.classroom_id.in_(self.teacher_classes()),
                        ClassEnrollment.effective_from <= self.today,
                        or_(
                            ClassEnrollment.effective_until.is_(None),
                            ClassEnrollment.effective_until > self.today,
                        ),
                    )
                )
            )
        return statement

    def classrooms(self):
        statement = (
            select(Classroom.id)
            .join(AcademicYear)
            .where(AcademicYear.organization_id == self.organization_id)
        )
        if self.role == "teacher":
            return statement.where(
                Classroom.id.in_(self.teacher_classes(upcoming=True))
            )
        if self.role == "guardian":
            statement = statement.where(
                exists(
                    select(ClassEnrollment.id)
                    .join(Enrollment, Enrollment.id == ClassEnrollment.enrollment_id)
                    .where(
                        ClassEnrollment.classroom_id == Classroom.id,
                        Enrollment.academic_year_id == Classroom.academic_year_id,
                        Enrollment.student_id.in_(self.students()),
                        ClassEnrollment.effective_from <= self.today,
                        or_(
                            ClassEnrollment.effective_until.is_(None),
                            ClassEnrollment.effective_until > self.today,
                        ),
                    )
                )
            )
        return statement

    async def page(self, statement, query):
        total = await self.session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        rows = (
            await self.session.execute(
                statement.limit(query.limit).offset(query.offset)
            )
        ).all()
        return rows, total

    def result(self, label, href, items, total, query, **extra):
        data = {
            "status": "ok",
            "source_id": self.source(label, href),
            "as_of": self.today.isoformat(),
            "timezone": self.timezone,
            "total_count": total,
            "items": items,
            "scope": "Authorized records allowed by chat privacy settings. Counts exclude protected records.",
            **extra,
        }
        # Keep counts intact when shortening a large result; never imply a partial list is complete.
        while (
            len(json.dumps(data, default=str, ensure_ascii=False)) > 14000
            and len(items) > 1
        ):
            items.pop()
        data.update(
            returned_count=len(items),
            has_more=query.offset + len(items) < total,
            next_offset=query.offset + len(items)
            if query.offset + len(items) < total
            else None,
        )
        return data

    async def school_members(self):
        if self.members is None:
            try:
                async with asyncio.timeout(10):
                    self.members = await list_school_members(self.organization_id)
            except (TimeoutError, MemberLookupUnavailable) as exc:
                raise HTTPException(
                    503, "School data is temporarily unavailable. Please try again."
                ) from exc
        return self.members

    async def query(self, query: SchoolDataQuery):
        if query.dataset in {"invitations", "members"} and self.role != "admin":
            return {
                "status": "forbidden",
                "message": "This information is only available in the administration workspace.",
            }
        if query.dataset == "registrations" and self.role == "teacher":
            return {
                "status": "forbidden",
                "message": "Registration requests are not accessible in the teacher workspace.",
            }
        supported = {
            "overview": set(),
            "academic_years": {"search", "academic_year_id", "record_id", "status"},
            "students": {
                "search",
                "student_id",
                "record_id",
                "classroom_id",
                "academic_year_id",
            },
            "classrooms": {
                "search",
                "student_id",
                "record_id",
                "classroom_id",
                "academic_year_id",
                "status",
            },
            "enrollments": {
                "search",
                "student_id",
                "record_id",
                "classroom_id",
                "academic_year_id",
            },
            "attendance": {
                "search",
                "student_id",
                "record_id",
                "classroom_id",
                "academic_year_id",
                "date_from",
                "date_to",
                "status",
            },
            "updates": {
                "search",
                "student_id",
                "record_id",
                "classroom_id",
                "date_from",
                "date_to",
                "status",
                *({"unread_only"} if self.role == "guardian" else set()),
                "overdue_only",
            },
            "acknowledgements": {
                "search",
                "student_id",
                "record_id",
                "classroom_id",
                "date_from",
                "date_to",
                "status",
                "unread_only",
                "overdue_only",
            },
            "publications": {
                "search",
                "record_id",
                "date_from",
                "date_to",
                *({"unread_only"} if self.role != "admin" else set()),
            },
            "calendar": {
                "search",
                "record_id",
                "classroom_id",
                "academic_year_id",
                "date_from",
                "date_to",
            },
            "registrations": {"search", "record_id", "academic_year_id", "status"},
            "invitations": {"search", "record_id", "status"},
            "members": {"search", "status"},
        }[query.dataset]
        provided = set(query.model_dump(exclude_defaults=True, exclude_none=True)) - {
            "dataset",
            "limit",
            "offset",
        }
        if provided - supported:
            return {"status": "invalid_filters", "supported_filters": sorted(supported)}
        statuses = {
            "academic_years": {"draft", "active", "closed"},
            "classrooms": {"draft", "active", "closed"},
            "attendance": {"present", "absent", "late", "excused"},
            "updates": {"assigned", "acknowledged", "completed"},
            "acknowledgements": {"pending", "acknowledged", "read", "unread"},
            "registrations": {"pending", "approved", "rejected", "withdrawn"},
        }
        if (
            query.status
            and query.dataset in statuses
            and query.status not in statuses[query.dataset]
        ):
            return {
                "status": "invalid_filters",
                "allowed_status_values": sorted(statuses[query.dataset]),
            }
        await self.ensure_access()
        result = await getattr(self, f"read_{query.dataset}")(query)
        # A preference changed while querying: discard the whole result, including counts.
        await self.ensure_access()
        return result

    async def read_overview(self, q):
        student_count = await self.session.scalar(
            select(func.count()).select_from(self.students().subquery())
        )
        class_count = await self.session.scalar(
            select(func.count()).select_from(self.classrooms().distinct().subquery())
        )
        years = (
            await self.session.execute(
                select(AcademicYear.name, AcademicYear.starts_on, AcademicYear.ends_on)
                .where(
                    AcademicYear.organization_id == self.organization_id,
                    AcademicYear.status == AcademicYearStatus.ACTIVE,
                )
                .order_by(AcademicYear.starts_on.desc())
            )
        ).all()
        item = {
            "workspace": self.role,
            "students_in_scope": student_count,
            "classrooms_in_scope": class_count,
            "active_academic_years": [
                {"name": name, "starts_on": start, "ends_on": end}
                for name, start, end in years
            ],
        }
        return self.result("School overview", "/", [item], 1, q)

    async def read_students(self, q):
        statement = select(Student).where(Student.id.in_(self.students()))
        if q.search:
            statement = statement.where(
                func.concat(Student.first_name, " ", Student.last_name).icontains(
                    q.search, autoescape=True
                )
            )
        if q.student_id or q.record_id:
            statement = statement.where(Student.id == (q.student_id or q.record_id))
        if q.classroom_id or q.academic_year_id:
            placement = (
                select(Enrollment.student_id)
                .join(ClassEnrollment, ClassEnrollment.enrollment_id == Enrollment.id)
                .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
                .where(
                    Classroom.id.in_(self.classrooms()),
                    ClassEnrollment.effective_from <= self.today,
                    or_(
                        ClassEnrollment.effective_until.is_(None),
                        ClassEnrollment.effective_until > self.today,
                    ),
                )
            )
            if q.classroom_id:
                placement = placement.where(Classroom.id == q.classroom_id)
            if q.academic_year_id:
                placement = placement.where(
                    Enrollment.academic_year_id == q.academic_year_id
                )
            statement = statement.where(Student.id.in_(placement))
        rows, total = await self.page(
            statement.order_by(Student.last_name, Student.first_name, Student.id), q
        )
        return self.result(
            "Students",
            "/family"
            if self.role == "guardian"
            else "/classrooms"
            if self.role == "teacher"
            else "/students",
            [
                {
                    "id": student.id,
                    "first_name": student.first_name,
                    "last_name": student.last_name,
                }
                for (student,) in rows
            ],
            total,
            q,
        )

    async def read_classrooms(self, q):
        statement = (
            select(Classroom, AcademicYear)
            .join(AcademicYear)
            .where(Classroom.id.in_(self.classrooms()))
        )
        if q.classroom_id or q.record_id:
            statement = statement.where(Classroom.id == (q.classroom_id or q.record_id))
        if q.search:
            statement = statement.where(
                Classroom.name.icontains(q.search, autoescape=True)
            )
        if q.academic_year_id:
            statement = statement.where(AcademicYear.id == q.academic_year_id)
        if q.status:
            statement = statement.where(AcademicYear.status == q.status)
        if q.student_id:
            statement = statement.where(
                Classroom.id.in_(
                    select(ClassEnrollment.classroom_id)
                    .join(Enrollment, Enrollment.id == ClassEnrollment.enrollment_id)
                    .where(
                        Enrollment.student_id == q.student_id,
                        Enrollment.student_id.in_(self.students()),
                        ClassEnrollment.effective_from <= self.today,
                        or_(
                            ClassEnrollment.effective_until.is_(None),
                            ClassEnrollment.effective_until > self.today,
                        ),
                    )
                )
            )
        rows, total = await self.page(
            statement.order_by(
                AcademicYear.starts_on.desc(), Classroom.name, Classroom.id
            ),
            q,
        )
        return self.result(
            "Classrooms",
            "/family" if self.role == "guardian" else "/classrooms",
            [
                {
                    "id": c.id,
                    "name": c.name,
                    "academic_year_id": y.id,
                    "academic_year": y.name,
                    "year_status": y.status,
                    "starts_on": y.starts_on,
                    "ends_on": y.ends_on,
                }
                for c, y in rows
            ],
            total,
            q,
        )

    async def read_academic_years(self, q):
        statement = select(AcademicYear).where(
            AcademicYear.organization_id == self.organization_id
        )
        if self.role != "admin":
            statement = statement.where(
                AcademicYear.status == AcademicYearStatus.ACTIVE
            )
        if q.academic_year_id or q.record_id:
            statement = statement.where(
                AcademicYear.id == (q.academic_year_id or q.record_id)
            )
        if q.search:
            statement = statement.where(
                AcademicYear.name.icontains(q.search, autoescape=True)
            )
        if q.status:
            statement = statement.where(AcademicYear.status == q.status)
        rows, total = await self.page(
            statement.order_by(AcademicYear.starts_on.desc(), AcademicYear.id), q
        )
        return self.result(
            "Academic years",
            "/academic-years"
            if self.role == "admin"
            else "/classrooms"
            if self.role == "teacher"
            else "/family",
            [
                {
                    "id": y.id,
                    "name": y.name,
                    "starts_on": y.starts_on,
                    "ends_on": y.ends_on,
                    "status": y.status,
                }
                for (y,) in rows
            ],
            total,
            q,
        )

    async def read_enrollments(self, q):
        statement = (
            select(Student, Enrollment, AcademicYear)
            .join(Enrollment, Enrollment.student_id == Student.id)
            .join(AcademicYear, AcademicYear.id == Enrollment.academic_year_id)
            .where(
                Student.id.in_(self.students()),
                AcademicYear.organization_id == self.organization_id,
            )
        )
        if q.student_id:
            statement = statement.where(Student.id == q.student_id)
        if q.academic_year_id:
            statement = statement.where(AcademicYear.id == q.academic_year_id)
        if q.record_id:
            statement = statement.where(Enrollment.id == q.record_id)
        if self.role == "teacher":
            statement = statement.where(
                Enrollment.id.in_(
                    select(ClassEnrollment.enrollment_id).where(
                        ClassEnrollment.classroom_id.in_(self.teacher_classes()),
                        ClassEnrollment.effective_from <= self.today,
                        or_(
                            ClassEnrollment.effective_until.is_(None),
                            ClassEnrollment.effective_until > self.today,
                        ),
                    )
                )
            )
        if q.classroom_id:
            statement = statement.where(
                Enrollment.id.in_(
                    select(ClassEnrollment.enrollment_id).where(
                        ClassEnrollment.classroom_id == q.classroom_id,
                        ClassEnrollment.classroom_id.in_(self.classrooms()),
                    )
                )
            )
        if q.search:
            statement = statement.where(
                func.concat(Student.first_name, " ", Student.last_name).icontains(
                    q.search, autoescape=True
                )
            )
        rows, total = await self.page(
            statement.order_by(
                AcademicYear.starts_on.desc(), Student.last_name, Enrollment.id
            ),
            q,
        )
        return self.result(
            "Enrollments",
            "/enrollments"
            if self.role == "admin"
            else "/family"
            if self.role == "guardian"
            else "/classrooms",
            [
                {
                    "id": e.id,
                    "student_id": s.id,
                    "student": f"{s.first_name} {s.last_name}",
                    "academic_year": y.name,
                    "year_status": y.status,
                }
                for s, e, y in rows
            ],
            total,
            q,
        )

    async def read_attendance(self, q):
        start = q.date_from or (q.date_to or self.today) - timedelta(days=30)
        end = q.date_to or self.today
        if not 0 <= (end - start).days <= 366:
            return {
                "status": "invalid_filters",
                "message": "Use an ordered date range of at most 366 days.",
            }
        statement = (
            select(AttendanceRecord, Student, Classroom)
            .join(
                ClassEnrollment,
                ClassEnrollment.id == AttendanceRecord.class_enrollment_id,
            )
            .join(Enrollment, Enrollment.id == ClassEnrollment.enrollment_id)
            .join(Student, Student.id == Enrollment.student_id)
            .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
            .join(AcademicYear, AcademicYear.id == Classroom.academic_year_id)
            .where(
                Student.organization_id == self.organization_id,
                Student.id.not_in(protected_students(self.organization_id)),
                AcademicYear.organization_id == self.organization_id,
                Enrollment.academic_year_id == Classroom.academic_year_id,
                AttendanceRecord.school_date >= start,
                AttendanceRecord.school_date <= end,
                AttendanceRecord.school_date >= ClassEnrollment.effective_from,
                or_(
                    ClassEnrollment.effective_until.is_(None),
                    AttendanceRecord.school_date < ClassEnrollment.effective_until,
                ),
            )
        )
        if self.role == "guardian":
            statement = statement.where(Student.id.in_(self.students()))
        if self.role == "teacher":
            statement = statement.where(
                Classroom.id.in_(self.teacher_classes()),
                exists(
                    select(TeacherAssignment.id).where(
                        TeacherAssignment.classroom_id == Classroom.id,
                        TeacherAssignment.teacher_workos_user_id == self.user_id,
                        TeacherAssignment.effective_from
                        <= AttendanceRecord.school_date,
                        or_(
                            TeacherAssignment.effective_until.is_(None),
                            TeacherAssignment.effective_until
                            > AttendanceRecord.school_date,
                        ),
                    )
                ),
            )
        if q.student_id:
            statement = statement.where(Student.id == q.student_id)
        if q.classroom_id:
            statement = statement.where(Classroom.id == q.classroom_id)
        if q.academic_year_id:
            statement = statement.where(AcademicYear.id == q.academic_year_id)
        if q.status:
            statement = statement.where(AttendanceRecord.status == q.status)
        if q.record_id:
            statement = statement.where(AttendanceRecord.id == q.record_id)
        if q.search:
            statement = statement.where(
                or_(
                    Classroom.name.icontains(q.search, autoescape=True),
                    func.concat(Student.first_name, " ", Student.last_name).icontains(
                        q.search, autoescape=True
                    ),
                )
            )
        base = statement.subquery()
        counts = dict(
            (
                await self.session.execute(
                    select(base.c.status, func.count()).group_by(base.c.status)
                )
            ).all()
        )
        rows, total = await self.page(
            statement.order_by(
                AttendanceRecord.school_date.desc(),
                Student.last_name,
                AttendanceRecord.id,
            ),
            q,
        )
        return self.result(
            "Attendance",
            "/family" if self.role == "guardian" else "/attendance",
            [
                {
                    "id": r.id,
                    "date": r.school_date,
                    "student_id": s.id,
                    "student": f"{s.first_name} {s.last_name}",
                    "classroom": c.name,
                    "status": r.status,
                    "note": r.note,
                }
                for r, s, c in rows
            ],
            total,
            q,
            date_from=start,
            date_to=end,
            status_counts=counts,
            missing_records_are_not_absences=True,
        )

    def updates_query(self, pending=False):
        statement = (
            select(StudentUpdate, StudentUpdateRecipient, Student, GuardianUpdateState)
            .join(
                StudentUpdateRecipient,
                StudentUpdateRecipient.student_update_id == StudentUpdate.id,
            )
            .join(Student, Student.id == StudentUpdateRecipient.student_id)
        )
        if pending or self.role == "guardian":
            statement = statement.join(
                GuardianStudent, GuardianStudent.student_id == Student.id
            ).outerjoin(
                GuardianUpdateState,
                and_(
                    GuardianUpdateState.recipient_id == StudentUpdateRecipient.id,
                    GuardianUpdateState.guardian_workos_user_id
                    == GuardianStudent.guardian_workos_user_id,
                ),
            )
            if self.role == "guardian":
                statement = statement.where(
                    GuardianStudent.guardian_workos_user_id == self.user_id
                )
        else:
            statement = statement.outerjoin(
                GuardianUpdateState,
                and_(
                    GuardianUpdateState.recipient_id == StudentUpdateRecipient.id,
                    GuardianUpdateState.guardian_workos_user_id == self.user_id,
                ),
            )
        statement = statement.where(
            StudentUpdate.organization_id == self.organization_id,
            Student.organization_id == self.organization_id,
            Student.id.not_in(protected_students(self.organization_id)),
            StudentUpdate.teacher_workos_user_id.not_in(
                blocked_guardians(self.organization_id)
            ),
            # Shared text may mention another recipient. Withhold the complete
            # update if any of its student recipients is protected.
            StudentUpdate.id.not_in(
                select(StudentUpdateRecipient.student_update_id)
                .where(
                    StudentUpdateRecipient.student_id.in_(
                        protected_students(self.organization_id)
                    ),
                )
                .correlate(None)
            ),
        )
        if pending or self.role == "guardian":
            statement = statement.where(
                GuardianStudent.guardian_workos_user_id.not_in(
                    blocked_guardians(self.organization_id)
                ),
            )
        if self.role == "teacher":
            statement = statement.where(
                StudentUpdate.teacher_workos_user_id == self.user_id,
                StudentUpdate.classroom_id.in_(self.teacher_classes()),
            )
        if pending:
            statement = statement.where(
                StudentUpdate.requires_acknowledgement.is_(True)
            )
        return statement

    async def read_updates(self, q):
        return await self._updates(q, False)

    async def read_acknowledgements(self, q):
        return await self._updates(q, True)

    async def _updates(self, q, pending):
        statement = self.updates_query(pending)
        if pending:
            statement = statement.add_columns(GuardianStudent.guardian_workos_user_id)
        if q.search:
            statement = statement.where(
                or_(
                    StudentUpdate.title.icontains(q.search, autoescape=True),
                    func.concat(Student.first_name, " ", Student.last_name).icontains(
                        q.search, autoescape=True
                    ),
                )
            )
        if q.record_id:
            statement = statement.where(StudentUpdate.id == q.record_id)
        if q.student_id:
            statement = statement.where(Student.id == q.student_id)
        if q.classroom_id:
            statement = statement.where(StudentUpdate.classroom_id == q.classroom_id)
        if pending:
            status = q.status or "pending"
            if status == "pending":
                statement = statement.where(
                    GuardianUpdateState.acknowledged_at.is_(None),
                    StudentUpdateRecipient.status != StudentUpdateStatus.COMPLETED,
                )
            if status == "acknowledged":
                statement = statement.where(
                    GuardianUpdateState.acknowledged_at.is_not(None)
                )
            if status == "read":
                statement = statement.where(GuardianUpdateState.read_at.is_not(None))
            if status == "unread":
                statement = statement.where(GuardianUpdateState.read_at.is_(None))
            if q.status is None:
                statement = statement.where(StudentUpdate.due_at < utcnow())
        elif q.status:
            statement = statement.where(StudentUpdateRecipient.status == q.status)
        if q.unread_only:
            statement = statement.where(GuardianUpdateState.read_at.is_(None))
        if q.overdue_only:
            statement = statement.where(
                StudentUpdate.due_at < utcnow(),
                StudentUpdateRecipient.status != StudentUpdateStatus.COMPLETED,
            )
        if q.date_from:
            statement = statement.where(
                func.date(StudentUpdate.created_at) >= q.date_from
            )
        if q.date_to:
            statement = statement.where(
                func.date(StudentUpdate.created_at) <= q.date_to
            )
        rows, total = await self.page(
            statement.order_by(
                StudentUpdate.created_at.desc(), StudentUpdate.id, Student.id
            ),
            q,
        )
        profiles = (
            {m["id"]: m["name"] for m in await self.school_members()}
            if pending and self.role != "guardian"
            else {}
        )
        items = []
        for row in rows:
            notice, recipient, student, state = row[:4]
            item = {
                "id": notice.id,
                "student_id": student.id,
                "student": f"{student.first_name} {student.last_name}",
                "title": notice.title,
                "body": (notice.body or "")[: 5000 if q.record_id else 600],
                "classroom_id": notice.classroom_id,
                "due_at": notice.due_at,
                "requires_acknowledgement": notice.requires_acknowledgement,
                "recipient_status": recipient.status,
            }
            if self.role == "guardian" or pending:
                item.update(
                    read_at=state.read_at if state else None,
                    acknowledged_at=state.acknowledged_at if state else None,
                )
            if pending:
                item["guardian"] = (
                    "current user"
                    if self.role == "guardian"
                    else profiles.get(row[4], "Profile unavailable")
                )
            items.append(item)
        return self.result(
            "Family acknowledgements" if pending else "Student updates",
            "/feed" if self.role == "guardian" else "/updates",
            items,
            total,
            q,
            count_unit="guardian_student_pairs"
            if pending
            else "student_update_recipients",
        )

    async def read_publications(self, q):
        if self.role == "admin":
            statement = select(SchoolPublication).where(
                SchoolPublication.organization_id == self.organization_id
            )
        else:
            statement = (
                select(SchoolPublication)
                .join(
                    PublicationRecipient,
                    PublicationRecipient.publication_id == SchoolPublication.id,
                )
                .where(
                    *_inbox_conditions(self.user_id, self.organization_id, self.role)
                )
            )
        protected_recipient = exists(
            select(PublicationRecipient.id)
            .where(
                PublicationRecipient.publication_id == SchoolPublication.id,
                or_(
                    PublicationRecipient.user_id.in_(
                        blocked_guardians(self.organization_id)
                    ),
                    exists(
                        select(Student.id)
                        .where(
                            Student.id.in_(protected_students(self.organization_id)),
                            cast(Student.id, String)
                            == any_(PublicationRecipient.student_ids),
                        )
                        .correlate(PublicationRecipient)
                    ),
                ),
            )
            .correlate(SchoolPublication)
        )
        protected_target = exists(
            select(Student.id)
            .where(
                Student.id.in_(protected_students(self.organization_id)),
                cast(Student.id, String) == any_(SchoolPublication.target_ids),
            )
            .correlate(SchoolPublication)
        )
        hidden_users = blocked_guardians(self.organization_id).subquery()
        protected_user_target = exists(
            select(hidden_users.c.guardian_user_id)
            .where(
                hidden_users.c.guardian_user_id == any_(SchoolPublication.target_ids),
            )
            .correlate(SchoolPublication)
        )
        statement = statement.where(
            SchoolPublication.author_user_id.not_in(
                blocked_guardians(self.organization_id)
            ),
            ~protected_recipient,
            ~and_(SchoolPublication.target_kind == "students", protected_target),
            ~and_(
                SchoolPublication.target_kind.in_(["guardians", "teachers"]),
                protected_user_target,
            ),
        )
        if q.search:
            statement = statement.where(
                SchoolPublication.title.icontains(q.search, autoescape=True)
            )
        if q.record_id:
            statement = statement.where(SchoolPublication.id == q.record_id)
        if q.unread_only and self.role != "admin":
            statement = statement.where(PublicationRecipient.read_at.is_(None))
        if q.date_from:
            statement = statement.where(
                func.date(SchoolPublication.created_at) >= q.date_from
            )
        if q.date_to:
            statement = statement.where(
                func.date(SchoolPublication.created_at) <= q.date_to
            )
        rows, total = await self.page(
            statement.order_by(
                SchoolPublication.created_at.desc(), SchoolPublication.id
            ),
            q,
        )
        return self.result(
            "Publications",
            "/publications",
            [
                {
                    "id": p.id,
                    "title": p.title,
                    "body": p.body[: 5000 if q.record_id else 800],
                    "created_at": p.created_at,
                }
                for (p,) in rows
            ],
            total,
            q,
        )

    async def read_calendar(self, q):
        statement = (
            select(CalendarEntry, AcademicYear)
            .join(
                AcademicCalendar,
                AcademicCalendar.id == CalendarEntry.academic_calendar_id,
            )
            .join(AcademicYear, AcademicYear.id == AcademicCalendar.academic_year_id)
            .where(AcademicYear.organization_id == self.organization_id)
        )
        if self.role != "admin":
            statement = statement.where(
                AcademicYear.status == AcademicYearStatus.ACTIVE
            )
        if q.academic_year_id:
            statement = statement.where(AcademicYear.id == q.academic_year_id)
        if q.classroom_id:
            statement = statement.where(
                AcademicYear.id.in_(
                    select(Classroom.academic_year_id).where(
                        Classroom.id == q.classroom_id,
                        Classroom.id.in_(self.classrooms()),
                    )
                )
            )
        if q.record_id:
            statement = statement.where(CalendarEntry.id == q.record_id)
        if q.search:
            statement = statement.where(
                CalendarEntry.title.icontains(q.search, autoescape=True)
            )
        if q.date_from:
            statement = statement.where(CalendarEntry.ends_on >= q.date_from)
        if q.date_to:
            statement = statement.where(CalendarEntry.starts_on <= q.date_to)
        rows, total = await self.page(
            statement.order_by(CalendarEntry.starts_on, CalendarEntry.id), q
        )
        return self.result(
            "Academic calendar",
            "/academic-years"
            if self.role == "admin"
            else "/family"
            if self.role == "guardian"
            else "/classrooms",
            [
                {
                    "id": e.id,
                    "title": e.title,
                    "type": e.entry_type,
                    "starts_on": e.starts_on,
                    "ends_on": e.ends_on,
                    "academic_year": y.name,
                }
                for e, y in rows
            ],
            total,
            q,
        )

    async def read_registrations(self, q):
        statement = (
            select(StudentRegistrationRequest, AcademicYear.name)
            .join(
                AcademicYear,
                AcademicYear.id == StudentRegistrationRequest.academic_year_id,
            )
            .where(
                StudentRegistrationRequest.organization_id == self.organization_id,
                AcademicYear.organization_id == self.organization_id,
                StudentRegistrationRequest.guardian_workos_user_id.not_in(
                    blocked_guardians(self.organization_id)
                ),
                or_(
                    StudentRegistrationRequest.resolved_student_id.is_(None),
                    StudentRegistrationRequest.resolved_student_id.not_in(
                        protected_students(self.organization_id)
                    ),
                ),
                ~exists(
                    select(Student.id).where(
                        Student.id.in_(protected_students(self.organization_id)),
                        func.lower(Student.first_name)
                        == func.lower(StudentRegistrationRequest.child_first_name),
                        func.lower(Student.last_name)
                        == func.lower(StudentRegistrationRequest.child_last_name),
                    )
                ),
            )
        )
        if self.role == "guardian":
            statement = statement.where(
                StudentRegistrationRequest.guardian_workos_user_id == self.user_id
            )
        if q.search:
            statement = statement.where(
                func.concat(
                    StudentRegistrationRequest.child_first_name,
                    " ",
                    StudentRegistrationRequest.child_last_name,
                ).icontains(q.search, autoescape=True)
            )
        if q.status:
            statement = statement.where(StudentRegistrationRequest.status == q.status)
        if q.record_id:
            statement = statement.where(StudentRegistrationRequest.id == q.record_id)
        if q.academic_year_id:
            statement = statement.where(AcademicYear.id == q.academic_year_id)
        rows, total = await self.page(
            statement.order_by(
                StudentRegistrationRequest.created_at.desc(),
                StudentRegistrationRequest.id,
            ),
            q,
        )
        return self.result(
            "Registration requests",
            "/registrations",
            [
                {
                    "id": r.id,
                    "child": f"{r.child_first_name} {r.child_last_name}",
                    "academic_year": name,
                    "status": r.status,
                    "rejection_reason": r.rejection_reason,
                }
                for r, name in rows
            ],
            total,
            q,
        )

    async def read_invitations(self, q):
        # Invitations have email addresses but no reliable recipient user ID.
        # Withhold this dataset if opt-outs exist rather than risk identifying a
        # protected person via an older email, name, role or invitation state.
        if await self.session.scalar(
            exists(blocked_guardians(self.organization_id)).select()
        ):
            return {
                "status": "privacy_restricted",
                "message": "Invitation records cannot be safely isolated under the current chat privacy settings. Use the invitations screen.",
            }
        statement = select(Invitation).where(
            Invitation.organization_id == self.organization_id
        )
        if q.search:
            statement = statement.where(
                or_(
                    Invitation.email.icontains(q.search, autoescape=True),
                    func.concat(
                        Invitation.first_name, " ", Invitation.last_name
                    ).icontains(q.search, autoescape=True),
                )
            )
        if q.status:
            statement = statement.where(
                or_(
                    Invitation.send_status == q.status,
                    Invitation.workos_state == q.status,
                )
            )
        if q.record_id:
            statement = statement.where(Invitation.id == q.record_id)
        rows, total = await self.page(
            statement.order_by(Invitation.created_at.desc(), Invitation.id), q
        )
        return self.result(
            "Invitations",
            "/invitations",
            [
                {
                    "id": i.id,
                    "name": f"{i.first_name or ''} {i.last_name or ''}".strip(),
                    "email": i.email,
                    "role": i.role_slug,
                    "send_status": i.send_status,
                    "acceptance_status": i.workos_state,
                    "expires_at": i.expires_at,
                }
                for (i,) in rows
            ],
            total,
            q,
        )

    async def read_members(self, q):
        hidden = set(
            await self.session.scalars(blocked_guardians(self.organization_id))
        )
        members = [
            item
            for item in await self.school_members()
            if item["id"] not in hidden
            if (
                not q.search
                or q.search.casefold()
                in f"{item['name']} {item['email']} {' '.join(item['roles'])}".casefold()
            )
            and (not q.status or q.status in item["roles"])
        ]
        return self.result(
            "School members",
            "/members",
            [
                {key: item[key] for key in ("id", "name", "email", "roles", "status")}
                for item in members[q.offset : q.offset + q.limit]
            ],
            len(members),
            q,
        )

    async def search_policies(self, keywords):
        await self.ensure_access()
        words = list(
            dict.fromkeys(
                word
                for keyword in keywords
                for word in re.findall(r"[^\W\d_]{3,40}", normalize_search(keyword))
            )
        )[:12]
        if not words:
            return {
                "status": "ok",
                "items": [],
                "message": "Use topic keywords with at least three letters.",
            }
        terms = func.websearch_to_tsquery(
            "simple", " OR ".join(f'"{word}"' for word in words)
        )
        rows = (
            await self.session.scalars(
                select(SchoolPolicyPassage)
                .where(
                    SchoolPolicyPassage.organization_id == self.organization_id,
                    SchoolPolicyPassage.search_vector.bool_op("@@")(terms),
                )
                .order_by(
                    func.ts_rank(SchoolPolicyPassage.search_vector, terms).desc(),
                    SchoolPolicyPassage.id,
                )
                .limit(3)
            )
        ).all()
        result = {
            "status": "ok",
            "items": [
                {
                    "source_id": self.source(
                        p.title,
                        "/settings"
                        if self.role == "admin"
                        else "/school-policies"
                        if self.role == "guardian"
                        else None,
                        p.excerpt,
                        key=("policy", p.id),
                    ),
                    "title": p.title,
                    "heading": p.heading,
                    "excerpt": p.excerpt,
                }
                for p in rows
            ],
            "no_matching_policy": not bool(rows),
        }
        await self.ensure_access()
        return result
