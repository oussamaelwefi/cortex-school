"""Import a PDF and reviewed per-page OCR files into one school's tutor library."""

import argparse
import asyncio
import hashlib
import re
import textwrap
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import SessionLocal, utcnow
from modules.schools.models import School
from modules.tutor.models import TutorBook, TutorPassage
from modules.tutor.services import normalize_book_search


MAX_BOOK_BYTES = 30 * 1024 * 1024
MAX_BOOK_PAGES = 400
MAX_PAGE_TEXT = 20_000
ARABIC_LETTER = re.compile(r"[\u0621-\u064a]")


def clean_ocr(value: str) -> str:
    value = re.sub(r"(?m)^\s*</?file\b[^>]*>\s*$", "", value)
    value = re.sub(r"!\[[^\]]*\]\([^\n)]*\)", "", value)
    return value.replace("\0", "").strip()


def page_chunks(value: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", value)
    chunks = []
    current = ""
    for paragraph in paragraphs:
        for block in textwrap.wrap(paragraph.strip(), width=900, replace_whitespace=False):
            if current and len(current) + len(block) + 2 > 900:
                chunks.append(current)
                current = ""
            current = f"{current}\n\n{block}" if current else block
    if current:
        chunks.append(current)
    return chunks


async def store_book(
    session: AsyncSession, organization_id: str, title: str, pdf: bytes, pages: dict[int, str],
):
    if not pdf.startswith(b"%PDF-") or len(pdf) > MAX_BOOK_BYTES:
        raise ValueError("Choose a PDF of 30 MB or less.")
    with PdfReader(BytesIO(pdf)) as reader:
        if reader.is_encrypted:
            raise ValueError("Choose an unlocked PDF.")
        total = len(reader.pages)
        if not 0 < total <= MAX_BOOK_PAGES:
            raise ValueError("Choose a PDF with up to 400 pages.")
    title = " ".join(title.split())
    if not 0 < len(title) <= 200:
        raise ValueError("A book title of up to 200 characters is required.")
    cleaned = {page: clean_ocr(value) for page, value in pages.items()}
    if any(not 1 <= page <= total or len(value) > MAX_PAGE_TEXT for page, value in cleaned.items()):
        raise ValueError("OCR files must match the original book page numbers and be 20,000 characters or fewer.")
    chunks = {page: page_chunks(value) for page, value in cleaned.items() if value}
    if not chunks:
        raise ValueError("The book requires readable page text.")

    async with session.begin():
        if await session.get(School, organization_id) is None:
            raise ValueError("School not found.")
        book = insert(TutorBook).values(
            organization_id=organization_id, title=title, sha256=hashlib.sha256(pdf).hexdigest(),
            pdf=pdf, page_count=total, indexed_page_count=len(chunks),
        )
        book_id = await session.scalar(
            book.on_conflict_do_update(
                constraint="uq_tutorbook_school_hash",
                set_={"title": title, "indexed_page_count": len(chunks), "updated_at": utcnow()},
            ).returning(TutorBook.id)
        )
        await session.execute(delete(TutorPassage).where(TutorPassage.book_id == book_id))
        session.add_all([
            TutorPassage(
                book_id=book_id, page=page, position=index, excerpt=excerpt,
                search_text=normalize_book_search(excerpt),
            )
            for page, snippets in sorted(chunks.items()) for index, excerpt in enumerate(snippets)
        ])
    return book_id, total, len(chunks)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--ocr-dir", type=Path, required=True, help="UTF-8 files named by PDF page, e.g. 042.txt")
    parser.add_argument("--first-page", type=int, default=1)
    parser.add_argument("--last-page", type=int, default=MAX_BOOK_PAGES)
    parser.add_argument("--min-arabic-letters", type=int, default=0)
    args = parser.parse_args()
    pages = {}
    for path in sorted(args.ocr_dir.glob("*.txt")):
        if not path.stem.isdecimal() or not args.first_page <= int(path.stem) <= args.last_page:
            continue
        value = clean_ocr(path.read_text(encoding="utf-8-sig"))
        if len(ARABIC_LETTER.findall(value)) >= args.min_arabic_letters:
            pages[int(path.stem)] = value
    async with SessionLocal() as session:
        book_id, total, indexed = await store_book(
            session, args.organization, args.title, args.pdf.read_bytes(), pages,
        )
    print(f"Imported {book_id}: {indexed} of {total} PDF pages indexed.")


if __name__ == "__main__":
    asyncio.run(main())
