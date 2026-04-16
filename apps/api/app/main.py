"""FastAPI app factory."""

from __future__ import annotations

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.middleware.request_id import RequestIDMiddleware
from app.routes import health


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


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, production=settings.is_production)
    _init_sentry(settings)

    app = FastAPI(
        title="Atlas API",
        version="0.1.0",
        description="Architecture that checks itself — API gateway.",
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIDMiddleware)

    app.include_router(health.router)

    log = get_logger("atlas.api")
    log.info(
        "api.startup",
        environment=settings.environment,
        sentry=bool(settings.sentry_dsn),
    )
    return app


app = create_app()
