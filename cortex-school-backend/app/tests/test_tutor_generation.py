"""Tutor generation regressions without a database or live provider."""
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from openai import AuthenticationError, BadRequestError

from modules.tutor import services
from modules.tutor.schemas import QuestionDraft, QuestionsDraft, StudyRequest, TutorSource


def quiz_draft(source_key=1):
    return QuestionsDraft(questions=[
        QuestionDraft(
            prompt=f"احسب {index} + 2.", options=[str(index + offset) for offset in range(1, 5)],
            correct_option=2, answer=str(index + 2), explanation="نجمع العددين.", source_keys=[source_key],
        ) for index in range(1, 4)
    ])


class Model:
    def __init__(self, draft=None, failure=None, fallback=None):
        self.chain = AsyncMock()
        self.chain.ainvoke = AsyncMock(return_value=draft, side_effect=failure)
        self.ainvoke = AsyncMock(return_value=AIMessage(content=fallback or quiz_draft().model_dump_json()))

    def model_copy(self, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        return self.chain


async def generate(monkeypatch, model):
    monkeypatch.setattr(services, "get_chat_model", lambda: model)
    source = TutorSource(id=uuid.uuid4(), page=4, excerpt="الجمع والطرح في مجموعة الأعداد العشرية")
    return await services.draft_activity(StudyRequest(action="quiz", start_page=4), "الرياضيات", [source])


@pytest.mark.asyncio
async def test_valid_quiz_needs_only_one_provider_request(monkeypatch):
    model = Model(draft=quiz_draft())
    result = await generate(monkeypatch, model)
    assert result.status == "ready"
    assert len(result.questions) == 3
    assert result.questions[0].answer == result.questions[0].options[1]
    model.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    OutputParserException("unparseable tool arguments"),
    BadRequestError("tool calling unsupported", response=httpx.Response(
        400, request=httpx.Request("POST", "https://example.invalid")), body=None),
    None,
])
async def test_unusable_structured_output_retries_with_json(monkeypatch, failure):
    model = Model(failure=failure)
    result = await generate(monkeypatch, model)
    assert result.status == "ready"
    assert len(result.questions) == 3
    model.ainvoke.assert_awaited_once()
    assert "JSON object matching this schema" in model.ainvoke.call_args.args[0][0].content


@pytest.mark.asyncio
async def test_invalid_citations_are_retried_and_still_validated(monkeypatch):
    model = Model(draft=quiz_draft(999), fallback=quiz_draft(999).model_dump_json())
    with pytest.raises(ValueError, match="Invalid textbook citations"):
        await generate(monkeypatch, model)
    model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_fenced_json_is_accepted_but_malformed_quizzes_are_rejected(monkeypatch):
    model = Model(fallback=f"```json\n{quiz_draft().model_dump_json()}\n```")
    assert (await generate(monkeypatch, model)).status == "ready"
    invalid = quiz_draft()
    invalid.questions[0].options = ["3", "3", "4", "5"]
    model = Model(fallback=invalid.model_dump_json())
    with pytest.raises(ValueError, match="Invalid quiz options"):
        await generate(monkeypatch, model)


@pytest.mark.asyncio
async def test_authentication_errors_do_not_trigger_another_provider_request(monkeypatch):
    failure = AuthenticationError("invalid key", response=httpx.Response(
        401, request=httpx.Request("POST", "https://example.invalid")), body=None)
    model = Model(failure=failure)
    with pytest.raises(AuthenticationError):
        await generate(monkeypatch, model)
    model.ainvoke.assert_not_awaited()
