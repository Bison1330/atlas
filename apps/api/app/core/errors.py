"""Global exception handlers.

Every error path — ``APIError``, ``HTTPException``, ``RequestValidationError``,
and unhandled ``Exception`` — lands in the ``ErrorResponse`` envelope.
The ``request_id`` is pulled from the structlog contextvar that the
RequestIDMiddleware binds at the start of every request.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.errors import APIError, ErrorBody, ErrorResponse

log = structlog.get_logger("atlas.errors")


def _request_id() -> str | None:
    return structlog.contextvars.get_contextvars().get("request_id")


def _envelope(
    *,
    code: str,
    message: str,
    status_code: int,
    details: dict | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details,
            request_id=_request_id(),
        )
    )
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    log.info("api_error", code=exc.code, status=exc.status_code)
    return _envelope(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
    )


async def http_exception_handler(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code_map = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        413: "payload_too_large",
        415: "unsupported_media_type",
        422: "validation_error",
        429: "rate_limited",
        500: "internal_error",
        503: "service_unavailable",
    }
    code = code_map.get(exc.status_code, f"http_{exc.status_code}")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    details = exc.detail if not isinstance(exc.detail, str) else None
    return _envelope(
        code=code, message=message, status_code=exc.status_code, details=details
    )


async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return _envelope(
        code="validation_error",
        message="One or more request fields failed validation.",
        status_code=422,
        details={"errors": jsonable_encoder(exc.errors())},
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception", error_type=type(exc).__name__)
    return _envelope(
        code="internal_error",
        message="An unexpected error occurred. Please retry shortly.",
        status_code=500,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
