from typing import Annotated

from fastapi import Depends, HTTPException, status
from pydantic import StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession
from core.auth import Permission, get_current_user, require_permission
from core.config import settings
from core.db import db_session
from core.router import APIRouter
from modules.members.schemas import MemberSummaryResponse, SchoolMemberResponse
from modules.members.services import (
    MemberLookupUnavailable,
    load_member_summaries,
    list_school_members,
    enrich_member_relationships,
)

WorkOSUserId = Annotated[
    str,
    StringConstraints(pattern=r"^user_[A-Za-z0-9]+$", max_length=255),
]

router = APIRouter(
    prefix="/members",
    tags=["Members"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@router.get("/", response_model=list[SchoolMemberResponse])
async def get_school_members(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(db_session),
):
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="Authenticated user must belong to an organization")
    try:
        members = await list_school_members(organization_id)
        return await enrich_member_relationships(session, organization_id, members)
    except MemberLookupUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{user_id}/", response_model=MemberSummaryResponse)
async def get_member_summary(
    user_id: WorkOSUserId,
    current_user: dict = Depends(get_current_user),
):
    organization_id = current_user.get("organization_id")
    if not settings.WORKOS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WorkOS is not configured",
        )

    try:
        summaries = await load_member_summaries(
            organization_id,
            {user_id},
            tolerate_errors=False,
        )
    except MemberLookupUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not load school member",
        ) from exc

    user = summaries.get(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="School member not found",
        )

    return MemberSummaryResponse(id=user.id, name=user.name, email=user.email)
