"""Конфигурация приложения из переменных окружения (.env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR.parent / "frontend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: str = "gemini"  # gemini | anthropic | openai | demo
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    anthropic_model: str = "claude-opus-4-8"
    openai_model: str = "gpt-4o"
    llm_use_search: bool = True

    # DB
    database_url: str = "sqlite:///./data/ai_smeta.db"

    # Knowledge cache
    knowledge_cache_ttl_days: int = 180

    # CORS
    cors_origins: str = "*"

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "*").strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()
