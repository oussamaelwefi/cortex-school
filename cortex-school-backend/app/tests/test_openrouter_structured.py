"""Check the serialized provider request without using a real key or network."""

import json

import httpx
import pytest
from pydantic import ValidationError

from ai import openrouter
from core.config import settings
from modules.ai.schemas import (
    GuardianWeeklyExplanationModelResult,
    TeacherUpdateDraftResult,
)


def _assert_strict_schema(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
            assert set(node.get("required", [])) == set(node.get("properties", {}))
        assert "default" not in node
        for value in node.values():
            _assert_strict_schema(value)
    elif isinstance(node, list):
        for value in node:
            _assert_strict_schema(value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory,result_type,output",
    [
        (
            openrouter.get_teacher_update_draft_chain,
            TeacherUpdateDraftResult,
            {
                "outcome": "draft",
                "title": "Lecture",
                "body": "Un atelier de lecture a eu lieu.",
                "questions": [],
            },
        ),
        (
            openrouter.get_teacher_update_draft_chain,
            TeacherUpdateDraftResult,
            {
                "outcome": "needs_more_information",
                "title": None,
                "body": None,
                "questions": ["Quelle activité souhaitez-vous présenter ?"],
            },
        ),
        (
            openrouter.get_guardian_weekly_explanation_chain,
            GuardianWeeklyExplanationModelResult,
            {
                "overview": [{"text": "Un atelier de lecture a eu lieu.", "source_keys": ["s1"]}],
                "attendance_summary": None,
                "school_updates": [],
                "follow_up": None,
            },
        ),
    ],
)
async def test_strict_request_and_validated_response(
    monkeypatch, factory, result_type, output
):
    monkeypatch.setattr(settings.llm, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(settings.llm, "OPENROUTER_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setattr(settings.llm, "OPENROUTER_MAX_RETRIES", 0)
    requests = []

    async def send(client, request, **kwargs):
        payload = json.loads(request.content)
        requests.append(payload)
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert payload["model"] == "openai/gpt-4.1-mini"
        assert payload["provider"] == {
            "require_parameters": True,
            "data_collection": "deny",
        }
        response_format = payload["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True
        _assert_strict_schema(response_format["json_schema"]["schema"])
        assert request.extensions["timeout"]["read"] == 20
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "chatcmpl-fixture",
                "object": "chat.completion",
                "created": 1,
                "model": payload["model"],
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": json.dumps(output)},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    result = await factory().ainvoke("Synthetic classroom observation.")
    assert len(requests) == 1
    assert result["parsing_error"] is None
    assert isinstance(result["parsed"], result_type)
    assert result["parsed"].model_dump(mode="json") == output
    assert result["raw"].usage_metadata["total_tokens"] == 12


@pytest.mark.asyncio
async def test_business_validation_is_kept_for_structured_responses(monkeypatch):
    monkeypatch.setattr(settings.llm, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(settings.llm, "OPENROUTER_MODEL", "openai/gpt-4.1-mini")

    async def send(client, request, **kwargs):
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "chatcmpl-invalid",
                "object": "chat.completion",
                "created": 1,
                "model": "openai/gpt-4.1-mini",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({
                            "outcome": "draft",
                            "title": None,
                            "body": "A draft must have a title.",
                            "questions": [],
                        }),
                    },
                    "finish_reason": "stop",
                }],
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    with pytest.raises(ValidationError, match="draft outcomes require title and body"):
        await openrouter.get_teacher_update_draft_chain().ainvoke("Synthetic observation.")
