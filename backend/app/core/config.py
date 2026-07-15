"""Application configuration loaded from environment variables.

Every deployable setting lives here; nothing else in the codebase reads
os.environ directly. Values come from the process environment or a local
`.env` file (development only — never commit one).
"""

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    APP_NAME: str = "AttendAI"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # --- Database ---
    DATABASE_URL: PostgresDsn  # e.g. postgresql+asyncpg://user:pass@host:5432/attendai
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_ECHO: bool = False

    # --- Security (used from Module 2 onward) ---
    SECRET_KEY: str  # openssl rand -hex 32
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # --- Face pipeline (used from Module 4 onward) ---
    FACE_MODEL_NAME: str = "buffalo_l"
    FACE_DET_SIZE: int = 640  # 320 for low-end CPUs
    FACE_MATCH_THRESHOLD: float = 0.40  # cosine similarity
    FACE_MODEL_ROOT: str = "./models"

    # --- Storage ---
    MEDIA_ROOT: str = "./media"
    MAX_UPLOAD_SIZE_MB: int = 15

    @field_validator("DATABASE_URL")
    @classmethod
    def _require_asyncpg(cls, v: PostgresDsn) -> PostgresDsn:
        if v.scheme != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// scheme")
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — import this, not a module-level instance,
    so tests can override env vars before first access."""
    return Settings()  # type: ignore[call-arg]
