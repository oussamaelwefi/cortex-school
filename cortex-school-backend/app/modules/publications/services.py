import asyncio
import hashlib
import json
import uuid
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import String, any_, cast, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from workos import AsyncWorkOSClient

from core.config import settings
from core.db import utcnow
from modules.academic_years.models import AcademicYear, AcademicYearStatus
from modules.attendance.services import _current_school_date
from modules.classrooms.models import Classroom, ClassEnrollment, TeacherAssignment
from modules.enrollments.models import Enrollment
from modules.members.services import MemberLookupUnavailable, list_school_members
from modules.publications.models import PublicationRecipient, SchoolPublication
from modules.publications.schemas import (
    PublicationAudienceOptions,
    PublicationCreateRequest,
    PublicationDetailResponse,
    PublicationInboxItem,
    PublicationInboxResponse,
    PublicationListResponse,
    PublicationOption,
    PublicationPreviewRecipient,
    PublicationPreviewResponse,
    PublicationReceipt,
    PublicationResponse,
    PublicationTarget,
)
from modules.schools.models import School
from modules.students.models import GuardianStudent, Student


def _scope(current_user: dict) -> tuple[str, str]:
    user_id, organization_id = (
        current_user.get("user_id"),
        current_user.get("organization_id"),
    )
    if not user_id or not organization_id:
        raise HTTPException(403, "A school session is required")
    return user_id, organization_id


async def _school(session, organization_id):
    school = await session.get(School, organization_id)
    if school is None:
        raise HTTPException(404, "School not found")
    return school


async def _members(organization_id):
    try:
        async with asyncio.timeout(15):
            return await list_school_members(organization_id)
    except (MemberLookupUnavailable, TimeoutError) as exc:
        raise HTTPException(
            503, "School recipients could not be verified. Please try again."
        ) from exc


async def _active_viewer(current_user, role):
    user_id, organization_id = _scope(current_user)
    if not settings.WORKOS_API_KEY:
        raise HTTPException(
            503, "School membership could not be verified. Please try again."
        )
    try:
        async with asyncio.timeout(8):
            async with AsyncWorkOSClient(api_key=settings.WORKOS_API_KEY) as client:
                page = (
                    await client.organization_membership.list_organization_memberships(
                        organization_id=organization_id,
                        user_id=user_id,
                        statuses=["active"],
                        limit=100,
                        request_options={
                            "base_url": settings.WORKOS_API_BASE_URL,
                            "timeout": 5,
                            "max_retries": 0,
                        },
                    )
                )
    except Exception as exc:
        raise HTTPException(
            503, "School membership could not be verified. Please try again."
        ) from exc
    if not any(
        membership.organization_id == organization_id
        and membership.user_id == user_id
        and membership.status == "active"
        and any(value.slug == role for value in membership.roles)
        for membership in page.data
    ):
        raise HTTPException(403, "Active school membership is required for this inbox")
    return user_id, organization_id


def _current_classes(organization_id, today):
    return (
        select(Classroom)
        .join(AcademicYear)
        .where(
            AcademicYear.organization_id == organization_id,
            AcademicYear.status == AcademicYearStatus.ACTIVE,
            AcademicYear.starts_on <= today,
            AcademicYear.ends_on >= today,
        )
    )


async def audience_options(session: AsyncSession, current_user: dict):
    _, organization_id = _scope(current_user)
    school = await _school(session, organization_id)
    members = await _members(organization_id)
    classrooms = (
        await session.scalars(
            _current_classes(organization_id, _current_school_date(school)).order_by(
                Classroom.name
            )
        )
    ).all()
    students = (
        await session.scalars(
            select(Student)
            .where(Student.organization_id == organization_id)
            .order_by(Student.first_name, Student.last_name, Student.id)
        )
    ).all()
    return PublicationAudienceOptions(
        classrooms=[
            PublicationOption(id=str(item.id), name=item.name) for item in classrooms
        ],
        students=[
            PublicationOption(
                id=str(item.id), name=f"{item.first_name} {item.last_name}"
            )
            for item in students
        ],
        guardians=[
            PublicationOption(id=item["id"], name=item["name"])
            for item in members
            if "guardian" in item["roles"]
        ],
        teachers=[
            PublicationOption(id=item["id"], name=item["name"])
            for item in members
            if "teacher" in item["roles"]
        ],
    )


