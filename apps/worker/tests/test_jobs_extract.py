"""Tests for the DXF extraction orchestrator.

These exercise the real Postgres + ORM path so we're proving the
end-to-end DXF → DB pipeline, not just the dataclass shuffling.
Redis events are stubbed via monkeypatch on ``worker.events.publish``
so we can assert what was emitted without touching a live broker.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import ezdxf
import pytest
from atlas_db import Drawing, Element, ElementSource, Sheet
from sqlalchemy.orm import Session

from worker.jobs import extract

# -------- helpers --------


def _make_drawing(db: Session) -> tuple[Drawing, Sheet]:
    d = Drawing(
        source_filename="x.dxf",
        source_s3_key="drawings/x/source.dxf",
        size_bytes=1,
        content_hash="sha256:test",
    )
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.commit()
    db.refresh(d)
    db.refresh(s)
    return d, s


def _floor_dxf(path: Path) -> Path:
    """Tiny synthetic DXF: 4 walls + 1 room polygon + 1 door arc."""
    doc = ezdxf.new(dxfversion="R2018")
    for layer in ("A-WALL-EXTR", "A-ROOM", "A-DOOR"):
        doc.layers.add(layer)
    msp = doc.modelspace()
    for a, b in [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 8)),
        ((10, 8), (0, 8)),
        ((0, 8), (0, 0)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})
    msp.add_lwpolyline(
        [(0, 0), (10, 0), (10, 8), (0, 8)],
        close=True,
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
    """Capture published events instead of hitting Redis."""
    events: list[tuple[UUID | str, dict]] = []
    monkeypatch.setattr(
        "worker.jobs.extract.events.publish",
        lambda drawing_id, payload: events.append((drawing_id, payload)) or 1,
    )
    return events


# -------- happy path --------


class TestExtractFromDxf:
    def test_writes_elements_for_each_candidate(
        self, db: Session, tmp_path: Path, captured_events
    ):
        d, _ = _make_drawing(db)
        path = _floor_dxf(tmp_path / "floor.dxf")

        summary = extract.extract_from_dxf(db, d.id, path)

        assert summary.elements_written == 6
        assert summary.elements_by_kind == {"wall": 4, "room": 1, "door": 1}
        assert summary.layer_counts == {"A-WALL-EXTR": 4, "A-ROOM": 1, "A-DOOR": 1}
        assert summary.skipped_entity_types == {}

        # Database state matches the summary.
        elements = db.query(Element).filter(Element.source_id == summary.source_id).all()
        assert len(elements) == 6
        kinds = sorted(e.kind for e in elements)
        assert kinds == ["door", "room", "wall", "wall", "wall", "wall"]

        wall = next(e for e in elements if e.kind == "wall")
        assert wall.ncs_layer == "A-WALL-EXTR"
        assert wall.ncs_major_group == "WALL"
        assert wall.ifc_type == "IfcWallStandardCase"
        assert wall.geometry["kind"] == "polyline"
        assert wall.confidence == pytest.approx(1.0)

    def test_source_row_is_completed(self, db: Session, tmp_path: Path, captured_events):
        d, _ = _make_drawing(db)
        path = _floor_dxf(tmp_path / "floor.dxf")
        summary = extract.extract_from_dxf(db, d.id, path)

        src = db.get(ElementSource, summary.source_id)
        assert src is not None
        assert src.status == "completed"
        assert src.source_kind == "extraction"
        assert src.producer_name == extract.PRODUCER_NAME
        assert src.started_at is not None
        assert src.finished_at is not None
        assert src.summary["elements_written"] == 6
        assert src.summary["elements_by_kind"]["wall"] == 4

    def test_publishes_started_and_completed_events(
        self, db: Session, tmp_path: Path, captured_events
    ):
        d, _ = _make_drawing(db)
        path = _floor_dxf(tmp_path / "floor.dxf")
        extract.extract_from_dxf(db, d.id, path)

        types = [payload["type"] for (_, payload) in captured_events]
        assert types[0] == "extraction.started"
        assert types[-1] == "extraction.completed"
        # Final completed event carries the summary.
        last = captured_events[-1][1]
        assert last["summary"]["elements_written"] == 6
        # Channel-key is the drawing id, not a string we made up.
        assert all(drawing_id == d.id for drawing_id, _ in captured_events)

    def test_progress_events_for_large_runs(
        self, db: Session, tmp_path: Path, monkeypatch, captured_events
    ):
        # Drop the threshold so a small DXF still triggers a progress tick.
        monkeypatch.setattr(extract, "PROGRESS_EVERY", 2)
        d, _ = _make_drawing(db)
        path = _floor_dxf(tmp_path / "many.dxf")
        extract.extract_from_dxf(db, d.id, path)

        types = [payload["type"] for (_, payload) in captured_events]
        assert types.count("extraction.progress") >= 2


# -------- sheet selection --------


class TestSheetResolution:
    def test_uses_first_sheet_when_id_not_given(
        self, db: Session, tmp_path: Path, captured_events
    ):
        d = Drawing(
            source_filename="x.dxf", source_s3_key="k", size_bytes=1,
            content_hash="sha256:y",
        )
        db.add(d)
        db.flush()
        # Add sheets out of order; the lower page_number wins.
        db.add_all([
            Sheet(drawing_id=d.id, page_number=3),
            Sheet(drawing_id=d.id, page_number=1),
        ])
        db.commit()

        path = _floor_dxf(tmp_path / "x.dxf")
        summary = extract.extract_from_dxf(db, d.id, path)

        elements = db.query(Element).filter(Element.source_id == summary.source_id).all()
        first_sheet = (
            db.query(Sheet)
            .filter(Sheet.drawing_id == d.id, Sheet.page_number == 1)
            .one()
        )
        assert {e.sheet_id for e in elements} == {first_sheet.id}

    def test_explicit_sheet_id_wins(
        self, db: Session, tmp_path: Path, captured_events
    ):
        d = Drawing(
            source_filename="x.dxf", source_s3_key="k", size_bytes=1,
            content_hash="sha256:y",
        )
        db.add(d)
        db.flush()
        db.add_all([
            Sheet(drawing_id=d.id, page_number=1),
            Sheet(drawing_id=d.id, page_number=2),
        ])
        db.commit()
        target_sheet = (
            db.query(Sheet).filter(Sheet.drawing_id == d.id, Sheet.page_number == 2).one()
        )

        path = _floor_dxf(tmp_path / "x.dxf")
        summary = extract.extract_from_dxf(db, d.id, path, sheet_id=target_sheet.id)

        elements = db.query(Element).filter(Element.source_id == summary.source_id).all()
        assert {e.sheet_id for e in elements} == {target_sheet.id}

    def test_drawing_with_no_sheets_raises(self, db: Session, tmp_path: Path):
        d = Drawing(
            source_filename="x.dxf", source_s3_key="k", size_bytes=1,
            content_hash="sha256:y",
        )
        db.add(d)
        db.commit()
        path = _floor_dxf(tmp_path / "x.dxf")

        with pytest.raises(ValueError, match="no sheets"):
            extract.extract_from_dxf(db, d.id, path)


# -------- failure path --------


class TestExtractFailure:
    def test_failure_marks_source_failed_and_publishes_event(
        self, db: Session, tmp_path: Path, captured_events
    ):
        d, _ = _make_drawing(db)
        bogus = tmp_path / "doesnotexist.dxf"

        with pytest.raises(OSError):
            extract.extract_from_dxf(db, d.id, bogus)

        # The source row exists and is marked failed.
        sources = db.query(ElementSource).filter(
            ElementSource.drawing_id == d.id
        ).all()
        assert len(sources) == 1
        src = sources[0]
        assert src.status == "failed"
        assert src.error_code  # populated
        assert src.error_message  # populated
        assert src.finished_at is not None

        # And no orphan elements landed.
        elements = db.query(Element).filter(Element.source_id == src.id).all()
        assert elements == []

        # An extraction.failed event went out.
        types = [payload["type"] for (_, payload) in captured_events]
        assert "extraction.failed" in types
        assert types[0] == "extraction.started"
