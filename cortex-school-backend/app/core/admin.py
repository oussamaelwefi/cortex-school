import uuid

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqladmin.filters import AllUniqueStringValuesFilter
from starlette.requests import Request
from starlette.responses import RedirectResponse

from core.auth import has_operator_session, is_workos_operator, verify_workos_access_token
from core.config import settings
from core.db import SessionLocal, engine
from modules.academic_years.models import (
    AcademicCalendar,
    AcademicYear,
    AcademicYearStatus,
    CalendarEntry,
)
from modules.academic_years.services import require_academic_year_publishable
from modules.classrooms.models import (
    ClassEnrollment,
    Classroom,
    TeacherAssignment,
)
from modules.enrollments.models import Enrollment
from modules.invitations.models import Invitation
from modules.invitations.services import (
    get_invitation,
    should_enqueue_invitation,
)
from modules.invitations.tasks import enqueue_invitation_task
from modules.schools.models import Country, School


class AdminAuth(AuthenticationBackend):
    def __init__(self) -> None:
        # The app supplies the signed session for both SQLAdmin and API documentation.
        self.middlewares = []

    async def login(self, request: Request) -> bool:
        form = await request.form()
        token = form.get("access_token")
        if not isinstance(token, str) or not token.strip():
            return False
        try:
            claims = await run_in_threadpool(verify_workos_access_token, token.strip())
        except HTTPException:
            return False
        user_id = claims["sub"]
        if not is_workos_operator(user_id):
            return False

        request.session.clear()
        request.session["workos_operator"] = {"user_id": user_id, "expires_at": int(claims["exp"])}
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return has_operator_session(request)


class InvitationAdmin(ModelView, model=Invitation):
    name = "Invitation"
    name_plural = "Invitations"
    icon = "fa-solid fa-envelope"

    column_list = [
        Invitation.id,
        Invitation.email,
        Invitation.organization_id,
        Invitation.send_status,
        Invitation.attempt_count,
        Invitation.workos_state,
        Invitation.sent_at,
        Invitation.created_at,
    ]
    column_searchable_list = [
        Invitation.email,
        Invitation.organization_id,
        Invitation.workos_invitation_id,
    ]
    column_filters = [
        AllUniqueStringValuesFilter(
            Invitation.organization_id,
            title="Organization ID",
        ),
    ]
    column_sortable_list = [
        Invitation.email,
        Invitation.send_status,
        Invitation.attempt_count,
        Invitation.sent_at,
        Invitation.created_at,
    ]
    form_excluded_columns = [
        "id",
        "created_at",
        "updated_at",
    ]
    form_create_rules = [
        "organization_id",
        "email",
        "role_slug",
        "expires_in_days",
    ]
    can_create = True
    can_edit = False
    can_delete = False

    async def after_model_change(
        self,
        data: dict,
        model: Invitation,
        is_created: bool,
        request: Request,
    ) -> None:
        if not is_created:
            return

        async with SessionLocal() as session:
            invitation = await get_invitation(session, model.id)
            try:
                await enqueue_invitation_task(session, invitation)
            except Exception:
                return

    @action(
        name="send_workos_invitation",
        label="Send WorkOS invitation",
        confirmation_message="Send selected invitations through WorkOS?",
        add_in_detail=True,
        add_in_list=True,
    )
    async def send_workos_invitation(self, request: Request):
        pks = [pk for pk in request.query_params.get("pks", "").split(",") if pk]

        async with SessionLocal() as session:
            for pk in pks:
                invitation = await get_invitation(session, uuid.UUID(pk))
                if not should_enqueue_invitation(invitation):
                    continue

                try:
                    await enqueue_invitation_task(session, invitation)
                except Exception:
                    continue

        referer = request.headers.get("Referer")
        if referer:
            return RedirectResponse(referer)
        return RedirectResponse(request.url_for("admin:list", identity=self.identity))


class CountryAdmin(ModelView, model=Country):
    name = "Country"
    name_plural = "Countries"
    icon = "fa-solid fa-earth-africa"
    column_list = [Country.code, Country.name, Country.calling_code]
    column_searchable_list = [Country.code, Country.name, Country.calling_code]
    column_sortable_list = [Country.code, Country.name]
    can_delete = False


class SchoolAdmin(ModelView, model=School):
    name = "School"
    name_plural = "Schools"
    icon = "fa-solid fa-school"
    column_list = [
        School.organization_id,
        School.country_code,
        School.timezone,
        School.instructional_weekdays,
    ]
    column_searchable_list = [School.organization_id, School.country_code]
    column_sortable_list = [School.organization_id, School.country_code]
    form_include_pk = True
    form_columns = [School.organization_id, School.country_code]
    can_delete = False