async def _resolve_audience(
    session: AsyncSession, target: PublicationTarget, organization_id: str
):
    school = await _school(session, organization_id)
    today = _current_school_date(school)
    members = {item["id"]: item for item in await _members(organization_id)}
    recipients = {}
    missing = []

    def add(user_id, role, student_id=None):
        member = members.get(user_id)
        if member is None or role not in member["roles"]:
            return False
        item = recipients.setdefault(
            user_id,
            {
                "id": user_id,
                "name": member["name"],
                "roles": set(),
                "student_ids": set(),
            },
        )
        item["roles"].add(role)
        if student_id is not None:
            item["student_ids"].add(str(student_id))
        return True

    if target.kind in {"guardians", "teachers"}:
        role = "guardian" if target.kind == "guardians" else "teacher"
        if not all(add(user_id, role) for user_id in target.ids):
            raise HTTPException(
                422,
                "Some selected members are unavailable in this school. Review the recipients.",
            )
    else:
        identifiers = [uuid.UUID(value) for value in target.ids]
        if target.kind == "classrooms":
            classrooms = (
                await session.scalars(
                    _current_classes(organization_id, today).where(
                        Classroom.id.in_(identifiers)
                    )
                )
            ).all()
            if len(classrooms) != len(identifiers):
                raise HTTPException(
                    422, "Some selected classes are no longer active in this school."
                )
            students = (
                await session.scalars(
                    select(Student)
                    .join(Enrollment, Enrollment.student_id == Student.id)
                    .join(
                        ClassEnrollment, ClassEnrollment.enrollment_id == Enrollment.id
                    )
                    .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
                    .where(
                        Classroom.id.in_(identifiers),
                        Enrollment.academic_year_id == Classroom.academic_year_id,
                        Student.organization_id == organization_id,
                        ClassEnrollment.effective_from <= today,
                        or_(
                            ClassEnrollment.effective_until.is_(None),
                            ClassEnrollment.effective_until > today,
                        ),
                    )
                    .distinct()
                )
            ).all()
            teachers = (
                await session.scalars(
                    select(TeacherAssignment.teacher_workos_user_id).where(
                        TeacherAssignment.classroom_id.in_(identifiers),
                        TeacherAssignment.effective_from <= today,
                        or_(
                            TeacherAssignment.effective_until.is_(None),
                            TeacherAssignment.effective_until > today,
                        ),
                    )
                )
            ).all()
            for teacher_id in teachers:
                add(teacher_id, "teacher")
        else:
            students = (
                await session.scalars(
                    select(Student).where(
                        Student.id.in_(identifiers),
                        Student.organization_id == organization_id,
                    )
                )
            ).all()
            if len(students) != len(identifiers):
                raise HTTPException(
                    422, "Some selected students are unavailable in this school."
                )
        links = (
            (
                await session.execute(
                    select(
                        GuardianStudent.student_id,
                        GuardianStudent.guardian_workos_user_id,
                    ).where(
                        GuardianStudent.student_id.in_(
                            [student.id for student in students]
                        ),
                    )
                )
            ).all()
            if students
            else []
        )
        reached_students = set()
        for student_id, guardian_id in links:
            if add(guardian_id, "guardian", student_id):
                reached_students.add(student_id)
        missing = sorted(
            f"{student.first_name} {student.last_name}"
            for student in students
            if student.id not in reached_students
        )
    resolved = [
        dict(item, roles=sorted(item["roles"]), student_ids=sorted(item["student_ids"]))
        for _, item in sorted(recipients.items())
    ]
    if not resolved:
        raise HTTPException(
            422,
            "No active recipients were found. Check family links and class assignments.",
        )
    fingerprint = _hash(
        {
            "organization": organization_id,
            "target": {"kind": target.kind, "ids": sorted(target.ids)},
            "recipients": [
                {key: item[key] for key in ("id", "roles", "student_ids")}
                for item in resolved
            ],
        }
    )
    return resolved, missing, fingerprint


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def preview_audience(session, target, current_user):
    _, organization_id = _scope(current_user)
    recipients, missing, fingerprint = await _resolve_audience(
        session, target, organization_id
    )
    return PublicationPreviewResponse(
        audience_hash=fingerprint,
        recipient_count=len(recipients),
        guardian_count=sum("guardian" in item["roles"] for item in recipients),
        teacher_count=sum("teacher" in item["roles"] for item in recipients),
        recipients=[
            PublicationPreviewRecipient(
                **{key: item[key] for key in ("id", "name", "roles")}
            )
            for item in recipients
        ],
        students_without_guardians=missing,
    )


