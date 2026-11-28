import asyncio
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from ai.chat.evidence import ChatEvidence, lookup_fingerprint
from ai.chat.run import school_reply
from ai.chat.schemas import SchoolDataQuery
from ai.llm import LLMProviderError
from core.db import utcnow
from modules.ai.chat_access import access_state
from modules.ai.chat_data import SchoolDataAccess, selected_role
from modules.ai.models import ChatConversation, ChatMessage
from modules.ai.schemas import (
    ChatConversationDetail,
    ChatConversationList,
    ChatConversationSummary,
    ChatHistoryMessage,
    ChatResponse,
)
from modules.publications.services import _active_viewer
from modules.schools.models import School


HIDDEN_REPLY = "This saved reply is unavailable because its school data changed or can no longer be verified."


async def verified_chat_role(user, requested):
    role = selected_role(user, requested)
    await _active_viewer(user, "school_admin" if role == "admin" else role)
    return role


def _owner(user, role):
    return (
        ChatConversation.organization_id == user["organization_id"],
        ChatConversation.user_id == user["user_id"],
        ChatConversation.role == role,
    )


async def _find(session, user, role, conversation_id, request_id=None, *, lock=False):
    key = (
        ChatConversation.id == conversation_id if conversation_id is not None
        else ChatConversation.initial_request_id == request_id
    )
    statement = select(ChatConversation).where(*_owner(user, role), key)
    if lock:
        statement = statement.with_for_update()
    conversation = await session.scalar(statement)
    if conversation is None and conversation_id is not None:
        raise HTTPException(404, "Conversation not found")
    return conversation


async def list_conversations(session, user, role, *, offset, limit):
    rows = (await session.scalars(
        select(ChatConversation).where(*_owner(user, role))
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
        .offset(offset).limit(limit + 1)
    )).all()
    return ChatConversationList(
        conversations=[ChatConversationSummary.model_validate(row) for row in rows[:limit]],
        next_offset=offset + limit if len(rows) > limit else None,
    )


async def conversation_detail(session, user, role, conversation_id, *, before_turn, limit):
    conversation = await _find(session, user, role, conversation_id)
    summary = ChatConversationSummary.model_validate(conversation)
    # Fetch complete turns, then return them in chronological order.
    rows = list((await session.scalars(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.turn < (before_turn if before_turn is not None else conversation.next_turn),
        ).order_by(ChatMessage.turn.desc(), ChatMessage.sender.asc()).limit(2 * limit + 1)
    )).all())
    has_older = len(rows) > 2 * limit
    rows = list(reversed(rows[:2 * limit]))
    cursor = rows[0].turn if has_older else None
    return ChatConversationDetail(
        **summary.model_dump(),
        messages=await _visible_messages(session, user, role, rows),
        before_turn=cursor,
    )


async def delete_conversation(session, user, role, conversation_id):
    removed = await session.scalar(
        delete(ChatConversation).where(*_owner(user, role), ChatConversation.id == conversation_id)
        .returning(ChatConversation.id)
    )
    if removed is None:
        raise HTTPException(404, "Conversation not found")
    await session.commit()


async def _visible_messages(session, user, role, rows):
    messages = [ChatHistoryMessage.model_validate(row) for row in rows]
    protected = {
        row.id: (row.school_data_revision, row.lookups)
        for row in rows if row.school_data_revision is not None or row.lookups or row.sources
    }
    if not protected:
        return messages

    # Release any write lock on a retried request and start a fresh read-only lookup.
    await session.rollback()
    access = SchoolDataAccess(session, user, role, membership_verified=True)
    verified = set()
    fingerprints = {}
    try:
        async with asyncio.timeout(6):
            await access.ensure_access()
            for message_id, (revision, lookups) in protected.items():
                if revision != access.privacy_revision or not lookups:
                    continue
                for lookup in lookups:
                    parameters = {key: value for key, value in lookup.items() if key != "fingerprint"}
                    cache_key = json.dumps(parameters, sort_keys=True)
                    if cache_key not in fingerprints:
                        if "query" in parameters:
                            result = await access.query(SchoolDataQuery.model_validate(parameters["query"]))
                        else:
                            result = await access.search_policies(parameters["keywords"])
                        fingerprints[cache_key] = lookup_fingerprint(result)
                    if fingerprints[cache_key] != lookup["fingerprint"]:
                        break
                else:
                    verified.add(message_id)
            await access.ensure_access()
    except (HTTPException, SQLAlchemyError, TimeoutError):
        verified.clear()
    return [
        message.model_copy(update={"text": None, "sources": []})
        if message.id in protected and message.id not in verified else message
        for message in messages
    ]


