import hashlib
import uuid
from io import BytesIO

from fastapi import HTTPException
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from modules.attendance.services import current_school_date
from modules.classrooms.services import _get_teacher_classroom_access
from modules.guardian_family.services import _active_year, _linked_students, _placements
from modules.teachers.services import _require_teacher_access
from modules.tutor.import_book import clean_ocr, page_chunks
from modules.tutor.models import TutorClassBook, TutorClassMaterial, TutorClassPassage
from modules.tutor.schemas import PublishTutorMaterialRequest, TutorChildResponse, TutorMaterialResponse
from modules.tutor.services import normalize_book_search


MAX_CLASS_PDF_BYTES = 10 * 1024 * 1024
MAX_CLASS_PDF_PAGES = 100
MAX_PAGE_CONTENT_BYTES = 2 * 1024 * 1024
MAX_CLASS_PDF_TEXT = 400_000
MATERIAL_COLUMNS = (
    TutorClassMaterial.id,
    TutorClassMaterial.title,
    TutorClassMaterial.subject,
    TutorClassMaterial.grade_level,
    TutorClassBook.page_count,
    TutorClassBook.indexed_page_count,
)


def extract_class_pdf(pdf: bytes) -> tuple[int, dict[int, list[str]]]:
    chunks = {}
    text_length = 0
    try:
        with PdfReader(BytesIO(pdf)) as reader:
            if reader.is_encrypted:
                raise HTTPException(422, "Choose an unlocked PDF.")
            total = len(reader.pages)
            if not 0 < total <= MAX_CLASS_PDF_PAGES:
                raise HTTPException(422, "Choose a PDF with 100 pages or fewer.")
            for number, page in enumerate(reader.pages, start=1):
                contents = page.get_contents()
                if contents is None:
                    continue
                if len(contents.get_data()) > MAX_PAGE_CONTENT_BYTES:
                    raise HTTPException(422, "A page in this PDF is too complex to import.")
                text = clean_ocr(page.extract_text())
                text_length += len(text)
                if text_length > MAX_CLASS_PDF_TEXT:
                    raise HTTPException(422, "This PDF contains too much text. Split it into smaller files.")
                if text:
                    chunks[number] = page_chunks(text)
    except (PyPdfError, ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError) as exc:
        raise HTTPException(422, "This PDF could not be read. Try exporting it again.") from exc
    if not chunks:
        raise HTTPException(422, "This PDF has no selectable text. Run OCR on the scan and try again.")
    return total, chunks


async def require_current_teacher_classes(
    session: AsyncSession, current_user: dict, classroom_ids: list[uuid.UUID],
) -> tuple[str, str]:
    teacher_id, organization_id = _require_teacher_access(current_user)
    today = await current_school_date(session, organization_id)
    for classroom_id in classroom_ids:
        _, year, assignment = await _get_teacher_classroom_access(session, classroom_id, current_user, today)
        if max(year.starts_on, assignment.effective_from) > today:
            raise HTTPException(404, "Classroom not found")
    return teacher_id, organization_id


def material_query(*columns):
    return select(*columns).select_from(TutorClassMaterial).join(TutorClassBook, TutorClassBook.id == TutorClassMaterial.book_id)


async def list_class_materials(
    session: AsyncSession, organization_id: str, classroom_id: uuid.UUID,
) -> list[TutorMaterialResponse]:
    rows = await session.execute(
        material_query(*MATERIAL_COLUMNS)
        .where(TutorClassMaterial.classroom_id == classroom_id, TutorClassBook.organization_id == organization_id)
        .order_by(TutorClassMaterial.created_at.desc(), TutorClassMaterial.id),
    )
    return [TutorMaterialResponse(**row._mapping) for row in rows]


