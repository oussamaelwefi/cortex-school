import textwrap
import uuid
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import HTTPException, Response
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.reminders.policy import POLICY_PASSAGE_LENGTH, get_policy_file


MAX_POLICY_PDF_BYTES = 10 * 1024 * 1024
MAX_POLICY_PDF_PAGES = 100
MAX_PAGE_CONTENT_BYTES = 2 * 1024 * 1024
MAX_POLICY_TEXT_CHARS = 400_000
PDF_DOWNLOAD_RESPONSES = {200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}}


class PolicyPDFError(Exception):
    pass


async def policy_pdf_download(session: AsyncSession, organization_id: str, document_id: uuid.UUID) -> Response:
    policy = await get_policy_file(session, organization_id, document_id)
    if policy is None:
        raise HTTPException(404, "Policy PDF not found.")
    title, content = policy
    filename = quote(f"{title}.pdf", safe="")
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


def pdf_policy_title(filename: str | None) -> str:
    basename = PurePosixPath((filename or "").replace("\\", "/")).stem
    title = " ".join(basename.replace("\0", "").split())[:200].strip()
    return title or "School policy"


def pdf_policy_passages(data: bytes) -> list[tuple[str, str]]:
    if b"%PDF-" not in data[:1024]:
        raise PolicyPDFError("Choose a valid PDF file.")

    passages = []
    text_length = 0
    try:
        with PdfReader(BytesIO(data)) as reader:
            if reader.is_encrypted:
                raise PolicyPDFError("Upload an unlocked PDF.")
            if len(reader.pages) > MAX_POLICY_PDF_PAGES:
                raise PolicyPDFError("Choose a PDF with 100 pages or fewer.")

            for number, page in enumerate(reader.pages, start=1):
                contents = page.get_contents()
                if contents is None:
                    continue
                if len(contents.get_data()) > MAX_PAGE_CONTENT_BYTES:
                    raise PolicyPDFError("A page in this PDF is too complex to import.")
                text = " ".join(page.extract_text().replace("\0", "").split())
                text_length += len(text)
                if text_length > MAX_POLICY_TEXT_CHARS:
                    raise PolicyPDFError("This PDF contains too much text. Split it into smaller files.")
                passages.extend(
                    (f"Page {number}", chunk)
                    for chunk in textwrap.wrap(text, width=POLICY_PASSAGE_LENGTH)
                )
    except (PyPdfError, ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError) as exc:
        raise PolicyPDFError("This PDF could not be read. Try exporting it again.") from exc

    if not passages:
        raise PolicyPDFError("This PDF has no readable text. Run OCR on the scan or paste the policy text.")
    return passages