async def _retry_response(session, user, role, conversation_id, request_id, message):
    rows = {row.sender: row for row in (await session.scalars(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id, ChatMessage.request_id == request_id,
        )
    )).all()}
    if not rows:
        return None
    if rows["user"].text != message:
        raise HTTPException(409, "This chat request was already used for a different message.")
    answer, = await _visible_messages(session, user, role, [rows["assistant"]])
    return ChatResponse(
        reply=answer.text or HIDDEN_REPLY, sources=answer.sources, conversation_id=conversation_id,
        message_id=answer.id, created_at=answer.created_at, hidden=answer.text is None,
    )


def _prompt(message, recent_questions):
    turns = [f"User: {message}"]
    size = len(turns[0])
    for question in recent_questions:
        turn = f"User: {question}"
        if size + len(turn) + 2 > 26000:
            break
        turns.append(turn)
        size += len(turn) + 2
    if len(turns) == 1:
        return message
    return "Continue this conversation. Answer the latest user message.\n\n" + "\n\n".join(reversed(turns))


async def save_chat_turn(session, user, payload, request_id):
    role = await verified_chat_role(user, payload.role)
    message = payload.message.strip()
    if not message:
        raise HTTPException(422, "Enter a message to continue.")
    if "\x00" in message:
        raise HTTPException(422, "The message contains an invalid character.")
    client_id = payload.client_message_id or uuid.uuid4()
    conversation = await _find(session, user, role, payload.conversation_id, client_id)
    expected_turn = 1
    prompt = message
    if conversation is not None:
        cached = await _retry_response(session, user, role, conversation.id, client_id, message)
        if cached is not None:
            return cached
        expected_turn = conversation.next_turn
        previous = (await session.scalars(select(ChatMessage.text).where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.sender == "user",
            ChatMessage.turn < expected_turn,
        ).order_by(ChatMessage.turn.desc()).limit(11))).all()
        prompt = _prompt(message, previous)

    # The model's school lookups use a read-only transaction. End it before saving.
    await session.rollback()
    evidence = ChatEvidence()
    result = await school_reply(
        session, user, prompt, role=role, language=payload.language,
        request_id=request_id, evidence=evidence, membership_verified=True,
    )
    await session.rollback()
    reply = result["reply"].replace("\x00", "")
    if not reply.strip():
        raise LLMProviderError("The assistant returned an empty response. Please try again.")

    now = utcnow()
    if evidence.revision is not None:
        await session.scalar(select(School.organization_id).where(
            School.organization_id == user["organization_id"],
        ).with_for_update(read=True))
        state = await access_state(session, user, role)
        if not state["effective_data_enabled"] or state["revision"] != evidence.revision:
            raise HTTPException(409, "Chat privacy settings changed. Start a new question.")

    if payload.conversation_id is None:
        await session.execute(insert(ChatConversation).values(
            organization_id=user["organization_id"], user_id=user["user_id"], role=role,
            initial_request_id=client_id, title=" ".join(message.split())[:100],
            created_at=now, updated_at=now,
        ).on_conflict_do_nothing(constraint="uq_chatconversation_initial_request"))
    conversation = await _find(session, user, role, payload.conversation_id, client_id, lock=True)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    conversation_id = conversation.id
    if conversation.next_turn != expected_turn:
        cached = await _retry_response(session, user, role, conversation_id, client_id, message)
        if cached is not None:
            return cached
        raise HTTPException(409, "This conversation changed in another session. Reopen it or try again.")

    shared = dict(conversation_id=conversation_id, turn=expected_turn, request_id=client_id, created_at=now)
    sources = result["sources"]
    answer = ChatMessage(
        id=uuid.uuid4(), sender="assistant", text=reply,
        sources=[source.model_dump(mode="json") for source in sources],
        school_data_revision=evidence.revision, lookups=evidence.lookups, **shared,
    )
    session.add_all([ChatMessage(sender="user", text=message, **shared), answer])
    conversation.next_turn += 1
    conversation.updated_at = now
    await session.commit()
    return ChatResponse(
        reply=answer.text, sources=sources, conversation_id=conversation_id,
        message_id=answer.id, created_at=answer.created_at,
    )
