import uuid
from typing import Literal

from fastapi import Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.publications import services
from modules.publications.schemas import (
    PublicationAudienceOptions,
    PublicationCreateRequest,
    PublicationDetailResponse,
    PublicationInboxItem,
    PublicationInboxResponse,
    PublicationListResponse,
    PublicationPreviewRequest,
    PublicationPreviewResponse,
    PublicationResponse,
)

admin_router = APIRouter(
    prefix="/publications",
    tags=["School Publications"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)
inbox_router = APIRouter(prefix="/publications", tags=["School Publication Inbox"])


@admin_router.get("/audiences/", response_model=PublicationAudienceOptions)
async def get_publication_audiences(
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await services.audience_options(session, current_user)


@admin_router.post("/preview/", response_model=PublicationPreviewResponse)
async def preview_publication(
    payload: PublicationPreviewRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await services.preview_audience(session, payload.target, current_user)


@admin_router.post(
    "/", response_model=PublicationResponse, status_code=status.HTTP_201_CREATED
)
async def publish_school_publication(
    payload: PublicationCreateRequest,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await services.create_publication(session, payload, current_user)


@admin_router.get("/", response_model=PublicationListResponse)
async def list_school_publications(
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await services.list_publications(
        session, current_user, search, limit, offset
    )


@inbox_router.get("/inbox/", response_model=PublicationInboxResponse)
async def list_received_publications(
    role: Literal["teacher", "guardian"],
    search: str = Query(default="", max_length=120),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await services.list_inbox(
        session, current_user, role, search, unread_only, limit, offset
    )


@inbox_router.post("/inbox/{publication_id}/read/", response_model=PublicationInboxItem)
async def read_school_publication(
    publication_id: uuid.UUID,
    role: Literal["teacher", "guardian"],
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await services.mark_read(session, publication_id, current_user, role)


@admin_router.get("/{publication_id}/", response_model=PublicationDetailResponse)
async def get_school_publication(
    publication_id: uuid.UUID,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await services.publication_detail(session, publication_id, current_user)


router = APIRouter()
router.include_router(inbox_router)
router.include_router(admin_router)
