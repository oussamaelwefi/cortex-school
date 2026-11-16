import logging
from datetime import date
from time import perf_counter
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import Permission, get_current_user, require_permission
from core.db import db_session
from core.router import APIRouter
from modules.needs_review.schemas import (
    NeedsReviewCategory,
    NeedsReviewResponse,
    NeedsReviewSeverity,
)
from modules.needs_review.services import build_needs_review


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/needs-review",
    tags=["Admin Needs Review"],
    dependencies=[Depends(require_permission(Permission.SCHOOL_MANAGE))],
)


@router.get("/", response_model=NeedsReviewResponse)
async def get_needs_review(
    category: Annotated[
        list[NeedsReviewCategory] | None,
        Query(),
    ] = None,
    severity: Annotated[
        list[NeedsReviewSeverity] | None,
        Query(),
    ] = None,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    if not current_user.get("organization_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to an organization",
        )
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be on or before date_to",
        )
    started_at = perf_counter()
    try:
        response = await build_needs_review(
            session,
            organization_id=current_user.get("organization_id"),
            categories=set(category) if category else None,
            severities=set(severity) if severity else None,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="School not found",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="School attendance settings are invalid",
        ) from exc

    logger.info(
        "needs_review_queue_built",
        extra={
            "latency_ms": round((perf_counter() - started_at) * 1000, 2),
            "total_count": response.total_count,
            "category_counts": {
                category.value: count
                for category, count in response.category_counts.items()
            },
        },
    )
    return response
