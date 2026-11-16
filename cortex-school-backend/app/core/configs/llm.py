from .base import ModelConfig


class LLMConfig(ModelConfig):
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4.1-mini"
    OPENAI_TEMPERATURE: float = 0.2
    OPENAI_MAX_TOKENS: int = 500
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openai/gpt-5.6-terra"
    OPENROUTER_TEMPERATURE: float = 0.2
    OPENROUTER_MAX_TOKENS: int = 500
    OPENROUTER_TIMEOUT_SECONDS: float = 20
    OPENROUTER_MAX_RETRIES: int = 1
