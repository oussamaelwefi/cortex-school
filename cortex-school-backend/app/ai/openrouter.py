from langchain_openrouter import ChatOpenRouter

from core.config import settings


class OpenRouterNotConfiguredError(RuntimeError):
    pass


def _get_structured_chain(schema):
    if not settings.llm.OPENROUTER_API_KEY:
        raise OpenRouterNotConfiguredError("OPENROUTER_API_KEY is not configured")
    if not settings.llm.OPENROUTER_MODEL:
        raise OpenRouterNotConfiguredError("OPENROUTER_MODEL is not configured")

    model = ChatOpenRouter(
        api_key=settings.llm.OPENROUTER_API_KEY,
        model=settings.llm.OPENROUTER_MODEL,
        temperature=settings.llm.OPENROUTER_TEMPERATURE,
        max_tokens=settings.llm.OPENROUTER_MAX_TOKENS,
        # ChatOpenRouter uses milliseconds (the OpenAI adapter uses seconds).
        timeout=max(1, round(settings.llm.OPENROUTER_TIMEOUT_SECONDS * 1000)),
        max_retries=settings.llm.OPENROUTER_MAX_RETRIES,
        openrouter_provider={
            "require_parameters": True,
            "data_collection": "deny",
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
