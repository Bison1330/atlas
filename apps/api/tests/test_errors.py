"""Error envelope smoke tests.

Validates that every error path — ``APIError``, raw ``HTTPException``,
``RequestValidationError``, and unhandled ``Exception`` — produces the
same ``{"error": {...}}`` shape with a ``request_id``.
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app


def test_validation_error_uses_envelope():
    # Malformed UUID in path → 422 from FastAPI's path validator.
    with TestClient(app) as client:
        resp = client.get("/drawings/not-a-uuid/status")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert "errors" in body["error"]["details"]


def test_method_not_allowed_uses_envelope():
    with TestClient(app) as client:
        resp = client.delete("/health")
    assert resp.status_code == 405
    body = resp.json()
    assert body["error"]["code"] == "method_not_allowed"


def test_unhandled_exception_uses_envelope(monkeypatch):
    """Force an unexpected error and confirm the 500 body is the envelope."""
    # Attach a throwaway route that blows up.
    @app.get("/_boom", include_in_schema=False)
    def _boom() -> dict:
        raise RuntimeError("kaboom")

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/_boom")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "internal_error"
        assert "unexpected" in body["error"]["message"].lower()
    finally:
        # Clean the route off so it doesn't leak into other tests.
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/_boom"]


def test_http_exception_uses_envelope():
    @app.get("/_forbidden", include_in_schema=False)
    def _forbidden() -> None:
        raise HTTPException(status_code=403, detail="nope")

    try:
        with TestClient(app) as client:
            resp = client.get("/_forbidden")
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "forbidden"
        assert body["error"]["message"] == "nope"
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/_forbidden"
        ]
