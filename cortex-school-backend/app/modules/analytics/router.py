from typing import Literal

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.analytics.schemas import SchoolAnalyticsResponse
from modules.analytics.services import build_school_analytics


router = APIRouter(
    prefix="/analytics",
    tags=["School Analytics"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@router.get("/", response_model=SchoolAnalyticsResponse)
async def get_school_analytics(
    days: Literal["7", "30", "90"] = Query(default="30"),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(400, "Authenticated user must belong to an organization")
    return await build_school_analytics(session, organization_id, days=int(days))
