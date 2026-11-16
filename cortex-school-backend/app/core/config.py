from functools import lru_cache
from pathlib import Path

from .configs.base import ModelConfig
from .configs.database import DatabaseConfig
from .configs.llm import LLMConfig


class Settings(ModelConfig):
    PROJECT_NAME: str = "my-service"
    ENVIRONMENT: str = "development"
    ADMIN_SESSION_SECRET: str = ""
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"
    AI_TEACHER_DRAFT_REDIS_URL: str = "redis://redis:6379/2"
    AI_TEACHER_DRAFT_RATE_WINDOW_SECONDS: int = 600
    AI_TEACHER_DRAFT_USER_RATE_LIMIT: int = 10
    AI_TEACHER_DRAFT_ORGANIZATION_RATE_LIMIT: int = 100
    WORKOS_API_KEY: str = ""
    WORKOS_OPERATOR_USER_IDS: list[str] = []
    WORKOS_API_BASE_URL: str = "https://api.workos.com"
    WORKOS_WEBHOOK_SECRET: str = ""
    WORKOS_INVITATION_TASK_RATE_LIMIT: str = "1/s"
    database: DatabaseConfig = DatabaseConfig()
    llm: LLMConfig = LLMConfig()

    @property
    def ROOT_PATH(self) -> Path:
        return Path(__file__).parent.parent


@lru_cache(maxsize=1)
def get_settings():
    return Settings()


settings = get_settings()
