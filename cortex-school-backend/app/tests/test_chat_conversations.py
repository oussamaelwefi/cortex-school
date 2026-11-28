import asyncio
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from ai.chat import run as chat
from main import app
from modules.ai import chat_data, conversations
from modules.ai.chat_access import save_preference
from modules.ai.models import ChatMessage
from modules.students.models import GuardianStudent
from test_publications import ORG, OTHER, headers
from test_school_chat import Model, call, prepare, user


CHAT = "/api/ai/chat/"
HISTORY = "/api/ai/chat/conversations/"
GUARDIAN = headers(user="GuardianA", role="guardian")


def question(message, conversation_id=None):
    return {
        "message": message, "role": "guardian", "conversation_id": conversation_id,
        "client_message_id": str(uuid.uuid4()),
    }


@pytest_asyncio.fixture
async def history_client(db_session, monkeypatch):
    data = await prepare(db_session, monkeypatch)
    monkeypatch.setattr(conversations, "_active_viewer", chat_data._active_viewer)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, data


@pytest.mark.asyncio
async def test_persists_private_turns_replays_only_user_questions_and_cascades_delete(
    history_client, db_session, monkeypatch,
):
    client, data = history_client
    model = Model([
        call("ChatAnswer", {"reply": "An earlier assistant answer"}),
        call("ChatAnswer", {"reply": "A second assistant answer"}, 2),
    ])
    monkeypatch.setattr(chat, "get_chat_model", lambda: model)
    first = question("An earlier question")
    response = await client.post(CHAT, headers=GUARDIAN, json=first)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    conversation_id = response.json()["conversation_id"]
    detail = f"{HISTORY}{conversation_id}/"
    duplicate = await client.post(CHAT, headers=GUARDIAN, json=first)
    assert duplicate.json()["message_id"] == response.json()["message_id"]
    assert len(model.messages) == 1

    resumed = await client.post(CHAT, headers=GUARDIAN, json=question("Follow-up question", conversation_id))
    assert resumed.status_code == 200, resumed.text
    assert "An earlier question" in model.messages[1][1].content
    assert model.messages[1][1].content.endswith("User: Follow-up question")
    assert "An earlier assistant answer" not in model.messages[1][1].content

    listed = await client.get(HISTORY, headers=GUARDIAN)
    assert listed.json()["conversations"][0]["title"] == "An earlier question"
    latest = (await client.get(detail, headers=GUARDIAN, params={"limit": 1})).json()
    assert [message["text"] for message in latest["messages"]] == ["Follow-up question", "A second assistant answer"]
    older = (await client.get(detail, headers=GUARDIAN, params={"before_turn": latest["before_turn"]})).json()
    assert [message["text"] for message in older["messages"]] == ["An earlier question", "An earlier assistant answer"]
    assert older["before_turn"] is None

    data["members"][OTHER].append({"id": "user_GuardianA", "roles": ["guardian"]})
    next(member for member in data["members"][ORG] if member["id"] == "user_GuardianA")["roles"].append("teacher")
    others = [
        headers(user="GuardianB", role="guardian"),
        headers(user="GuardianA", organization=OTHER, role="guardian"),
        headers(user="GuardianA", role="teacher"),
    ]
    for other in others:
        assert (await client.get(HISTORY, headers=other)).json()["conversations"] == []
        assert (await client.get(detail, headers=other)).status_code == 404
        assert (await client.delete(detail, headers=other)).status_code == 404

    assert (await client.delete(detail, headers=GUARDIAN)).status_code == 204
    assert (await client.get(detail, headers=GUARDIAN)).status_code == 404
    assert await db_session.scalar(select(func.count()).select_from(ChatMessage)) == 0


