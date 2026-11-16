import re
import textwrap
import unicodedata
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable

from pydantic import ValidationError
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.reminders.models import ReminderDelivery, ReminderProposal, SchoolPolicyFile, SchoolPolicyPassage
from modules.reminders.schemas import GuardianPolicySource, PolicySource, SchoolPolicyFileResponse, SchoolPolicyResponse


POLICY_PASSAGE_LENGTH = 1000


def normalize_search(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(char)
    )


def policy_passages(text: str):
    heading = "General"
    paragraph: list[str] = []
    for line in [*text.splitlines(), ""]:
        line = line.strip()
        if not line or line.startswith("#"):
            if paragraph:
                for chunk in textwrap.wrap(" ".join(paragraph), width=POLICY_PASSAGE_LENGTH):
                    yield heading, chunk
                paragraph.clear()
            if line.startswith("#"):
                heading = line.lstrip("#").strip()[:150] or "General"
        else:
            paragraph.append(line)


async def add_policy(
    session: AsyncSession,
    organization_id: str,
    title: str,
    passages: Iterable[tuple[str, str]],
    *,
    pdf: bytes | None = None,
) -> SchoolPolicyResponse:
    passages = list(passages)
    document_id = uuid.uuid4()
    existing_id = None
    async with session.begin():
        if pdf is not None:
            existing_id = await _match_pdf_passages(session, organization_id, title, passages)
            if existing_id is not None:
                document_id = existing_id
            existing_file = await session.get(SchoolPolicyFile, document_id)
            if existing_file is None:
                session.add(SchoolPolicyFile(
                    id=document_id, organization_id=organization_id, title=title, content=pdf
                ))
            else:
                existing_file.content = pdf
        if existing_id is None:
            session.add_all([
                SchoolPolicyPassage(
                    organization_id=organization_id,
                    document_id=document_id,
                    title=title,
                    heading=heading,
                    excerpt=excerpt,
                    search_text=normalize_search(f"{title} {heading} {excerpt}"),
                )
                for heading, excerpt in passages
            ])
    return SchoolPolicyResponse(
        id=document_id, title=title, passage_count=len(passages), has_pdf=pdf is not None
    )


async def _lock_policy(session: AsyncSession, organization_id: str, title: str) -> None:
    # Serialize same-title uploads and deletions for the duration of their transactions.
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(
        f"school-policy-pdf:{organization_id}:{title}", 0
    ))))


async def _match_pdf_passages(
    session: AsyncSession, organization_id: str, title: str, passages: list[tuple[str, str]]
) -> uuid.UUID | None:
    await _lock_policy(session, organization_id, title)
    passage = SchoolPolicyPassage
    rows = await session.execute(
        select(passage.document_id, passage.heading, passage.excerpt)
        .where(passage.organization_id == organization_id, passage.title == title)
        .order_by(passage.document_id)
    )
    indexed = defaultdict(Counter)
    for document_id, heading, excerpt in rows:
        indexed[document_id][heading, excerpt] += 1
    expected = Counter(passages)
    return next((document_id for document_id, content in indexed.items() if content == expected), None)


async def list_policies(session: AsyncSession, organization_id: str) -> list[SchoolPolicyResponse]:
    passage = SchoolPolicyPassage
    rows = (await session.execute(
        select(passage.document_id, passage.title, func.count(passage.id), SchoolPolicyFile.id.is_not(None))
        .outerjoin(SchoolPolicyFile, SchoolPolicyFile.id == passage.document_id)
        .where(passage.organization_id == organization_id)
        .group_by(passage.document_id, passage.title, SchoolPolicyFile.id)
        .order_by(func.max(passage.created_at).desc(), passage.document_id)
    )).all()
    return [
        SchoolPolicyResponse(id=document_id, title=title, passage_count=count, has_pdf=has_pdf)
        for document_id, title, count, has_pdf in rows
    ]


