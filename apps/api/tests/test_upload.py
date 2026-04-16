"""Tests for POST /drawings/upload.

S3 + queue are monkey-patched: the upload path is exercised end-to-end
against the real DB but without talking to MinIO or Redis. A second
integration-style test against the live Postgres validates that the
Drawing row lands with the right fields.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import drawings as drawings_service


@pytest.fixture()
def patched_storage(monkeypatch):
    """Replace S3 put + queue enqueue with no-op mocks."""
    put_mock = MagicMock()
    enqueue_mock = MagicMock(return_value="job-id-1")
    monkeypatch.setattr(drawings_service, "_put_pdf", put_mock)
    monkeypatch.setattr(drawings_service, "enqueue_ingest", enqueue_mock)

    # Publish is noisy without Redis; null it out.
    monkeypatch.setattr(drawings_service.events, "publish", MagicMock(return_value=0))
    return put_mock, enqueue_mock


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _pdf_bytes(payload: bytes = b"dummy content for testing") -> bytes:
    return b"%PDF-1.4\n" + payload + b"\n%%EOF\n"


def test_upload_happy_path(db, client, patched_storage):
    put_mock, enqueue_mock = patched_storage

    resp = client.post(
        "/drawings/upload",
        files={"file": ("plans.pdf", _pdf_bytes(), "application/pdf")},
        data={"project_name": "Studio 42"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_filename"] == "plans.pdf"
    assert body["project_name"] == "Studio 42"
    assert body["status"] == "queued"
    assert body["progress_percent"] == 0
    assert body["content_hash"].startswith("sha256:")
    assert body["size_bytes"] > 0

    put_mock.assert_called_once()
    enqueue_mock.assert_called_once_with(body["id"])


def test_upload_rejects_non_pdf_mime(db, client, patched_storage):
    resp = client.post(
        "/drawings/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 415
    body = resp.json()
    assert body["error"]["code"] == "unsupported_media_type"
    assert "text/plain" in body["error"]["message"]


def test_upload_rejects_non_pdf_magic_number(db, client, patched_storage):
    # Content-type lies — says PDF but the bytes aren't PDF magic.
    resp = client.post(
        "/drawings/upload",
        files={"file": ("fake.pdf", b"not a pdf at all", "application/pdf")},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "invalid_file"
    assert "%PDF-" in body["error"]["message"]


def test_upload_rejects_empty_file(db, client, patched_storage):
    resp = client.post(
        "/drawings/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "invalid_file"
    assert "empty" in body["error"]["message"]


def test_upload_enforces_size_limit(db, client, patched_storage, monkeypatch):
    # Drop the limit way down to make the test fast.
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    try:
        oversized = _pdf_bytes(b"A" * (2 * 1024 * 1024))  # 2 MB payload
        resp = client.post(
            "/drawings/upload",
            files={"file": ("big.pdf", oversized, "application/pdf")},
        )
        assert resp.status_code == 413
        body = resp.json()
        assert body["error"]["code"] == "payload_too_large"
        assert body["error"]["details"]["max_bytes"] == 1 * 1024 * 1024
    finally:
        get_settings.cache_clear()


def test_upload_persists_drawing_row(db, client, patched_storage):
    resp = client.post(
        "/drawings/upload",
        files={"file": ("real.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert resp.status_code == 201
    drawing_id = resp.json()["id"]

    from uuid import UUID

    from app.db import Drawing

    row = db.get(Drawing, UUID(drawing_id))
    assert row is not None
    assert row.status == "queued"
    assert row.source_s3_key.endswith("/source.pdf")
    assert row.progress_percent == 0


def test_upload_response_includes_request_id_on_error(db, client, patched_storage):
    resp = client.post(
        "/drawings/upload",
        files={"file": ("x.txt", b"no", "text/plain")},
        headers={"X-Request-ID": "req-abc-123"},
    )
    assert resp.status_code == 415
    assert resp.json()["error"]["request_id"] == "req-abc-123"
    assert resp.headers.get("X-Request-ID") == "req-abc-123"
