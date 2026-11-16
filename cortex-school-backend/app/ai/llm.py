from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError

from core.config import settings


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMProviderError(RuntimeError):
    """Safe provider failure suitable for returning to the caller."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def _require_api_key() -> str:
    if not settings.llm.OPENAI_API_KEY:
        raise LLMNotConfiguredError(
            "OPENAI_API_KEY is not set. Add it to docker/.env to use AI endpoints."
        )
    return settings.llm.OPENAI_API_KEY


def get_chat_model() -> ChatOpenAI:
    if settings.llm.OPENROUTER_API_KEY:
        if not settings.llm.OPENROUTER_MODEL:
            raise LLMNotConfiguredError("Set OPENROUTER_MODEL in docker/.env.")
        return ChatOpenAI(
            api_key=settings.llm.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            model=settings.llm.OPENROUTER_MODEL,
            temperature=settings.llm.OPENROUTER_TEMPERATURE,
            max_tokens=settings.llm.OPENROUTER_MAX_TOKENS,
            timeout=settings.llm.OPENROUTER_TIMEOUT_SECONDS,
            max_retries=settings.llm.OPENROUTER_MAX_RETRIES,
        )
    if settings.llm.OPENAI_API_KEY.startswith("sk-or-"):
        raise LLMNotConfiguredError(
            "An OpenRouter key was configured as OPENAI_API_KEY. Move it to "
            "OPENROUTER_API_KEY and set OPENROUTER_MODEL in docker/.env, "
            "then recreate the API container."
        )
    return ChatOpenAI(
        api_key=_require_api_key(),
        model=settings.llm.OPENAI_MODEL,
        temperature=settings.llm.OPENAI_TEMPERATURE,
        max_tokens=settings.llm.OPENAI_MAX_TOKENS,
        timeout=20,
        max_retries=1,
    )


async def ainvoke(prompt: str) -> str:
    llm = get_chat_model()
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
    except APITimeoutError as exc:
        raise LLMProviderError("The AI provider timed out. Please try again.", 504) from exc
    except APIConnectionError as exc:
        raise LLMProviderError("Unable to connect to the AI provider. Please try again.") from exc
    except APIStatusError as exc:
        messages = {
            401: "The AI provider rejected the API key. Check the provider key in docker/.env and recreate the API container.",
            402: "The AI provider has insufficient credits. Check your provider account balance.",
            403: "The AI provider denied access. Check your key permissions and model access.",
            404: "The configured AI model is unavailable. Check the model name in docker/.env.",
            429: "The AI provider is rate limited or has no available quota. Check your account limits and try again.",
        }
        raise LLMProviderError(
            messages.get(exc.status_code, "The AI provider could not complete the request. Please try again."),
            429 if exc.status_code == 429 else 503,
        ) from exc
    return response.content
