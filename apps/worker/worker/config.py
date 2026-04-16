"""Worker configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    sentry_dsn: str | None = None

    redis_url: str = Field(default="redis://redis:6379/0")
    queues: str = Field(default="default")

    @property
    def queue_list(self) -> list[str]:
        return [q.strip() for q in self.queues.split(",") if q.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


def get_settings() -> WorkerSettings:
    return WorkerSettings()
