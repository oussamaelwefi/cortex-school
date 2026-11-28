import uuid
from typing import Literal

from ai.chat.run import school_reply
from ai.llm import LLMNotConfiguredError, LLMProviderError
from core.auth import get_current_user
from core.db import db_session
from core.router import APIRouter
from fastapi import Depends, HTTPException, Query, Request, Response, status
from modules.ai.chat_access import access_state, save_preference
from modules.ai.chat_data import selected_role
from modules.ai.conversations import (
    conversation_detail,
    delete_conversation,
    list_conversations,
    save_chat_turn,
    verified_chat_role,
)
from modules.ai.schemas import (
    ChatConversationDetail,
    ChatConversationList,
    ChatDataAccessResponse,
    ChatDataPreferenceRequest,
    ChatRequest,
    ChatResponse,
    TeacherUpdateDraftRequest,
    TeacherUpdateDraftResult,
)
from modules.ai.services import teacher_update_draft_service
from modules.publications.services import _active_viewer
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/ai", tags=["AI"])


@router.get("/chat/access/", response_model=ChatDataAccessResponse)
async def get_chat_data_access(
    response: Response,
    role: Literal["admin", "teacher", "guardian"] | None = Query(default=None),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    workspace = selected_role(current_user, role)
    await _active_viewer(current_user, "school_admin" if workspace == "admin" else workspace)
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


@router.get("/chat/conversations/", response_model=ChatConversationList)
async def get_chat_conversations(
    response: Response,
    role: Literal["admin", "teacher", "guardian"] | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=50),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    workspace = await verified_chat_role(current_user, role)
    return await list_conversations(session, current_user, workspace, offset=offset, limit=limit)


@router.get("/chat/conversations/{conversation_id}/", response_model=ChatConversationDetail)
async def get_chat_conversation(
    conversation_id: uuid.UUID,
    response: Response,
    role: Literal["admin", "teacher", "guardian"] | None = Query(default=None),
    before_turn: int | None = Query(default=None, ge=1),
    limit: int = Query(default=12, ge=1, le=20),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    workspace = await verified_chat_role(current_user, role)
    return await conversation_detail(
        session, current_user, workspace, conversation_id, before_turn=before_turn, limit=limit,
    )


@router.delete("/chat/conversations/{conversation_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def remove_chat_conversation(
    conversation_id: uuid.UUID,
    role: Literal["admin", "teacher", "guardian"] | None = Query(default=None),
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
) -> Response:
    workspace = await verified_chat_role(current_user, role)
    await delete_conversation(session, current_user, workspace, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


@router.post("/chat/", response_model=ChatResponse, response_model_exclude_unset=True)
async def chat(
    payload: ChatRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(db_session),
    current_user: dict = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    request_id = getattr(request.state, "request_id", "unknown")
    try:
        if payload.conversation_id is not None or payload.client_message_id is not None:
            return await save_chat_turn(session, current_user, payload, request_id)
        result = await school_reply(
            session,
            current_user,
            payload.message,
            role=payload.role,
            language=payload.language,
            request_id=request_id,
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
