"""Error response envelope.

Every error — validation, HTTP, or unhandled — serializes to the same
shape so the frontend doesn't need to branch on error kind:

    {
      "error": {
        "code": "payload_too_large",
        "message": "Upload exceeds maximum size of 500 MB.",
        "details": {...},        # optional, structured context
        "request_id": "..."      # from X-Request-ID middleware
      }
    }
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


class APIError(Exception):
    """Exception carrying a machine-readable code + HTTP status.

    Raise this from services and routes instead of ``HTTPException`` when
    you want the envelope applied automatically by the global handler.

    ``headers`` is an optional dict of response headers the handler
    applies to the error response. Needed for 429 responses that must
    carry ``Retry-After`` — setting ``response.headers[...]`` at the
    route level doesn't work because the handler builds its own
    ``JSONResponse``.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        self.headers = headers


class NotFoundError(APIError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            code="not_found",
            message=f"{resource} {identifier!r} was not found.",
            status_code=404,
            details={"resource": resource, "id": identifier},
        )


class UnsupportedMediaTypeError(APIError):
    def __init__(self, received: str | None, allowed: list[str]) -> None:
        super().__init__(
            code="unsupported_media_type",
            message=(
                f"Unsupported media type {received!r}. "
                f"Allowed: {', '.join(allowed)}."
            ),
            status_code=415,
            details={"received": received, "allowed": allowed},
        )


class PayloadTooLargeError(APIError):
    def __init__(self, max_bytes: int, received_bytes: int | None = None) -> None:
        max_mb = max_bytes // (1024 * 1024)
        super().__init__(
            code="payload_too_large",
            message=(
                f"Upload exceeds maximum size of {max_mb} MB."
                if received_bytes is None
                else (
                    f"Upload of {received_bytes / (1024 * 1024):.1f} MB exceeds "
                    f"maximum size of {max_mb} MB."
                )
            ),
            status_code=413,
            details={"max_bytes": max_bytes, "received_bytes": received_bytes},
        )


class MissingFileError(APIError):
    def __init__(self, field: str = "file") -> None:
        super().__init__(
            code="missing_file",
            message=f"Required upload field {field!r} was not provided.",
            status_code=400,
            details={"field": field},
        )


class InvalidFileError(APIError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            code="invalid_file",
            message=f"Uploaded file is invalid: {reason}",
            status_code=400,
            details={"reason": reason},
        )


class ServiceError(APIError):
    def __init__(
        self,
        *,
        code: str = "internal_error",
        message: str = "An internal error occurred.",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code=code, message=message, status_code=status_code, details=details
        )

    @classmethod
    def storage_unavailable(cls) -> ServiceError:
        return cls(
            code="storage_unavailable",
            message="Object storage is unreachable. Please retry shortly.",
            status_code=503,
        )

    @classmethod
    def queue_unavailable(cls) -> ServiceError:
        return cls(
            code="queue_unavailable",
            message="Background job queue is unreachable. Please retry shortly.",
            status_code=503,
        )
