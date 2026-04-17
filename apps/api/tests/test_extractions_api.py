"""Tests for POST /drawings/{id}/extract and GET /drawings/{id}/extractions.

S3 + queue are monkey-patched, mirroring the M1 upload tests. The DB
side is real so we're verifying the ElementSource row lands with the
right shape (params include the S3 key, status is 'queued').
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import Drawing, ElementSource, Sheet
from app.main import app
from app.services import extractions as extractions_service
from tests.conftest import TEST_USER_ID


@pytest.fixture()
def patched_storage(monkeypatch):
    put_mock = MagicMock()
    enqueue_mock = MagicMock(return_value="rq-job-id-1")
    monkeypatch.setattr(extractions_service, "_put_dxf", put_mock)
    monkeypatch.setattr(extractions_service, "enqueue_extraction", enqueue_mock)
    monkeypatch.setattr(
        extractions_service.events, "publish", MagicMock(return_value=0)
    )
    return put_mock, enqueue_mock


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _ascii_dxf(filler: str = "TEST") -> bytes:
    """Smallest thing that passes the DXF magic sniff."""
    return f"  0\nSECTION\n  2\n{filler}\n  0\nENDSEC\n  0\nEOF\n".encode()


def _make_drawing_with_sheet(db) -> tuple[Drawing, Sheet]:
    d = Drawing(
        source_filename="x.pdf", source_s3_key="drawings/x/source.pdf",
        size_bytes=1, content_hash="sha256:test",
            owner_id=TEST_USER_ID,
        )
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.commit()
    db.refresh(d)
    db.refresh(s)
    return d, s


# -------- happy path --------


class TestTriggerExtraction:
    def test_upload_creates_queued_source(self, db, client, patched_storage):
        put_mock, enqueue_mock = patched_storage
        d, _ = _make_drawing_with_sheet(db)

        body = _ascii_dxf()
        r = client.post(
            f"/drawings/{d.id}/extract",
            files={"file": ("plan.dxf", body, "application/dxf")},
        )
        assert r.status_code == 202, r.text
        payload = r.json()
        assert payload["drawing_id"] == str(d.id)
        assert payload["status"] == "queued"
        assert payload["source_kind"] == "extraction"
        assert payload["producer_name"] == "dxf_ncs_extractor"
        assert payload["params"]["dxf_filename"] == "plan.dxf"
        assert payload["params"]["dxf_size_bytes"] == len(body)
        assert payload["params"]["dxf_s3_key"].endswith("/source.dxf")

        # Side effects: S3 upload + enqueue both fired exactly once.
        put_mock.assert_called_once()
        enqueue_mock.assert_called_once_with(payload["id"])

        # Row landed in DB.
        row = db.get(ElementSource, payload["id"])
        assert row is not None
        assert row.status == "queued"


# -------- validation errors --------


class TestValidationErrors:
    def test_unknown_drawing_returns_404(self, db, client, patched_storage):
        body = _ascii_dxf()
        r = client.post(
            f"/drawings/{uuid4()}/extract",
            files={"file": ("plan.dxf", body, "application/dxf")},
        )
        assert r.status_code == 404

    def test_drawing_with_no_sheet_rejected(self, db, client, patched_storage):
        # Drawing exists but has no sheet (ingest hasn't completed).
        d = Drawing(
            source_filename="x.pdf", source_s3_key="k", size_bytes=1,
            content_hash="sha256:y",
                    owner_id=TEST_USER_ID,
        )
        db.add(d)
        db.commit()
        body = _ascii_dxf()
        r = client.post(
            f"/drawings/{d.id}/extract",
            files={"file": ("plan.dxf", body, "application/dxf")},
        )
        assert r.status_code == 400
        assert "no sheets" in r.json()["error"]["message"].lower()

    def test_non_dxf_filename_rejected(self, db, client, patched_storage):
        d, _ = _make_drawing_with_sheet(db)
        r = client.post(
            f"/drawings/{d.id}/extract",
            files={"file": ("plan.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert r.status_code == 400
        assert ".dxf" in r.json()["error"]["message"].lower()

    def test_empty_file_rejected(self, db, client, patched_storage):
        d, _ = _make_drawing_with_sheet(db)
        r = client.post(
            f"/drawings/{d.id}/extract",
            files={"file": ("plan.dxf", b"", "application/dxf")},
        )
        assert r.status_code == 400

    def test_dxf_with_bad_header_rejected(self, db, client, patched_storage):
        d, _ = _make_drawing_with_sheet(db)
        # File ends in .dxf but doesn't look like one.
        r = client.post(
            f"/drawings/{d.id}/extract",
            files={"file": ("plan.dxf", b"not a real dxf at all", "application/dxf")},
        )
        assert r.status_code == 400
        assert "header sniff" in r.json()["error"]["message"].lower()


# -------- queue failure rollback --------


class TestQueueFailureRollback:
    def test_queue_down_rolls_back_source_row(self, db, client, monkeypatch):
        d, _ = _make_drawing_with_sheet(db)
        monkeypatch.setattr(extractions_service, "_put_dxf", MagicMock())
        monkeypatch.setattr(
            extractions_service, "enqueue_extraction",
            MagicMock(side_effect=RuntimeError("redis down")),
        )
        monkeypatch.setattr(
            extractions_service.events,
            "publish",
            MagicMock(return_value=0),
        )

        body = _ascii_dxf()
        r = client.post(
            f"/drawings/{d.id}/extract",
            files={"file": ("plan.dxf", body, "application/dxf")},
        )
        assert r.status_code == 503
        # No partial row landed.
        sources = db.query(ElementSource).filter(
            ElementSource.drawing_id == d.id
        ).all()
        assert sources == []


# -------- listing --------


class TestListExtractions:
    def test_empty_listing(self, db, client):
        d, _ = _make_drawing_with_sheet(db)
        r = client.get(f"/drawings/{d.id}/extractions")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 0
        assert body["extractions"] == []

    def test_listing_returns_newest_first(self, db, client):
        d, _ = _make_drawing_with_sheet(db)
        for ver in ("0.1.0", "0.2.0", "0.3.0"):
            db.add(ElementSource(
                drawing_id=d.id,
                source_kind="extraction",
                producer_name="dxf_ncs_extractor",
                producer_version=ver,
                status="completed",
            ))
            db.commit()
        r = client.get(f"/drawings/{d.id}/extractions")
        body = r.json()
        assert body["count"] == 3
        versions = [e["producer_version"] for e in body["extractions"]]
        assert versions == ["0.3.0", "0.2.0", "0.1.0"]

    def test_listing_unknown_drawing_returns_404(self, db, client):
        # M7: ownership-resolution 404s unknown drawings.
        r = client.get(f"/drawings/{uuid4()}/extractions")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"
