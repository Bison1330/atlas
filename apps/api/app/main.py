"""FastAPI app factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.s3 import ensure_bucket
from app.middleware.request_id import RequestIDMiddleware
from app.routes import drawings, health, sheets, websocket


def _init_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        send_default_pii=False,
        traces_sample_rate=0.1 if settings.is_production else 0.0,
        integrations=[StarletteIntegration(), FastApiIntegration()],
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup/shutdown hooks.

    On startup: create the drawings bucket if it's missing. A failure
    here (S3 transiently down) is logged but doesn't prevent the app
    from booting — health/readiness will surface the issue.
    """
    log = get_logger("atlas.api")
    try:
        ensure_bucket()
        log.info("api.bucket_ready", bucket=get_settings().s3_bucket)
    except Exception:
        log.exception("api.bucket_ensure_failed")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, production=settings.is_production)
    _init_sentry(settings)

    app = FastAPI(
        title="Atlas API",
        version="0.2.0",
        description="Architecture that checks itself — API gateway.",
        docs_url="/docs",
        redoc_url=None,
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "ETag", "Retry-After", "Location"],
    )
    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(drawings.router)
    app.include_router(sheets.router)
    app.include_router(websocket.router)

    log = get_logger("atlas.api")
    log.info(
        "api.startup",
        environment=settings.environment,
        sentry=bool(settings.sentry_dsn),
        max_upload_mb=settings.max_upload_mb,
    )
    return app


app = create_app()
