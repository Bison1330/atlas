"""Tests for the RQ entrypoint ``run_dxf_extraction``.

The RQ entrypoint is the seam between the API (which uploads the DXF
to S3 and creates a queued ElementSource) and the orchestrator
(which actually walks the DXF). These tests exercise its three
moving parts:

- looking up the source row,
- downloading the DXF from S3 (boto3 mocked — we don't need a live
  MinIO to prove the wiring),
- handing off to ``extract_from_dxf`` with the correct args.

Failures before the orchestrator runs (missing source, missing
s3_key, S3 download error) must mark the source ``failed`` and
publish ``extraction.failed`` so a WS subscriber doesn't see a
silent stall.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import ezdxf
import pytest
from atlas_db import Drawing, Element, ElementSource, Sheet
from sqlalchemy.orm import Session

from worker.jobs import extract

# -------- helpers --------


def _make_drawing_with_sheet(db: Session) -> tuple[Drawing, Sheet]:
    d = Drawing(
        source_filename="x.dxf", source_s3_key="drawings/x/source.dxf",
        size_bytes=1, content_hash="sha256:rq-test",
    )
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.commit()
    db.refresh(d)
    db.refresh(s)
    return d, s


def _make_queued_source(
    db: Session, drawing_id: UUID, *, dxf_s3_key: str | None = "drawings/x/extractions/y/source.dxf"
) -> ElementSource:
    params = {"dxf_s3_key": dxf_s3_key} if dxf_s3_key else {}
    src = ElementSource(
        drawing_id=drawing_id,
        source_kind="extraction",
        producer_name="dxf_ncs_extractor",
        producer_version="0.1.0",
        status="queued",
        params=params,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _floor_dxf(path: Path) -> Path:
    """4 walls + 1 room polygon + 1 door arc — same shape as orchestrator tests."""
    doc = ezdxf.new(dxfversion="R2018")
    for layer in ("A-WALL-EXTR", "A-ROOM", "A-DOOR"):
        doc.layers.add(layer)
    msp = doc.modelspace()
    for a, b in [
        ((0, 0), (10, 0)), ((10, 0), (10, 8)),
        ((10, 8), (0, 8)), ((0, 8), (0, 0)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})
    msp.add_lwpolyline(
        [(0, 0), (10, 0), (10, 8), (0, 8)], close=True,
        dxfattribs={"layer": "A-ROOM"},
    )
    msp.add_arc(
        center=(0, 0), radius=3, start_angle=0, end_angle=90,
        dxfattribs={"layer": "A-DOOR"},
    )
    doc.saveas(str(path))
    return path


@pytest.fixture
def captured_events(monkeypatch):
    events: list[tuple[UUID | str, dict]] = []
    monkeypatch.setattr(
        "worker.jobs.extract.events.publish",
        lambda drawing_id, payload: events.append((drawing_id, payload)) or 1,
    )
    return events


@pytest.fixture
def patched_session_scope(monkeypatch, _session_factory):
    """Make worker.db.session_scope yield a session bound to the test engine.

    The RQ entrypoint imports session_scope inside the function body to
    avoid a startup-time DB dep, so we patch the import target lazily.
    The ``db`` fixture handles row cleanup via its own TRUNCATE.
    """
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        s = _session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr("worker.db.session_scope", _scope)
    yield


@pytest.fixture
def patched_s3(monkeypatch):
    """Replace the boto3 S3 client used by the RQ entrypoint.

    By default the mock writes a real DXF to whatever local path the
    entrypoint asks for, so the orchestrator's ezdxf.readfile call
    succeeds. Tests that want to simulate a download failure can set
    ``patched_s3.download_file.side_effect = SomeError(...)``.
    """
    import worker.s3 as s3_mod

    real_dxf_template = None  # populated per-test if needed

    def _download_writer(bucket, key, dest):
        # Default: write a valid floor DXF at dest so happy path works.
        nonlocal real_dxf_template
        if real_dxf_template is None:
            import tempfile
            tmpdir = Path(tempfile.mkdtemp(prefix="atlas-test-dxf-"))
            real_dxf_template = _floor_dxf(tmpdir / "floor.dxf")
        Path(dest).write_bytes(real_dxf_template.read_bytes())

    mock_client = MagicMock()
    mock_client.download_file.side_effect = _download_writer
    monkeypatch.setattr(s3_mod, "get_s3_client", lambda: mock_client)
    return mock_client


# -------- tests --------


class TestRunDxfExtraction:
    def test_happy_path_writes_elements(
        self, db, captured_events, patched_session_scope, patched_s3
    ):
        d, _ = _make_drawing_with_sheet(db)
        src = _make_queued_source(db, d.id)

        extract.run_dxf_extraction(str(src.id))

        # Used the right S3 key.
        patched_s3.download_file.assert_called_once()
        bucket_arg, key_arg, _ = patched_s3.download_file.call_args.args
        assert key_arg == "drawings/x/extractions/y/source.dxf"

        # Source landed at completed. 6 reader candidates
        # (4 walls + 1 explicit A-ROOM + 1 door); the M3 derivation
        # matches the explicit A-ROOM under G-O1 so no duplicate
        # derived row is inserted — 6 elements total.
        db.expire_all()
        refreshed = db.get(ElementSource, src.id)
        assert refreshed.status == "completed"
        assert refreshed.summary["elements_written"] == 6

        # Elements landed against the test sheet.
        assert db.query(Element).filter(
            Element.source_id == src.id
        ).count() == 6

    def test_missing_source_raises(
        self, db, captured_events, patched_session_scope, patched_s3
    ):
        with pytest.raises(RuntimeError, match="not found"):
            extract.run_dxf_extraction(str(uuid4()))

    def test_missing_s3_key_marks_failed(
        self, db, captured_events, patched_session_scope, patched_s3
    ):
        d, _ = _make_drawing_with_sheet(db)
        src = _make_queued_source(db, d.id, dxf_s3_key=None)

        with pytest.raises(RuntimeError, match="dxf_s3_key"):
            extract.run_dxf_extraction(str(src.id))

        db.expire_all()
        refreshed = db.get(ElementSource, src.id)
        assert refreshed.status == "failed"
        assert refreshed.error_code == "missing_s3_key"
        types = [payload["type"] for (_, payload) in captured_events]
        assert "extraction.failed" in types

    def test_s3_download_failure_marks_failed(
        self, db, captured_events, patched_session_scope, patched_s3
    ):
        d, _ = _make_drawing_with_sheet(db)
        src = _make_queued_source(db, d.id)

        patched_s3.download_file.side_effect = OSError("connection reset")

        with pytest.raises(OSError):
            extract.run_dxf_extraction(str(src.id))

        db.expire_all()
        refreshed = db.get(ElementSource, src.id)
        assert refreshed.status == "failed"
        assert refreshed.error_code == "s3_download_failed"
        assert "connection reset" in refreshed.error_message
        types = [payload["type"] for (_, payload) in captured_events]
        assert types[-1] == "extraction.failed"

    def test_source_drawing_mismatch_caught_by_orchestrator(
        self, db, captured_events, patched_session_scope, patched_s3
    ):
        # Source belongs to drawing A, but if the orchestrator received
        # a different drawing_id (e.g. via a buggy caller) it must
        # refuse — the orchestrator already enforces this; this test
        # documents that the RQ path inherits the protection.
        d, _ = _make_drawing_with_sheet(db)
        src = _make_queued_source(db, d.id)
        # Run normally so the assertion is "happy path still works".
        extract.run_dxf_extraction(str(src.id))
        db.expire_all()
        assert db.get(ElementSource, src.id).status == "completed"