def _summary(publication, read_count=0):
    return PublicationResponse(
        id=publication.id,
        title=publication.title,
        body=publication.body,
        target_kind=publication.target_kind,
        target_ids=publication.target_ids,
        recipient_count=publication.recipient_count,
        read_count=read_count,
        created_at=publication.created_at,
    )


async def create_publication(
    session: AsyncSession, payload: PublicationCreateRequest, current_user: dict
):
    author_id, organization_id = _scope(current_user)
    content_hash = _hash(
        {
            **payload.model_dump(mode="json", exclude={"confirmed", "idempotency_key"}),
            "target": {"kind": payload.target.kind, "ids": sorted(payload.target.ids)},
        }
    )
    key_query = select(SchoolPublication).where(
        SchoolPublication.organization_id == organization_id,
        SchoolPublication.author_user_id == author_id,
        SchoolPublication.idempotency_key == payload.idempotency_key,
    )
    async with session.begin():
        existing = await session.scalar(key_query)
        if existing:
            if existing.payload_hash != content_hash:
                raise HTTPException(
                    409,
                    "This publication attempt was already used for different content. Start a new publication.",
                )
            read_count = await session.scalar(
                select(func.count())
                .select_from(PublicationRecipient)
                .where(
                    PublicationRecipient.publication_id == existing.id,
                    PublicationRecipient.read_at.is_not(None),
                )
            )
            return _summary(existing, read_count)
        recipients, _, fingerprint = await _resolve_audience(
            session, payload.target, organization_id
        )
        if fingerprint != payload.audience_hash:
            raise HTTPException(
                409, "The recipients have changed. Review them again before publishing."
            )
        now, publication_id = utcnow(), uuid.uuid4()
        inserted = await session.scalar(
            insert(SchoolPublication)
            .values(
                id=publication_id,
                organization_id=organization_id,
                author_user_id=author_id,
                idempotency_key=payload.idempotency_key,
                payload_hash=content_hash,
                title=payload.title,
                body=payload.body,
                target_kind=payload.target.kind,
                target_ids=payload.target.ids,
                recipient_count=len(recipients),
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_publication_author_attempt")
            .returning(SchoolPublication.id)
        )
        if inserted is None:
            existing = await session.scalar(key_query)
            if existing.payload_hash != content_hash:
                raise HTTPException(
                    409,
                    "This publication attempt was already used for different content. Start a new publication.",
                )
            return _summary(existing)
        session.add_all(
            [
                PublicationRecipient(
                    publication_id=publication_id,
                    user_id=item["id"],
                    name=item["name"],
                    roles=item["roles"],
                    student_ids=item["student_ids"],
                )
                for item in recipients
            ]
        )
        await session.flush()
        return _summary(await session.get(SchoolPublication, publication_id))


async def list_publications(session, current_user, search, limit, offset):
    _, organization_id = _scope(current_user)
    conditions = [SchoolPublication.organization_id == organization_id]
    if search.strip():
        conditions.append(
            SchoolPublication.title.icontains(search.strip(), autoescape=True)
        )
    total = await session.scalar(
        select(func.count()).select_from(SchoolPublication).where(*conditions)
    )
    read_count = (
        select(func.count())
        .select_from(PublicationRecipient)
        .where(
            PublicationRecipient.publication_id == SchoolPublication.id,
            PublicationRecipient.read_at.is_not(None),
        )
        .correlate(SchoolPublication)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(SchoolPublication, read_count)
            .where(*conditions)
            .order_by(SchoolPublication.created_at.desc(), SchoolPublication.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return PublicationListResponse(
        items=[_summary(publication, count) for publication, count in rows],
        total_count=total,
    )


async def publication_detail(session, publication_id, current_user):
    _, organization_id = _scope(current_user)
    publication = await session.scalar(
        select(SchoolPublication).where(
            SchoolPublication.id == publication_id,
            SchoolPublication.organization_id == organization_id,
        )
    )
    if publication is None:
        raise HTTPException(404, "Publication not found")
    recipients = (
        await session.scalars(
            select(PublicationRecipient)
            .where(PublicationRecipient.publication_id == publication_id)
            .order_by(PublicationRecipient.name, PublicationRecipient.user_id)
        )
    ).all()
    return PublicationDetailResponse(
        **_summary(
            publication, sum(item.read_at is not None for item in recipients)
        ).model_dump(),
        recipients=[
            PublicationReceipt(
                id=item.user_id, name=item.name, roles=item.roles, read_at=item.read_at
            )
            for item in recipients
        ],
    )


def _inbox_conditions(user_id, organization_id, role):
    conditions = [
        SchoolPublication.organization_id == organization_id,
        PublicationRecipient.user_id == user_id,
        PublicationRecipient.roles.contains([role]),
    ]
    if role == "guardian":
        still_linked = exists(
            select(GuardianStudent.id)
            .join(Student, Student.id == GuardianStudent.student_id)
            .where(
                GuardianStudent.guardian_workos_user_id == user_id,
                Student.organization_id == organization_id,
                cast(GuardianStudent.student_id, String)
                == any_(PublicationRecipient.student_ids),
            )
        )
        conditions.append(or_(PublicationRecipient.student_ids == [], still_linked))
    return conditions


def _inbox_item(publication, recipient):
    return PublicationInboxItem(
        id=publication.id,
        title=publication.title,
        body=publication.body,
        created_at=publication.created_at,
        read_at=recipient.read_at,
    )


async def list_inbox(
    session,
    current_user,
    role: Literal["teacher", "guardian"],
    search,
    unread_only,
    limit,
    offset,
):
    user_id, organization_id = await _active_viewer(current_user, role)
    conditions = _inbox_conditions(user_id, organization_id, role)
    if search.strip():
        conditions.append(
            SchoolPublication.title.icontains(search.strip(), autoescape=True)
        )
    base = select(SchoolPublication, PublicationRecipient).join(
        PublicationRecipient,
        PublicationRecipient.publication_id == SchoolPublication.id,
    )
    unread = await session.scalar(
        select(func.count()).select_from(
            base.where(*conditions, PublicationRecipient.read_at.is_(None)).subquery()
        )
    )
    if unread_only:
        conditions.append(PublicationRecipient.read_at.is_(None))
    total = await session.scalar(
        select(func.count()).select_from(base.where(*conditions).subquery())
    )
    rows = (
        await session.execute(
            base.where(*conditions)
            .order_by(SchoolPublication.created_at.desc(), SchoolPublication.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return PublicationInboxResponse(
        items=[_inbox_item(publication, recipient) for publication, recipient in rows],
        total_count=total,
        unread_count=unread,
    )


async def mark_read(session, publication_id, current_user, role):
    user_id, organization_id = await _active_viewer(current_user, role)
    async with session.begin():
        row = (
            await session.execute(
                select(SchoolPublication, PublicationRecipient)
                .join(
                    PublicationRecipient,
                    PublicationRecipient.publication_id == SchoolPublication.id,
                )
                .where(
                    SchoolPublication.id == publication_id,
                    *_inbox_conditions(user_id, organization_id, role),
                )
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(404, "Publication not found")
        publication, recipient = row
        await session.execute(
            update(PublicationRecipient)
            .where(PublicationRecipient.id == recipient.id)
            .values(read_at=func.coalesce(PublicationRecipient.read_at, utcnow()))
        )
        await session.refresh(recipient)
        return _inbox_item(publication, recipient)
