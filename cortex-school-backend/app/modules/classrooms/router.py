import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.academic_years.models import CalendarEntry
from modules.academic_years.schemas import AcademicCalendarResponse
from modules.academic_years.services import (
    _get_academic_calendar,
    _get_academic_year,
)
from modules.classrooms.models import ClassEnrollment, Classroom, TeacherAssignment
from modules.classrooms.schemas import (
    ClassEnrollmentCreateRequest,
    ClassEnrollmentResponse,
    ClassroomRequest,
    ClassroomResponse,
    ClassTransferRequest,
    TeacherAssignmentCreateRequest,
    TeacherAssignmentEndRequest,
    TeacherAssignmentResponse,
)
from modules.classrooms.services import (
    _find_overlapping_placement,
    _get_classroom,
    _get_enrollment_for_update,
    _get_teacher_assignment,
    _require_active_teacher,
    _require_no_placement_overlap,
    _require_no_teacher_assignment_overlap,
    _require_same_academic_year,
    _require_year_writable,
    _validate_placement_dates,
    _validate_teacher_assignment_dates,
)
from modules.enrollments.services import _get_enrollment

router = APIRouter(
    tags=["Classrooms"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@router.post(
    "/academic-years/{year_id}/classrooms/",
    response_model=ClassroomResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_classroom(
    year_id: uuid.UUID,
    payload: ClassroomRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    year = await _get_academic_year(
        session,
        year_id,
        current_user,
        for_update=True,
    )
    _require_year_writable(year)
    classroom = Classroom(academic_year_id=year.id, name=payload.name)
    session.add(classroom)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Classroom name already exists in this academic year",
        ) from exc
    await session.refresh(classroom)
    return classroom


@router.get(
    "/academic-years/{year_id}/classrooms/",
    response_model=list[ClassroomResponse],
)
async def list_classrooms(
    year_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    year = await _get_academic_year(session, year_id, current_user)
    result = await session.scalars(
        select(Classroom)
        .where(Classroom.academic_year_id == year.id)
        .order_by(Classroom.name)
    )
    return list(result.all())


@router.get("/classrooms/{classroom_id}/", response_model=ClassroomResponse)
async def get_classroom(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    classroom, _ = await _get_classroom(session, classroom_id, current_user)
    return classroom


@router.put("/classrooms/{classroom_id}/", response_model=ClassroomResponse)
async def replace_classroom(
    classroom_id: uuid.UUID,
    payload: ClassroomRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    classroom, year = await _get_classroom(
        session,
        classroom_id,
        current_user,
        for_update=True,
    )
    _require_year_writable(year)
    classroom.name = payload.name
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Classroom name already exists in this academic year",
        ) from exc
    await session.refresh(classroom)
    return classroom


@router.delete(
    "/classrooms/{classroom_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_classroom(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    classroom, year = await _get_classroom(
        session,
        classroom_id,
        current_user,
        for_update=True,
    )
    _require_year_writable(year)

    placement_id = await session.scalar(
        select(ClassEnrollment.id)
        .where(ClassEnrollment.classroom_id == classroom.id)
        .limit(1)
    )
    assignment_id = await session.scalar(
        select(TeacherAssignment.id)
        .where(TeacherAssignment.classroom_id == classroom.id)
        .limit(1)
    )
    if placement_id is not None or assignment_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Classrooms with placement or teacher assignment history "
                "cannot be deleted"
            ),
        )

    await session.delete(classroom)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Classroom history prevents deletion",
        ) from exc


@router.get(
    "/classrooms/{classroom_id}/calendar/",
    response_model=AcademicCalendarResponse,
)
async def get_classroom_calendar(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    _, year = await _get_classroom(session, classroom_id, current_user)
    calendar = await _get_academic_calendar(session, year)
    entries = list(
        (
            await session.scalars(
                select(CalendarEntry)
                .where(CalendarEntry.academic_calendar_id == calendar.id)
                .order_by(CalendarEntry.starts_on, CalendarEntry.title)
            )
        ).all()
    )
    return AcademicCalendarResponse(
        id=calendar.id,
        academic_year_id=calendar.academic_year_id,
        entries=entries,
        created_at=calendar.created_at,
        updated_at=calendar.updated_at,
    )


@router.post(
    "/classrooms/{classroom_id}/placements/",
    response_model=ClassEnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_class_placement(
    classroom_id: uuid.UUID,
    payload: ClassEnrollmentCreateRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    try:
        enrollment = await _get_enrollment_for_update(
            session,
            payload.enrollment_id,
            current_user,
        )
        classroom, year = await _get_classroom(
            session,
            classroom_id,
            current_user,
            for_update=True,
        )
        _require_same_academic_year(classroom, enrollment)
        _require_year_writable(year)
        _validate_placement_dates(
            year,
            payload.effective_from,
            payload.effective_until,
        )
        await _require_no_placement_overlap(
            session,
            enrollment.id,
            payload.effective_from,
            payload.effective_until,
        )
        placement = ClassEnrollment(
            classroom_id=classroom.id,
            enrollment_id=enrollment.id,
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
        )
        session.add(placement)
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student already has an overlapping class placement",
        ) from exc
    await session.refresh(placement)
    return placement


@router.get(
    "/classrooms/{classroom_id}/placements/",
    response_model=list[ClassEnrollmentResponse],
)
async def list_classroom_placements(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    classroom, _ = await _get_classroom(session, classroom_id, current_user)
    result = await session.scalars(
        select(ClassEnrollment)
        .where(ClassEnrollment.classroom_id == classroom.id)
        .order_by(ClassEnrollment.effective_from.desc())
    )
    return list(result.all())


@router.get(
    "/enrollments/{enrollment_id}/placements/",
    response_model=list[ClassEnrollmentResponse],
)
async def list_enrollment_placements(
    enrollment_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    enrollment = await _get_enrollment(session, enrollment_id, current_user)
    result = await session.scalars(
        select(ClassEnrollment)
        .where(ClassEnrollment.enrollment_id == enrollment.id)
        .order_by(ClassEnrollment.effective_from.desc())
    )
    return list(result.all())


@router.post(
    "/enrollments/{enrollment_id}/transfer/",
    response_model=ClassEnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def transfer_enrollment(
    enrollment_id: uuid.UUID,
    payload: ClassTransferRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    try:
        enrollment = await _get_enrollment_for_update(
            session,
            enrollment_id,
            current_user,
        )
        target_classroom, year = await _get_classroom(
            session,
            payload.classroom_id,
            current_user,
            for_update=True,
        )
        _require_same_academic_year(target_classroom, enrollment)
        _require_year_writable(year)
        _validate_placement_dates(year, payload.effective_from, None)

        current_placement = await session.scalar(
            select(ClassEnrollment)
            .where(
                ClassEnrollment.enrollment_id == enrollment.id,
                ClassEnrollment.effective_from < payload.effective_from,
                or_(
                    ClassEnrollment.effective_until.is_(None),
                    ClassEnrollment.effective_until > payload.effective_from,
                ),
            )
            .order_by(ClassEnrollment.effective_from.desc())
            .limit(1)
        )
        if current_placement is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No current class placement exists on the transfer date",
            )
        if current_placement.classroom_id == target_classroom.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Enrollment is already placed in the target classroom",
            )

        future_overlap = await _find_overlapping_placement(
            session,
            enrollment.id,
            payload.effective_from,
            None,
            exclude_id=current_placement.id,
        )
        if future_overlap is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Student already has an overlapping class placement",
            )

        current_placement.effective_until = payload.effective_from
        await session.flush()
        new_placement = ClassEnrollment(
            classroom_id=target_classroom.id,
            enrollment_id=enrollment.id,
            effective_from=payload.effective_from,
            effective_until=None,
        )
        session.add(new_placement)
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student already has an overlapping class placement",
        ) from exc
    await session.refresh(new_placement)
    return new_placement


@router.post(
    "/classrooms/{classroom_id}/teacher-assignments/",
    response_model=TeacherAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_teacher_assignment(
    classroom_id: uuid.UUID,
    payload: TeacherAssignmentCreateRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    try:
        _, initial_year = await _get_classroom(
            session,
            classroom_id,
            current_user,
        )
        _require_year_writable(initial_year)
        _validate_teacher_assignment_dates(
            initial_year,
            payload.effective_from,
            payload.effective_until,
        )
        await _require_active_teacher(
            payload.teacher_workos_user_id,
            initial_year.organization_id,
        )

        classroom, year = await _get_classroom(
            session,
            classroom_id,
            current_user,
            for_update=True,
        )
        _require_year_writable(year)
        _validate_teacher_assignment_dates(
            year,
            payload.effective_from,
            payload.effective_until,
        )
        await _require_no_teacher_assignment_overlap(
            session,
            classroom.id,
            payload.teacher_workos_user_id,
            payload.effective_from,
            payload.effective_until,
        )
        assignment = TeacherAssignment(
            classroom_id=classroom.id,
            teacher_workos_user_id=payload.teacher_workos_user_id,
            role=payload.role,
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
        )
        session.add(assignment)
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Teacher already has an overlapping assignment in this classroom"
            ),
        ) from exc
    await session.refresh(assignment)
    return assignment


@router.get(
    "/classrooms/{classroom_id}/teacher-assignments/",
    response_model=list[TeacherAssignmentResponse],
)
async def list_teacher_assignments(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    classroom, _ = await _get_classroom(session, classroom_id, current_user)
    result = await session.scalars(
        select(TeacherAssignment)
        .where(TeacherAssignment.classroom_id == classroom.id)
        .order_by(
            TeacherAssignment.effective_from.desc(),
            TeacherAssignment.teacher_workos_user_id,
        )
    )
    return list(result.all())


@router.post(
    "/teacher-assignments/{assignment_id}/end/",
    response_model=TeacherAssignmentResponse,
)
async def end_teacher_assignment(
    assignment_id: uuid.UUID,
    payload: TeacherAssignmentEndRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    assignment, year = await _get_teacher_assignment(
        session,
        assignment_id,
        current_user,
        for_update=True,
    )
    _require_year_writable(year)
    if assignment.effective_until is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Teacher assignment has already ended",
        )
    if payload.effective_until <= assignment.effective_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="effective_until must be after effective_from",
        )
    _validate_teacher_assignment_dates(
        year,
        assignment.effective_from,
        payload.effective_until,
    )
    assignment.effective_until = payload.effective_until
    await session.commit()
    await session.refresh(assignment)
    return assignment
