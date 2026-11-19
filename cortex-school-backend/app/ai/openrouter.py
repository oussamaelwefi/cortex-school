from langchain_openai import ChatOpenAI

from core.config import settings


class OpenRouterNotConfiguredError(RuntimeError):
    pass


def _get_structured_chain(schema):
    if not settings.llm.OPENROUTER_API_KEY:
        raise OpenRouterNotConfiguredError("OPENROUTER_API_KEY is not configured")
    if not settings.llm.OPENROUTER_MODEL:
        raise OpenRouterNotConfiguredError("OPENROUTER_MODEL is not configured")

    # Use the chat adapter's Pydantic serializer: strict schemas require every
    # property to be present, including nullable fields and empty lists.
    model = ChatOpenAI(
        api_key=settings.llm.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        model=settings.llm.OPENROUTER_MODEL,
        temperature=settings.llm.OPENROUTER_TEMPERATURE,
        max_tokens=settings.llm.OPENROUTER_MAX_TOKENS,
        timeout=settings.llm.OPENROUTER_TIMEOUT_SECONDS,
        max_retries=settings.llm.OPENROUTER_MAX_RETRIES,
        extra_body={
            "provider": {
                "require_parameters": True,
                "data_collection": "deny",
            },
        },
    )
    return model.with_structured_output(
        schema,
        method="json_schema",
        strict=True,
        include_raw=True,
    )


def get_teacher_update_draft_chain():
    from modules.ai.schemas import TeacherUpdateDraftResult

    return _get_structured_chain(TeacherUpdateDraftResult)


def get_guardian_weekly_explanation_chain():
    from modules.ai.schemas import GuardianWeeklyExplanationModelResult

    return _get_structured_chain(GuardianWeeklyExplanationModelResult)
