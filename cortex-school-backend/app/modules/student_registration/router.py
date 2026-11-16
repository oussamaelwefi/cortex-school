import uuid

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.academic_years.schemas import AcademicYearResponse
from modules.enrollments.models import Enrollment
from modules.student_registration.models import (
    StudentRegistrationRequest,
    StudentRegistrationStatus,
)
from modules.student_registration.schemas import (
    GuardianEnrollmentResponse,
    GuardianStudentResponse,
    StudentRegistrationApproval,
    StudentRegistrationRejection,
    StudentRegistrationRequestCreate,
    StudentRegistrationRequestResponse,
    StudentRegistrationRequestUpdate,
)
from modules.student_registration.services import (
    approve_registration_request,
    create_registration_request,
    reject_registration_request,
    require_active_guardian,
    update_registration_request,
    withdraw_registration_request,
)
from modules.students.models import GuardianStudent, Student

guardian_router = APIRouter(
    prefix="/guardian",
    tags=["Guardian"],
    dependencies=[Depends(require_active_guardian)],
)
admin_router = APIRouter(
    prefix="/registration-requests",
    tags=["Registration Requests"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@guardian_router.get("/academic-years/", response_model=list[AcademicYearResponse])
async def list_guardian_academic_years(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    result = await session.scalars(
        select(AcademicYear)
        .where(
            AcademicYear.organization_id == current_user["organization_id"],
            AcademicYear.status == AcademicYearStatus.ACTIVE,
        )
        .order_by(AcademicYear.starts_on.desc())
    )
    return list(result.all())


async def _list_linked_students(
    session: AsyncSession,
    current_user: dict,
    student_id: uuid.UUID | None = None,
) -> list[GuardianStudentResponse]:
    students_query = (
        select(Student)
        .join(GuardianStudent, GuardianStudent.student_id == Student.id)
        .where(
            GuardianStudent.guardian_workos_user_id == current_user["user_id"],
            Student.organization_id == current_user["organization_id"],
        )
        .order_by(Student.created_at.desc())
    )
    if student_id is not None:
        students_query = students_query.where(Student.id == student_id)

    students = list((await session.scalars(students_query)).all())
    if not students:
        return []

    student_ids = [student.id for student in students]
    rows = (
        await session.execute(
            select(Enrollment, AcademicYear)
            .join(AcademicYear, AcademicYear.id == Enrollment.academic_year_id)
            .where(
                Enrollment.student_id.in_(student_ids),
                AcademicYear.organization_id == current_user["organization_id"],
            )
            .order_by(AcademicYear.starts_on.desc())
        )
    ).all()

    enrollments_by_student: dict[uuid.UUID, list[GuardianEnrollmentResponse]] = {
        student_id: [] for student_id in student_ids
    }
    for enrollment, academic_year in rows:
        enrollments_by_student[enrollment.student_id].append(
            GuardianEnrollmentResponse(
                id=enrollment.id,
                academic_year=AcademicYearResponse.model_validate(academic_year),
                created_at=enrollment.created_at,
                updated_at=enrollment.updated_at,
            )
        )

    return [
        GuardianStudentResponse(
            id=student.id,
            first_name=student.first_name,
            last_name=student.last_name,
            enrollments=enrollments_by_student[student.id],
            created_at=student.created_at,
            updated_at=student.updated_at,
        )
        for student in students
    ]


@guardian_router.get("/students/", response_model=list[GuardianStudentResponse])
async def list_guardian_students(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await _list_linked_students(session, current_user)


@guardian_router.get("/students/{student_id}/", response_model=GuardianStudentResponse)
async def get_guardian_student(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    students = await _list_linked_students(session, current_user, student_id)
    if not students:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )
    return students[0]


@guardian_router.post(
    "/registration-requests/",
    response_model=StudentRegistrationRequestResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Guardian Registration Requests"],
)
async def create_guardian_registration_request(
    payload: StudentRegistrationRequestCreate,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await create_registration_request(
        session,
        payload,
        current_user["user_id"],
        current_user["organization_id"],
    )


@guardian_router.get(
    "/registration-requests/",
    response_model=list[StudentRegistrationRequestResponse],
    tags=["Guardian Registration Requests"],
)
async def list_guardian_registration_requests(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    result = await session.scalars(
        select(StudentRegistrationRequest)
        .where(
            StudentRegistrationRequest.guardian_workos_user_id
            == current_user["user_id"],
            StudentRegistrationRequest.organization_id
            == current_user["organization_id"],
        )
        .order_by(StudentRegistrationRequest.created_at.desc())
    )
    return list(result.all())


@guardian_router.put(
    "/registration-requests/{request_id}/",
    response_model=StudentRegistrationRequestResponse,
    tags=["Guardian Registration Requests"],
)
async def edit_guardian_registration_request(
    request_id: uuid.UUID,
    payload: StudentRegistrationRequestUpdate,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await update_registration_request(
        session,
        request_id,
        payload,
        current_user["user_id"],
        current_user["organization_id"],
    )


@guardian_router.post(
    "/registration-requests/{request_id}/withdraw/",
    response_model=StudentRegistrationRequestResponse,
    tags=["Guardian Registration Requests"],
)
async def withdraw_guardian_registration_request(
    request_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await withdraw_registration_request(
        session,
        request_id,
        current_user["user_id"],
        current_user["organization_id"],
    )


@admin_router.get(
    "/",
    response_model=list[StudentRegistrationRequestResponse],
)
async def list_school_registration_requests(
    request_status: StudentRegistrationStatus | None = Query(
        default=None,
        alias="status",
    ),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    query = select(StudentRegistrationRequest).where(
        StudentRegistrationRequest.organization_id
        == current_user["organization_id"]
    )
    if request_status is not None:
        query = query.where(StudentRegistrationRequest.status == request_status)

    result = await session.scalars(
        query.order_by(StudentRegistrationRequest.created_at.desc())
    )
    return list(result.all())


@admin_router.post(
    "/{request_id}/approve/",
    response_model=StudentRegistrationRequestResponse,
)
async def approve_school_registration_request(
    request_id: uuid.UUID,
    payload: StudentRegistrationApproval,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await approve_registration_request(
        session,
        request_id,
        payload,
        current_user["organization_id"],
    )


@admin_router.post(
    "/{request_id}/reject/",
    response_model=StudentRegistrationRequestResponse,
)
async def reject_school_registration_request(
    request_id: uuid.UUID,
    payload: StudentRegistrationRejection,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await reject_registration_request(
        session,
        request_id,
        payload.reason,
        current_user["organization_id"],
    )


router = APIRouter()
router.include_router(guardian_router)
router.include_router(admin_router)
