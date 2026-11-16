import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.academic_years.models import (
    AcademicCalendar,
    AcademicYear,
    AcademicYearStatus,
    CalendarEntry,
)
from modules.academic_years.schemas import (
    AcademicCalendarResponse,
    AcademicYearCreateRequest,
    AcademicYearReadinessResponse,
    AcademicYearResponse,
    CalendarEntryRequest,
    CalendarEntryResponse,
)
from modules.academic_years.services import (
    _commit_year,
    _get_academic_calendar,
    _get_academic_year,
    _get_calendar_entry,
    _require_draft_year,
    _require_year_writable,
    _validate_academic_year_dates_against_history,
    _validate_calendar_entry_dates,
    get_academic_year_readiness,
    require_academic_year_publishable,
)
from modules.schools.models import School

router = APIRouter(
    prefix="/academic-years",
    tags=["Academic Years"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@router.post("/", response_model=AcademicYearResponse, status_code=status.HTTP_201_CREATED)
async def create_academic_year(
    payload: AcademicYearCreateRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to an organization",
        )
    if await session.get(School, organization_id) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="School country must be configured first",
        )

    year = AcademicYear(
        organization_id=organization_id,
        name=payload.name,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        status=AcademicYearStatus.DRAFT,
    )
    session.add(year)
    try:
        await session.flush()
        session.add(AcademicCalendar(academic_year_id=year.id))
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Academic year name already exists for this school",
        ) from exc
    await session.refresh(year)
    return year


@router.get("/", response_model=list[AcademicYearResponse])
async def list_academic_years(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    result = await session.scalars(
        select(AcademicYear)
        .where(AcademicYear.organization_id == current_user.get("organization_id"))
        .order_by(AcademicYear.starts_on.desc())
    )
    return list(result.all())


@router.get("/{year_id}/", response_model=AcademicYearResponse)
async def get_academic_year(
    year_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await _get_academic_year(session, year_id, current_user)


@router.put("/{year_id}/", response_model=AcademicYearResponse)
async def replace_academic_year(
    year_id: uuid.UUID,
    payload: AcademicYearCreateRequest,
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
    await _validate_academic_year_dates_against_history(
        session,
        year,
        payload.starts_on,
        payload.ends_on,
    )
    year.name = payload.name
    year.starts_on = payload.starts_on
    year.ends_on = payload.ends_on
    await _commit_year(session, year)
    return year


@router.post("/{year_id}/publish/", response_model=AcademicYearResponse)
async def publish_academic_year(
    year_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    year = await _get_academic_year(
        session,
        year_id,
        current_user,
        for_update=True,
    )
    _require_draft_year(year)
    readiness = await require_academic_year_publishable(session, year)
    year.status = AcademicYearStatus.ACTIVE
    await session.commit()
    await session.refresh(year)
    return AcademicYearResponse.model_validate(year).model_copy(
        update={"warnings": readiness.warnings}
    )


@router.get(
    "/{year_id}/readiness/",
    response_model=AcademicYearReadinessResponse,
)
async def get_academic_year_publish_readiness(
    year_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    year = await _get_academic_year(session, year_id, current_user)
    readiness = await get_academic_year_readiness(session, year)
    return AcademicYearReadinessResponse(
        can_publish=readiness.can_publish,
        errors=readiness.errors,
        warnings=readiness.warnings,
    )


@router.post("/{year_id}/close/", response_model=AcademicYearResponse)
async def close_academic_year(
    year_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    year = await _get_academic_year(
        session,
        year_id,
        current_user,
        for_update=True,
    )
    if year.status != AcademicYearStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only active academic years can be closed",
        )
    year.status = AcademicYearStatus.CLOSED
    await session.commit()
    await session.refresh(year)
    return year


@router.get(
    "/{year_id}/calendar/",
    response_model=AcademicCalendarResponse,
)
async def get_academic_calendar(
    year_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    year = await _get_academic_year(session, year_id, current_user)
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


@router.get(
    "/{year_id}/calendar/entries/",
    response_model=list[CalendarEntryResponse],
)
async def list_calendar_entries(
    year_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    year = await _get_academic_year(session, year_id, current_user)
    calendar = await _get_academic_calendar(session, year)
    result = await session.scalars(
        select(CalendarEntry)
        .where(CalendarEntry.academic_calendar_id == calendar.id)
        .order_by(CalendarEntry.starts_on, CalendarEntry.title)
    )
    return list(result.all())


@router.post(
    "/{year_id}/calendar/entries/",
    response_model=CalendarEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_calendar_entry(
    year_id: uuid.UUID,
    payload: CalendarEntryRequest,
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
    _validate_calendar_entry_dates(year, payload.starts_on, payload.ends_on)
    calendar = await _get_academic_calendar(session, year)
    entry = CalendarEntry(
        academic_calendar_id=calendar.id,
        entry_type=payload.entry_type,
        title=payload.title,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


@router.get(
    "/{year_id}/calendar/entries/{entry_id}/",
    response_model=CalendarEntryResponse,
)
async def get_calendar_entry(
    year_id: uuid.UUID,
    entry_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    year = await _get_academic_year(session, year_id, current_user)
    return await _get_calendar_entry(session, year, entry_id)


@router.put(
    "/{year_id}/calendar/entries/{entry_id}/",
    response_model=CalendarEntryResponse,
)
async def replace_calendar_entry(
    year_id: uuid.UUID,
    entry_id: uuid.UUID,
    payload: CalendarEntryRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    year = await _get_academic_year(
        session,
        year_id,
        current_user,
        for_update=True,
    )
    entry = await _get_calendar_entry(session, year, entry_id)
    _require_year_writable(year)
    _validate_calendar_entry_dates(year, payload.starts_on, payload.ends_on)
    entry.entry_type = payload.entry_type
    entry.title = payload.title
    entry.starts_on = payload.starts_on
    entry.ends_on = payload.ends_on
    await session.commit()
    await session.refresh(entry)
    return entry


@router.delete(
    "/{year_id}/calendar/entries/{entry_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_calendar_entry(
    year_id: uuid.UUID,
    entry_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    year = await _get_academic_year(
        session,
        year_id,
        current_user,
        for_update=True,
    )
    entry = await _get_calendar_entry(session, year, entry_id)
    _require_year_writable(year)
    await session.delete(entry)
    await session.commit()