async def list_policy_files(session: AsyncSession, organization_id: str) -> list[SchoolPolicyFileResponse]:
    file = SchoolPolicyFile
    rows = await session.execute(
        select(file.id, file.title).where(file.organization_id == organization_id)
        .order_by(file.title, file.id)
    )
    return [SchoolPolicyFileResponse(id=file_id, title=title) for file_id, title in rows]


async def get_policy_file(session: AsyncSession, organization_id: str, document_id: uuid.UUID):
    file = SchoolPolicyFile
    return (await session.execute(select(file.title, file.content).where(
        file.organization_id == organization_id, file.id == document_id
    ))).one_or_none()


async def get_guardian_reminder_sources(
    session: AsyncSession,
    organization_id: str | None,
    guardian_id: str | None,
    update_ids: set[uuid.UUID],
) -> dict[uuid.UUID, list[GuardianPolicySource]]:
    if not update_ids or not guardian_id or not organization_id:
        return {}

    proposals = await session.execute(
        select(ReminderProposal.update_id, ReminderProposal.sources)
        .join(ReminderDelivery, ReminderDelivery.proposal_id == ReminderProposal.id)
        .where(
            ReminderProposal.organization_id == organization_id,
            ReminderProposal.update_id.in_(update_ids),
            ReminderProposal.status == "completed",
            ReminderProposal.approved_at.is_not(None),
            ReminderDelivery.guardian_id == guardian_id,
            ReminderDelivery.status == "sent",
        )
    )
    citations: dict[uuid.UUID, dict[tuple[uuid.UUID, uuid.UUID], PolicySource]] = defaultdict(dict)
    for update_id, snapshots in proposals:
        for snapshot in snapshots:
            try:
                source = PolicySource.model_validate(snapshot)
            except ValidationError:
                continue
            citations[update_id].setdefault((source.id, source.document_id), source)
    passage_ids = {source.id for sources in citations.values() for source in sources.values()}
    if not passage_ids:
        return {}

    passage, file = SchoolPolicyPassage, SchoolPolicyFile
    rows = await session.execute(
        select(passage.id, passage.document_id, file.id.is_not(None))
        .outerjoin(
            file, and_(file.id == passage.document_id, file.organization_id == organization_id)
        )
        .where(passage.organization_id == organization_id, passage.id.in_(passage_ids))
    )
    available = {(source_id, document_id): has_pdf for source_id, document_id, has_pdf in rows}
    return {
        update_id: [
            GuardianPolicySource(**source.model_dump(), has_pdf=available[key])
            for key, source in sources.items() if key in available
        ]
        for update_id, sources in citations.items()
    }


async def delete_policy(session: AsyncSession, organization_id: str, document_id: uuid.UUID) -> bool:
    passage = SchoolPolicyPassage
    file = SchoolPolicyFile
    target = (passage.organization_id == organization_id, passage.document_id == document_id)
    async with session.begin():
        title = await session.scalar(select(passage.title).where(*target).limit(1))
        if title is None:
            return False
        await _lock_policy(session, organization_id, title)
        removed = await session.execute(delete(passage).where(*target))
        if not removed.rowcount:
            return False
        await session.execute(delete(file).where(file.organization_id == organization_id, file.id == document_id))
    return True


async def search_policy(
    session: AsyncSession, organization_id: str, keywords: list[str]
) -> list[PolicySource]:
    words = list(dict.fromkeys(
        word for keyword in keywords
        for word in re.findall(r"[^\W\d_]{3,40}", normalize_search(keyword))
    ))[:12]
    if not words:
        return []
    query = func.websearch_to_tsquery("simple", " OR ".join(f'"{word}"' for word in words))
    passage = SchoolPolicyPassage
    statement = (
        select(passage)
        .where(passage.organization_id == organization_id, passage.search_vector.bool_op("@@")(query))
        .order_by(func.ts_rank(passage.search_vector, query).desc(), passage.created_at.desc(), passage.id)
        .limit(3)
    )
    async with session.begin():
        rows = (await session.scalars(statement)).all()
    return [PolicySource.model_validate(row, from_attributes=True) for row in rows]
