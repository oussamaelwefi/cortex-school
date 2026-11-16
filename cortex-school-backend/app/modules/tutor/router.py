import uuid
from urllib.parse import quote

from fastapi import Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.db import db_session
from core.router import APIRouter
from modules.student_registration.services import require_active_guardian
from modules.tutor.models import TutorBook
from modules.tutor.schemas import StudyRequest, StudyResponse, TutorBookResponse
from modules.tutor.services import generate_study, list_books


router = APIRouter(
    prefix="/guardian/tutor",
    tags=["Guardian Study Tutor"],
    dependencies=[Depends(require_active_guardian)],
)


@router.get("/books/", response_model=list[TutorBookResponse])
async def list_guardian_tutor_books(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await list_books(session, current_user["organization_id"])


@router.get("/books/{book_id}/pdf/", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}})
async def open_guardian_tutor_book(
    book_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    row = (await session.execute(select(TutorBook.title, TutorBook.pdf).where(
        TutorBook.id == book_id, TutorBook.organization_id == current_user["organization_id"],
    ))).one_or_none()
    if row is None:
        raise HTTPException(404, "Study book not found.")
    filename = quote(f"{row.title}.pdf", safe="")
    return Response(row.pdf, media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/books/{book_id}/study/", response_model=StudyResponse)
async def create_guardian_study_activity(
    book_id: uuid.UUID,
    payload: StudyRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await generate_study(
        session, current_user["organization_id"], current_user["user_id"], book_id, payload,
    )
