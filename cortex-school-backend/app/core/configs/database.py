from .base import ModelConfig


class DatabaseConfig(ModelConfig):

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str

    SCHEMA_NAME: str = "backend_schema"

    @property
    def DATABASE_URI(self) -> str:
        # psycopg = psycopg3
        return f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