async def publish_class_material(
    session: AsyncSession, current_user: dict, classroom_id: uuid.UUID, pdf: bytes,
    metadata: PublishTutorMaterialRequest,
) -> TutorMaterialResponse:
    classroom_ids = list(dict.fromkeys([classroom_id, *metadata.additional_classroom_ids]))
    async with session.begin():
        teacher_id, organization_id = await require_current_teacher_classes(session, current_user, classroom_ids)
        if len(pdf) > MAX_CLASS_PDF_BYTES:
            raise HTTPException(413, "Choose a PDF of 10 MB or less.")
        if b"%PDF-" not in pdf[:1024]:
            raise HTTPException(422, "Choose a valid PDF file.")
        digest = hashlib.sha256(pdf).hexdigest()
        existing_book = select(TutorClassBook.id).where(
            TutorClassBook.organization_id == organization_id, TutorClassBook.sha256 == digest,
        )
        book_id = await session.scalar(existing_book)
        if book_id is None:
            total, chunks = await run_in_threadpool(extract_class_pdf, pdf)
            book_id = await session.scalar(
                insert(TutorClassBook).values(
                    organization_id=organization_id, sha256=digest, pdf=pdf,
                    page_count=total, indexed_page_count=len(chunks),
                ).on_conflict_do_nothing(constraint="uq_tutor_class_book_school_hash").returning(TutorClassBook.id),
            )
            if book_id is None:
                book_id = (await session.execute(existing_book)).scalar_one()
            else:
                session.add_all([
                    TutorClassPassage(book_id=book_id, page=page, position=index, excerpt=excerpt,
                                      search_text=normalize_book_search(excerpt))
                    for page, passages in chunks.items() for index, excerpt in enumerate(passages)
                ])
        await session.execute(insert(TutorClassMaterial).values([
            {"classroom_id": target, "book_id": book_id, "title": metadata.title, "subject": metadata.subject,
             "grade_level": metadata.grade_level, "published_by": teacher_id}
            for target in sorted(classroom_ids)
        ]).on_conflict_do_nothing(constraint="uq_tutor_class_material_class_book"))
        row = (await session.execute(
            material_query(*MATERIAL_COLUMNS)
            .where(TutorClassMaterial.classroom_id == classroom_id, TutorClassMaterial.book_id == book_id),
        )).one()
        return TutorMaterialResponse(**row._mapping)


async def unpublish_class_material(
    session: AsyncSession, current_user: dict, classroom_id: uuid.UUID, material_id: uuid.UUID,
) -> None:
    async with session.begin():
        await require_current_teacher_classes(session, current_user, [classroom_id])
        removed = await session.scalar(
            delete(TutorClassMaterial)
            .where(TutorClassMaterial.id == material_id, TutorClassMaterial.classroom_id == classroom_id)
            .returning(TutorClassMaterial.id),
        )
        if removed is None:
            raise HTTPException(404, "Study material not found.")


async def guardian_tutor_children(session: AsyncSession, current_user: dict):
    organization_id = current_user["organization_id"]
    students = await _linked_students(session, current_user["user_id"], organization_id)
    if not students:
        return [], {}
    today = await current_school_date(session, organization_id)
    year = await _active_year(session, organization_id, today)
    placements, _ = await _placements(session, [student.id for student in students], organization_id, year, today)
    return [
        TutorChildResponse(
            id=student.id, first_name=student.first_name, last_name=student.last_name,
            classroom_name=placements.get(student.id, {}).get("classroom_name"),
        )
        for student in students
    ], placements


async def child_classroom(session: AsyncSession, current_user: dict, student_id: uuid.UUID) -> uuid.UUID | None:
    children, placements = await guardian_tutor_children(session, current_user)
    if not any(child.id == student_id for child in children):
        raise HTTPException(404, "Child not found.")
    return placements.get(student_id, {}).get("classroom_id")


async def get_child_material(session: AsyncSession, current_user: dict, student_id: uuid.UUID, material_id: uuid.UUID, *columns):
    classroom_id = await child_classroom(session, current_user, student_id)
    row = (await session.execute(
        material_query(*columns).where(
            TutorClassMaterial.id == material_id,
            TutorClassMaterial.classroom_id == classroom_id,
            TutorClassBook.organization_id == current_user["organization_id"],
        ),
    )).one_or_none()
    if row is None:
        raise HTTPException(404, "Study material not found.")
    return row
