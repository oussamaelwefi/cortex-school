import uuid
from urllib.parse import quote

from fastapi import Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.db import db_session
from core.router import APIRouter
from modules.student_registration.services import require_active_guardian
from modules.tutor.class_materials import (
    MAX_CLASS_PDF_BYTES, child_classroom, get_child_material, guardian_tutor_children,
    list_class_materials, publish_class_material, require_current_teacher_classes, unpublish_class_material,
)
from modules.tutor.models import TutorBook, TutorClassBook, TutorClassMaterial, TutorClassPassage
from modules.tutor.schemas import (
    PublishTutorMaterialRequest, StudyRequest, StudyResponse, TutorBookResponse, TutorChildResponse, TutorMaterialResponse,
)
from modules.tutor.services import build_activity, find_book_sources, generate_study, list_books


guardian_router = APIRouter(
    prefix="/guardian/tutor",
    tags=["Guardian Study Tutor"],
    dependencies=[Depends(require_active_guardian)],
)
teacher_router = APIRouter(prefix="/teacher/classrooms", tags=["Teacher Study Materials"])
PDF_RESPONSES = {200: {"content": {"application/pdf": {}}}}


def tutor_pdf(title: str, content: bytes) -> Response:
    filename = quote(f"{title}.pdf", safe="")
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@guardian_router.get("/books/", response_model=list[TutorBookResponse])
async def list_guardian_tutor_books(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await list_books(session, current_user["organization_id"])


@guardian_router.get("/books/{book_id}/pdf/", response_class=Response, responses=PDF_RESPONSES)
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
    return tutor_pdf(row.title, row.pdf)


@guardian_router.post("/books/{book_id}/study/", response_model=StudyResponse)
async def create_guardian_study_activity(
    book_id: uuid.UUID,
    payload: StudyRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await generate_study(
        session, current_user["organization_id"], current_user["user_id"], book_id, payload,
    )


@guardian_router.get("/children/", response_model=list[TutorChildResponse])
async def list_guardian_tutor_children(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    children, _ = await guardian_tutor_children(session, current_user)
    return children


@guardian_router.get("/children/{student_id}/materials/", response_model=list[TutorMaterialResponse])
async def list_guardian_study_materials(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    classroom_id = await child_classroom(session, current_user, student_id)
    if classroom_id is None:
        return []
    return await list_class_materials(session, current_user["organization_id"], classroom_id)


@guardian_router.get("/children/{student_id}/materials/{material_id}/pdf/", response_class=Response, responses=PDF_RESPONSES)
async def open_guardian_study_material(
    student_id: uuid.UUID, material_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    row = await get_child_material(session, current_user, student_id, material_id, TutorClassMaterial.title, TutorClassBook.pdf)
    return tutor_pdf(row.title, row.pdf)


@guardian_router.post("/children/{student_id}/materials/{material_id}/study/", response_model=StudyResponse)
async def create_guardian_class_study_activity(
    student_id: uuid.UUID, material_id: uuid.UUID, payload: StudyRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    async with session.begin():
        row = await get_child_material(
            session, current_user, student_id, material_id,
            TutorClassBook.id, TutorClassMaterial.title, TutorClassBook.page_count, TutorClassBook.indexed_page_count,
            TutorClassMaterial.grade_level,
        )
        book = TutorBookResponse(**row._mapping)
        sources = await find_book_sources(session, book, payload, TutorClassPassage)
    return await build_activity(
        current_user["organization_id"], current_user["user_id"], book.title, payload, sources,
        class_material=True, grade_level=row.grade_level,
    )


@teacher_router.get("/{classroom_id}/study-materials/", response_model=list[TutorMaterialResponse])
async def list_teacher_study_materials(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    _, organization_id = await require_current_teacher_classes(session, current_user, [classroom_id])
    return await list_class_materials(session, organization_id, classroom_id)


@teacher_router.post("/{classroom_id}/study-materials/", response_model=TutorMaterialResponse)
async def publish_teacher_study_material(
    classroom_id: uuid.UUID, file: UploadFile = File(), metadata: str = Form(max_length=2000),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    try:
        settings = PublishTutorMaterialRequest.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(422, "Enter a lesson title, a subject, and a valid grade level if provided.") from exc
    pdf = await file.read(MAX_CLASS_PDF_BYTES + 1)
    return await publish_class_material(session, current_user, classroom_id, pdf, settings)


@teacher_router.delete("/{classroom_id}/study-materials/{material_id}/", status_code=204)
async def unpublish_teacher_study_material(
    classroom_id: uuid.UUID, material_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    await unpublish_class_material(session, current_user, classroom_id, material_id)


router = APIRouter()
router.include_router(guardian_router)
router.include_router(teacher_router)
