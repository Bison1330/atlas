"""Tests for GET /drawings/{id}/status and GET /drawings/{id}."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import Drawing, Sheet
from app.main import app
from tests.conftest import TEST_USER_ID


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _insert(db, **overrides) -> Drawing:
    defaults = dict(
        source_filename="plans.pdf",
        source_s3_key="drawings/xyz/source.pdf",
        size_bytes=1024,
        content_hash="sha256:abc",
        owner_id=TEST_USER_ID,
    )
    defaults.update(overrides)
    d = Drawing(**defaults)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def test_status_returns_current_state(db, client):
    d = _insert(
        db,
        status="rasterizing",
        progress_percent=42,
        progress_message="Rendering page 2 of 5",
    )

    resp = client.get(f"/drawings/{d.id}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rasterizing"
    assert body["progress_percent"] == 42
    assert body["progress_message"] == "Rendering page 2 of 5"
    assert "ETag" in resp.headers


def test_status_404_when_not_found(client):
    resp = client.get(f"/drawings/{uuid4()}/status")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"


def test_status_etag_returns_304_when_unchanged(db, client):
    d = _insert(db, status="queued", progress_percent=0)

    first = client.get(f"/drawings/{d.id}/status")
    etag = first.headers["ETag"]

    second = client.get(
        f"/drawings/{d.id}/status", headers={"If-None-Match": etag}
    )
    assert second.status_code == 304
    assert second.headers["ETag"] == etag
    assert second.content == b""


def test_status_etag_changes_when_progress_changes(db, client):
    d = _insert(db, status="rasterizing", progress_percent=10)
    etag_1 = client.get(f"/drawings/{d.id}/status").headers["ETag"]

    d.progress_percent = 50
    db.add(d)
    db.commit()

    etag_2 = client.get(f"/drawings/{d.id}/status").headers["ETag"]
    assert etag_1 != etag_2


def test_detail_202_while_in_progress(db, client):
    d = _insert(db, status="tiling", progress_percent=66, progress_message="Tiling A-101 (2 of 3)")
    resp = client.get(f"/drawings/{d.id}")
    assert resp.status_code == 202
    assert resp.headers.get("Retry-After") == "2"
    assert f"/drawings/{d.id}/status" in resp.headers.get("Location", "")
    body = resp.json()
    assert body["status"] == "tiling"
    assert body["progress_percent"] == 66
    # In-progress detail should not expose sheets.
    assert body["sheets"] == []


def test_detail_200_when_completed_with_sheets(db, client):
    d = _insert(db, status="completed", progress_percent=100, page_count=2)
    db.add_all(
        [
            Sheet(
                drawing_id=d.id,
                page_number=1,
                sheet_number="A-101",
                title="Floor Plan",
                status="completed",
                progress_percent=100,
            ),
            Sheet(
                drawing_id=d.id,
                page_number=2,
                sheet_number="A-102",
                status="completed",
                progress_percent=100,
            ),
        ]
    )
    db.commit()

    resp = client.get(f"/drawings/{d.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert len(body["sheets"]) == 2
    assert body["sheets"][0]["sheet_number"] == "A-101"
    assert body["sheets"][0]["page_number"] == 1


def test_detail_200_when_failed_with_error_fields(db, client):
    d = _insert(
        db,
        status="failed",
        progress_percent=30,
        error_code="pdf_unreadable",
        error_message="PDF is password-protected and cannot be processed.",
    )
    resp = client.get(f"/drawings/{d.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "pdf_unreadable"


def test_detail_404_when_not_found(client):
    resp = client.get(f"/drawings/{uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
