from typing import Literal

from ai.chat.run import school_reply
from ai.chat.schemas import ChatSource
from ai.llm import LLMNotConfiguredError, LLMProviderError
from core.auth import get_current_user
from core.db import db_session
from core.pydantic import CustomBaseModel
from core.router import APIRouter
from fastapi import Depends, HTTPException, Query, Request, Response, status
from modules.ai.chat_access import access_state, save_preference
from modules.ai.chat_data import selected_role
from modules.ai.schemas import (
    ChatDataAccessResponse,
    ChatDataPreferenceRequest,
    TeacherUpdateDraftRequest,
    TeacherUpdateDraftResult,
)
from modules.ai.services import teacher_update_draft_service
from modules.publications.services import _active_viewer
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/ai", tags=["AI"])


class ChatRequest(CustomBaseModel):
    message: str = Field(min_length=1, max_length=30000)
    role: Literal["admin", "teacher", "guardian"] | None = None
    language: Literal["fr", "en"] = "fr"


class ChatResponse(CustomBaseModel):
    reply: str
    sources: list[ChatSource] = Field(default_factory=list)


@router.get("/chat/access/", response_model=ChatDataAccessResponse)
async def get_chat_data_access(
    response: Response,
    role: Literal["admin", "teacher", "guardian"] | None = Query(default=None),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    workspace = selected_role(current_user, role)
    await _active_viewer(
        current_user, "school_admin" if workspace == "admin" else workspace
    )
    return await access_state(session, current_user, workspace)


@router.put("/chat/access/", response_model=ChatDataAccessResponse)
async def set_guardian_chat_data_access(
    payload: ChatDataPreferenceRequest,
    response: Response,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    selected_role(current_user, "guardian")
    await _active_viewer(current_user, "guardian")
    return await save_preference(
        session, current_user, enabled=payload.enabled, personal=True
    )


@router.post("/chat/", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def chat(
    payload: ChatRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        result = await school_reply(
            session,
            current_user,
            payload.message,
            role=payload.role,
            language=payload.language,
            request_id=getattr(request.state, "request_id", "unknown"),
        )
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except LLMProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return ChatResponse(**result)


@router.post(
    "/teacher-update-draft/",
    response_model=TeacherUpdateDraftResult,
    status_code=status.HTTP_200_OK,
)
async def create_teacher_update_draft(
    payload: TeacherUpdateDraftRequest,
    request: Request,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    return await teacher_update_draft_service.generate(
        session=session,
        payload=payload,
        current_user=current_user,
        request_id=getattr(request.state, "request_id", "unknown"),
    )
