from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    DATABASE_URL: str = "postgresql+asyncpg://ukiyo:ukiyo@localhost:5432/ukiyo"
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    JWT_SECRET: str = "dev-secret-change-me"
    DAILY_TOKEN_CAP: int = 100_000
    GENERALIST_MODEL: str = "claude-sonnet-4-6"
    # NoDecode skips pydantic-settings' default JSON parse for complex types
    # so the validator below can accept the simpler `a,b,c` env shape.
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    BUCKET_MODEL_MAP: dict[str, str] = Field(
        default_factory=lambda: {
            "coding": "claude-sonnet-4-6",
            "design": "gpt-4o",
            # Gemini 2.5 Flash with the google_search grounding tool — see
            # Phase 6.5. Cheap (~$0.30/$2.50 per M tokens), grounding is free
            # for the first 1500 requests/day per Google project, citations
            # arrive in the response. GoogleProvider attaches the tool
            # unconditionally; needs GOOGLE_API_KEY in .env.
            "research": "gemini-2.5-flash",
        }
    )

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
