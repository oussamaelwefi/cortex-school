import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.students.models import GuardianStudent, Student
from modules.students.schemas import (
    GuardianCreateRequest,
    GuardianResponse,
    StudentCreateRequest,
    StudentResponse,
    StudentUpdateRequest,
)
from modules.students.services import (
    _get_guardian,
    _get_student,
    _require_active_guardian,
    guardian_ids_by_student,
)

router = APIRouter(
    prefix="/students",
    tags=["Students"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@router.post("/", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    payload: StudentCreateRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to an organization",
        )
    student = Student(
        organization_id=organization_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    session.add(student)
    await session.commit()
    await session.refresh(student)
    return student


@router.get("/", response_model=list[StudentResponse])
async def list_students(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    result = await session.scalars(
        select(Student)
        .where(Student.organization_id == current_user.get("organization_id"))
        .order_by(Student.created_at.desc())
    )
    students = list(result.all())
    guardians = await guardian_ids_by_student(
        session, current_user.get("organization_id"), [student.id for student in students],
    )
    return [StudentResponse.model_validate(student).model_copy(update={
        "guardian_ids": guardians.get(student.id, []),
    }) for student in students]


@router.get("/{student_id}/", response_model=StudentResponse)
async def get_student(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    student = await _get_student(session, student_id, current_user)
    guardians = await guardian_ids_by_student(session, student.organization_id, [student.id])
    return StudentResponse.model_validate(student).model_copy(update={"guardian_ids": guardians.get(student.id, [])})


@router.patch("/{student_id}/", response_model=StudentResponse)
async def update_student(
    student_id: uuid.UUID,
    payload: StudentUpdateRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    student = await _get_student(session, student_id, current_user)
    if payload.first_name is not None:
        student.first_name = payload.first_name
    if payload.last_name is not None:
        student.last_name = payload.last_name
    await session.commit()
    await session.refresh(student)
    guardians = await guardian_ids_by_student(session, student.organization_id, [student.id])
    return StudentResponse.model_validate(student).model_copy(update={"guardian_ids": guardians.get(student.id, [])})


@router.post(
    "/{student_id}/guardians/",
    response_model=GuardianResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_guardian(
    student_id: uuid.UUID,
    payload: GuardianCreateRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    student = await _get_student(session, student_id, current_user)
    await _require_active_guardian(
        payload.guardian_workos_user_id,
        student.organization_id,
    )

    guardian = GuardianStudent(
        student_id=student_id,
        guardian_workos_user_id=payload.guardian_workos_user_id,
    )
    session.add(guardian)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Guardian is already linked to this student",
        ) from exc
    await session.refresh(guardian)
    return guardian


@router.get(
    "/{student_id}/guardians/",
    response_model=list[GuardianResponse],
)
async def list_guardians(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    await _get_student(session, student_id, current_user)
    result = await session.scalars(
        select(GuardianStudent)
        .where(GuardianStudent.student_id == student_id)
        .order_by(GuardianStudent.created_at.desc())
    )
    return list(result.all())


@router.delete(
    "/{student_id}/guardians/{guardian_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_guardian(
    student_id: uuid.UUID,
    guardian_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    guardian = await _get_guardian(session, student_id, guardian_id, current_user)
    await session.delete(guardian)
    await session.commit()