class AcademicYearSupportAdmin(ModelView, model=AcademicYear):
    name = "Academic Year"
    name_plural = "Academic Years"
    icon = "fa-solid fa-calendar-days"
    column_list = [
        AcademicYear.id,
        AcademicYear.organization_id,
        AcademicYear.name,
        AcademicYear.starts_on,
        AcademicYear.ends_on,
        AcademicYear.status,
        AcademicYear.updated_at,
    ]
    column_searchable_list = [AcademicYear.organization_id, AcademicYear.name]
    column_filters = [
        AllUniqueStringValuesFilter(
            AcademicYear.organization_id,
            title="Organization ID",
        ),
        AllUniqueStringValuesFilter(AcademicYear.status, title="Status"),
    ]
    column_sortable_list = [
        AcademicYear.organization_id,
        AcademicYear.name,
        AcademicYear.starts_on,
        AcademicYear.ends_on,
        AcademicYear.status,
        AcademicYear.updated_at,
    ]
    can_create = False
    can_edit = False
    can_delete = False

    @action(
        name="publish_academic_year",
        label="Publish academic year",
        confirmation_message="Publish selected draft academic years that are ready?",
        add_in_detail=True,
        add_in_list=True,
    )
    async def publish_academic_year(self, request: Request):
        pks = [pk for pk in request.query_params.get("pks", "").split(",") if pk]

        async with SessionLocal() as session:
            for pk in pks:
                year = await session.scalar(
                    select(AcademicYear)
                    .where(AcademicYear.id == uuid.UUID(pk))
                    .with_for_update()
                )
                if year is None or year.status != AcademicYearStatus.DRAFT:
                    continue
                try:
                    await require_academic_year_publishable(session, year)
                except HTTPException:
                    continue
                year.status = AcademicYearStatus.ACTIVE
            await session.commit()

        referer = request.headers.get("Referer")
        if referer:
            return RedirectResponse(referer)
        return RedirectResponse(request.url_for("admin:list", identity=self.identity))

    @action(
        name="close_academic_year",
        label="Close academic year",
        confirmation_message="Close selected active academic years?",
        add_in_detail=True,
        add_in_list=True,
    )
    async def close_academic_year(self, request: Request):
        pks = [pk for pk in request.query_params.get("pks", "").split(",") if pk]

        async with SessionLocal() as session:
            for pk in pks:
                year = await session.scalar(
                    select(AcademicYear)
                    .where(AcademicYear.id == uuid.UUID(pk))
                    .with_for_update()
                )
                if year is None or year.status != AcademicYearStatus.ACTIVE:
                    continue
                year.status = AcademicYearStatus.CLOSED
            await session.commit()

        referer = request.headers.get("Referer")
        if referer:
            return RedirectResponse(referer)
        return RedirectResponse(request.url_for("admin:list", identity=self.identity))


class ReadOnlySupportMixin:
    can_create = False
    can_edit = False
    can_delete = False


class AcademicCalendarSupportAdmin(
    ReadOnlySupportMixin,
    ModelView,
    model=AcademicCalendar,
):
    name = "Academic Calendar"
    name_plural = "Academic Calendars"
    icon = "fa-solid fa-calendar"
    column_list = [
        AcademicCalendar.id,
        AcademicCalendar.academic_year_id,
        AcademicCalendar.updated_at,
    ]


class CalendarEntrySupportAdmin(
    ReadOnlySupportMixin,
    ModelView,
    model=CalendarEntry,
):
    name = "Calendar Entry"
    name_plural = "Calendar Entries"
    icon = "fa-solid fa-calendar-day"
    column_list = [
        CalendarEntry.id,
        CalendarEntry.academic_calendar_id,
        CalendarEntry.entry_type,
        CalendarEntry.title,
        CalendarEntry.starts_on,
        CalendarEntry.ends_on,
    ]


class ClassroomSupportAdmin(ReadOnlySupportMixin, ModelView, model=Classroom):
    name = "Classroom"
    name_plural = "Classrooms"
    icon = "fa-solid fa-chalkboard"
    column_list = [
        Classroom.id,
        Classroom.academic_year_id,
        Classroom.name,
        Classroom.updated_at,
    ]


class EnrollmentSupportAdmin(ReadOnlySupportMixin, ModelView, model=Enrollment):
    name = "Enrollment"
    name_plural = "Enrollments"
    icon = "fa-solid fa-user-graduate"
    column_list = [
        Enrollment.id,
        Enrollment.student_id,
        Enrollment.academic_year_id,
        Enrollment.updated_at,
    ]


class ClassEnrollmentSupportAdmin(
    ReadOnlySupportMixin,
    ModelView,
    model=ClassEnrollment,
):
    name = "Class Placement"
    name_plural = "Class Placements"
    icon = "fa-solid fa-people-group"
    column_list = [
        ClassEnrollment.id,
        ClassEnrollment.classroom_id,
        ClassEnrollment.enrollment_id,
        ClassEnrollment.effective_from,
        ClassEnrollment.effective_until,
    ]


class TeacherAssignmentSupportAdmin(
    ReadOnlySupportMixin,
    ModelView,
    model=TeacherAssignment,
):
    name = "Teacher Assignment"
    name_plural = "Teacher Assignments"
    icon = "fa-solid fa-person-chalkboard"
    column_list = [
        TeacherAssignment.id,
        TeacherAssignment.classroom_id,
        TeacherAssignment.teacher_workos_user_id,
        TeacherAssignment.role,
        TeacherAssignment.effective_from,
        TeacherAssignment.effective_until,
    ]


def setup_admin(app) -> None:
    admin = Admin(
        app=app,
        engine=engine,
        authentication_backend=AdminAuth(),
        templates_dir=str(settings.ROOT_PATH / "templates"),
    )
    admin.add_view(InvitationAdmin)
    admin.add_view(CountryAdmin)
    admin.add_view(SchoolAdmin)
    admin.add_view(AcademicYearSupportAdmin)
    admin.add_view(AcademicCalendarSupportAdmin)
    admin.add_view(CalendarEntrySupportAdmin)
    admin.add_view(ClassroomSupportAdmin)
    admin.add_view(EnrollmentSupportAdmin)
    admin.add_view(ClassEnrollmentSupportAdmin)
    admin.add_view(TeacherAssignmentSupportAdmin)