@pytest.mark.asyncio
async def test_hides_saved_school_reply_if_current_scope_or_privacy_changes(
    history_client, db_session, monkeypatch,
):
    client, data = history_client
    model = Model([
        call("QuerySchoolData", {"dataset": "students"}),
        call("ChatAnswer", {"reply": "Yasmine and Adam are linked [S1].", "source_ids": ["S1"]}, 2),
        call("ChatAnswer", {"reply": "General reply"}, 3),
    ])
    monkeypatch.setattr(chat, "get_chat_model", lambda: model)
    first = question("Who is linked to me?")
    generated = await client.post(CHAT, headers=GUARDIAN, json=first)
    assert generated.status_code == 200, generated.text
    conversation_id = generated.json()["conversation_id"]
    detail = f"{HISTORY}{conversation_id}/"
    second = await client.post(CHAT, headers=GUARDIAN, json=question("Draft a greeting", conversation_id))
    assert second.status_code == 200, second.text
    assert "Yasmine and Adam" not in model.messages[-1][1].content

    available = (await client.get(detail, headers=GUARDIAN)).json()["messages"]
    assert available[1]["text"] == "Yasmine and Adam are linked [S1]."
    assert available[1]["sources"][0]["href"] == "/family"
    removed_link = data["children"][0].id
    await db_session.execute(delete(GuardianStudent).where(
        GuardianStudent.student_id == removed_link,
        GuardianStudent.guardian_workos_user_id == "user_GuardianA",
    ))
    await db_session.commit()

    protected = (await client.get(detail, headers=GUARDIAN)).json()["messages"]
    assert protected[1]["text"] is None and protected[1]["sources"] == []
    assert protected[3]["text"] == "General reply"
    retry = (await client.post(CHAT, headers=GUARDIAN, json=first)).json()
    assert retry["hidden"] and retry["sources"] == []
    assert "Yasmine" not in retry["reply"]

    db_session.add(GuardianStudent(student_id=removed_link, guardian_workos_user_id="user_GuardianA"))
    await db_session.commit()
    await save_preference(db_session, user("guardian"), enabled=False, personal=True)
    after_opt_out = (await client.get(detail, headers=GUARDIAN)).json()["messages"]
    assert after_opt_out[1]["text"] is None
    assert after_opt_out[3]["text"] == "General reply"


@pytest.mark.asyncio
async def test_parallel_turn_cannot_overwrite_newer_context(history_client, monkeypatch):
    client, _ = history_client
    waiting = asyncio.Event()
    finish = asyncio.Event()

    async def answer(_session, _user, message, **kwargs):
        if message.endswith("Slow question"):
            waiting.set()
            await finish.wait()
        return {"reply": "An answer", "sources": []}

    monkeypatch.setattr(conversations, "school_reply", answer)
    initial = await client.post(CHAT, headers=GUARDIAN, json=question("Start"))
    assert initial.status_code == 200, initial.text
    conversation_id = initial.json()["conversation_id"]
    slow = question("Slow question", conversation_id)
    pending = asyncio.create_task(client.post(CHAT, headers=GUARDIAN, json=slow))
    try:
        await asyncio.wait_for(waiting.wait(), 5)
        quick = await client.post(CHAT, headers=GUARDIAN, json=question("Fast question", conversation_id))
        assert quick.status_code == 200, quick.text
    finally:
        finish.set()
    assert (await pending).status_code == 409
    assert (await client.post(CHAT, headers=GUARDIAN, json=slow)).status_code == 200
    saved = (await client.get(f"{HISTORY}{conversation_id}/", headers=GUARDIAN)).json()["messages"]
    assert [item["text"] for item in saved if item["sender"] == "user"] == ["Start", "Fast question", "Slow question"]


def test_model_context_bounds_saved_questions():
    recent = [f"Previous {index}: " + "x" * 11000 for index in range(11)]
    prompt = conversations._prompt("Current question", recent)
    assert len(prompt) < 27000
    assert "Previous 1:" in prompt and "Previous 2:" not in prompt
    assert prompt.endswith("User: Current question")
