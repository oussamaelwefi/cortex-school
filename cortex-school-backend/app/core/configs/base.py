import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

if os.getenv("ENVIRONMENT") not in {"development", "testing"}:
    load_dotenv("/secrets/.env")


class ModelConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
