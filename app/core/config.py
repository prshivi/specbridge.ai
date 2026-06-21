from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "SpecBridge AI"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    upload_dir: Path = Path("data/uploads")
    max_upload_size_mb: int = Field(default=10, ge=1, le=100)
    chroma_dir: Path = Path("data/chroma")
    chroma_collection: str = "specbridge_chunks"
    understanding_cache_db: Path = Path("data/specbridge.db")
    agent_framework_db: Path = Path("data/specbridge.db")
    agent_retry_attempts: int = Field(default=2, ge=1, le=10)
    agent_retry_delay_seconds: float = Field(default=0.25, ge=0.0, le=60.0)
    mock_ai: bool = False
    openai_api_key: SecretStr | None = None
    openai_understanding_model: str = "gpt-5.5"
    openai_requirements_model: str = "gpt-5.5"
    openai_ambiguity_model: str = "gpt-5.5"
    openai_conflict_model: str = "gpt-5.5"
    openai_missing_requirements_model: str = "gpt-5.5"
    openai_assumption_model: str = "gpt-5.5"
    openai_translator_model: str = "gpt-5.5"
    openai_architecture_model: str = "gpt-5.5"
    openai_copilot_model: str = "gpt-5.5"

    @property
    def max_upload_size_bytes(self) -> int:
        """Return the configured upload limit in bytes."""
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
