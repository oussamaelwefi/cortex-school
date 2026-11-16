from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ai.chat.run import simple_reply
from ai.llm import LLMNotConfiguredError, LLMProviderError
from core.auth import get_current_user
from core.db import db_session
from core.pydantic import CustomBaseModel
from core.router import APIRouter
from modules.ai.schemas import (
    TeacherUpdateDraftRequest,
    TeacherUpdateDraftResult,
)
from modules.ai.services import teacher_update_draft_service

router = APIRouter(prefix="/ai", tags=["AI"])


class ChatRequest(CustomBaseModel):
    message: str


class ChatResponse(CustomBaseModel):
    reply: str


@router.post("/chat/", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def chat(payload: ChatRequest):
    try:
        reply = await simple_reply(payload.message)
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except LLMProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return ChatResponse(reply=reply)


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
