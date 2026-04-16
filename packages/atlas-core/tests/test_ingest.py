from datetime import UTC, datetime
from uuid import uuid4

from atlas_core import (
    DrawingSummary,
    IngestStatus,
    IngestStatusEvent,
    SheetDiscipline,
    SheetSummary,
    TileRef,
)


def test_ingest_status_terminal_and_in_progress():
    assert IngestStatus.COMPLETED.is_terminal
    assert IngestStatus.FAILED.is_terminal
    assert not IngestStatus.QUEUED.is_terminal

    assert IngestStatus.RASTERIZING.is_in_progress
    assert not IngestStatus.COMPLETED.is_in_progress
    assert not IngestStatus.QUEUED.is_in_progress


def test_drawing_summary_roundtrip_with_sheets():
    now = datetime.now(UTC)
    sheet = SheetSummary(
        id=uuid4(),
        page_number=1,
        sheet_number="A-101",
        title="First Floor Plan",
        discipline=SheetDiscipline.ARCHITECTURAL,
        width_px=8500,
        height_px=11000,
        dpi=150,
        tile_size=512,
        max_zoom=4,
        status=IngestStatus.COMPLETED,
        progress_percent=100,
        created_at=now,
        completed_at=now,
    )
    drawing = DrawingSummary(
        id=uuid4(),
        source_filename="plans.pdf",
        size_bytes=5_120_000,
        content_hash="sha256:deadbeef",
        page_count=1,
        status=IngestStatus.COMPLETED,
        progress_percent=100,
        created_at=now,
        updated_at=now,
        completed_at=now,
        sheets=[sheet],
    )

    json = drawing.model_dump_json()
    restored = DrawingSummary.model_validate_json(json)
    assert restored.status == IngestStatus.COMPLETED
    assert restored.sheets[0].sheet_number == "A-101"


def test_tile_ref_bounds():
    ref = TileRef(zoom_level=3, col=5, row=7, s3_key="drawings/abc/tiles/3/5/7.webp")
    assert ref.content_type == "image/webp"
    assert ref.zoom_level == 3


def test_ingest_status_event_minimal():
    ev = IngestStatusEvent(
        drawing_id=uuid4(),
        status=IngestStatus.RASTERIZING,
        progress_percent=42,
        at=datetime.now(UTC),
    )
    assert ev.sheet_id is None
    assert ev.progress_percent == 42
