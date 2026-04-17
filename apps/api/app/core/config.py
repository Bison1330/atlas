"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

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

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    sentry_dsn: str | None = None

    database_url: str = Field(
        default="postgresql+psycopg://atlas:atlas@postgres:5432/atlas"
    )
    redis_url: str = Field(default="redis://redis:6379/0")

    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "atlas"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_drawings_prefix: str = "drawings"

    # Upload limits.
    max_upload_mb: int = Field(default=500, ge=1, le=5000)
    allowed_upload_mime_types: str = "application/pdf"

    # RQ queue names.
    ingest_queue: str = "default"

    cors_origins: str = "http://localhost:3000"

    # Anthropic API for M5 Q&A. When missing, the /ask endpoint
    # returns 503; everything else works. This lets local dev and
    # CI run without provisioning a key.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # M7 auth.
    # ``session_secret`` signs the opaque session-id cookie. Rotating
    # it invalidates all live sessions by design. MUST be set in
    # production (any non-empty string); dev / test generate a
    # random one on startup if absent.
    session_secret: str | None = None
    session_ttl_seconds: int = 14 * 24 * 3600  # 14 days
    session_cookie_name: str = "atlas_session"
    csrf_cookie_name: str = "atlas_csrf"
    csrf_header_name: str = "X-Atlas-CSRF"

    # Password policy — kept narrow by design (NIST SP 800-63B).
    password_min_length: int = 10

    # Auth rate limits — Redis-backed sliding windows.
    login_max_attempts: int = 5
    login_window_seconds: int = 15 * 60
    register_max_attempts: int = 3
    register_window_seconds: int = 60 * 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_mime_set(self) -> set[str]:
        return {m.strip() for m in self.allowed_upload_mime_types.split(",") if m.strip()}

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
