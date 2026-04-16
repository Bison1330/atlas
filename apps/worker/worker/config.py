"""Worker configuration.

Mirrors the API's S3/DB env vars so docker-compose can pass a single
block to both services. When a var has a default the worker will boot
without it; values without defaults (DB/S3 creds) must be provided.
"""

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

    # Queues / Redis
    redis_url: str = Field(default="redis://redis:6379/0")
    queues: str = Field(default="default")

    # Postgres
    database_url: str = Field(
        default="postgresql+psycopg://atlas:atlas@postgres:5432/atlas"
    )

    # S3 / object storage
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "atlas"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_drawings_prefix: str = "drawings"

    # Ingest-pipeline tuning
    rasterize_dpi: int = Field(default=300, ge=72, le=600)
    tile_size: int = Field(default=512, ge=128, le=2048)
    tile_overlap: int = Field(default=2, ge=0, le=64)
    max_zoom_levels: int = Field(default=7, ge=1, le=10)  # zoom 0..N-1 inclusive
    tile_webp_quality: int = Field(default=80, ge=10, le=100)
    s3_upload_retries: int = Field(default=3, ge=0, le=10)

    @property
    def queue_list(self) -> list[str]:
        return [q.strip() for q in self.queues.split(",") if q.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


_settings: WorkerSettings | None = None


def get_settings() -> WorkerSettings:
    global _settings
    if _settings is None:
        _settings = WorkerSettings()
    return _settings
