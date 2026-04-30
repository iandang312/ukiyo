from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    BUCKET_MODEL_MAP: dict[str, str] = Field(
        default_factory=lambda: {
            "coding": "claude-sonnet-4-6",
            "design": "gpt-4o",
            "research": "gemini-2.5-pro",
        }
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
