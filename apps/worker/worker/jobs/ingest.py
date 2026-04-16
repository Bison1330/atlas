"""Ingest orchestrator — the RQ job entrypoint.

``process_drawing(drawing_id)`` is registered in the API's queue under
``worker.jobs.ingest.process_drawing``. Its job is to drive a single
Drawing from ``queued`` → ``completed`` (or ``failed``), committing
progress after each meaningful step so the frontend's WebSocket sees
smooth transitions.

Progress budget:
  0–5%    validation + metadata + source download
  5–50%   rasterization (45% split across N pages)
  50–90%  tiling + upload (40% split across N pages)
  90–100% finalize
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from uuid import UUID

import structlog
from atlas_core import IngestStatus
from atlas_db import Drawing, Sheet, Tile
from sqlalchemy import select
from sqlalchemy.orm import Session

from worker import s3 as s3_mod
from worker.config import get_settings
from worker.db import session_scope
from worker.pipeline import pdf as pdf_mod
from worker.pipeline import raster as raster_mod
from worker.pipeline import tiles as tiles_mod
from worker.pipeline.errors import IngestError, StorageError
from worker.pipeline.progress import ProgressReporter

log = structlog.get_logger("atlas.worker.ingest")


def process_drawing(drawing_id: str) -> None:
    """RQ entrypoint. See module docstring."""
    started = time.monotonic()
    log.info("ingest.start", drawing_id=drawing_id)

    with session_scope() as session:
        drawing = _load_drawing(session, UUID(drawing_id))
        reporter = ProgressReporter(session, drawing)

        try:
            _run_pipeline(session, reporter, drawing)
        except IngestError as exc:
            reporter.fail(code=exc.code, message=exc.message)
            session.commit()
            log.warning(
                "ingest.failed_typed",
                drawing_id=drawing_id,
                code=exc.code,
                message=exc.message,
            )
            raise
        except Exception as exc:
            reporter.fail(code="ingest_failed", message=f"Unexpected error: {exc}")
            session.commit()
            log.exception("ingest.failed_unexpected", drawing_id=drawing_id)
            raise

    log.info(
        "ingest.completed",
        drawing_id=drawing_id,
        seconds=round(time.monotonic() - started, 2),
    )


def _load_drawing(session: Session, drawing_id: UUID) -> Drawing:
    drawing = session.execute(
        select(Drawing).where(Drawing.id == drawing_id)
    ).scalars().one_or_none()
    if drawing is None:
        raise RuntimeError(f"drawing {drawing_id} not found")
    return drawing


def _run_pipeline(
    session: Session, reporter: ProgressReporter, drawing: Drawing
) -> None:
    settings = get_settings()

    with tempfile.TemporaryDirectory(prefix="atlas-ingest-") as workdir_str:
        workdir = Path(workdir_str)

        # ---- 0-5%: validate + metadata ----
        reporter.drawing(
            status=IngestStatus.VALIDATING,
            percent=2,
            message="Analyzing PDF structure…",
        )
        session.commit()

        source_path = workdir / "source.pdf"
        _download_source(drawing, source_path)

        metadata = pdf_mod.validate_and_extract_metadata(source_path)

        drawing.page_count = metadata.page_count
        drawing.extra = {
            **(drawing.extra or {}),
            "pdf_title": metadata.title,
            "pdf_author": metadata.author,
            "pdf_producer": metadata.producer,
            "pdf_creation_date": metadata.creation_date,
        }
        session.add(drawing)

        sheets = _create_sheet_rows(session, drawing, metadata, settings)
        session.flush()

        reporter.drawing(
            status=IngestStatus.VALIDATING,
            percent=5,
            message=f"Found {metadata.page_count} page(s). Preparing to render…",
        )
        session.commit()

        # ---- 5-50%: rasterize + tile each page (interleaved per page) ----
        n = metadata.page_count
        for page_num, image in raster_mod.rasterize_pages(
            source_path, dpi=settings.rasterize_dpi
        ):
            sheet = sheets[page_num - 1]
            overall_raster_pct = 5 + int(45 * page_num / n)
            reporter.sheet(
                sheet,
                status=IngestStatus.RASTERIZING,
                percent=50,
                overall_percent=overall_raster_pct,
                overall_message=f"Rasterizing page {page_num} of {n}…",
            )
            session.commit()

            sheet.width_px = image.width
            sheet.height_px = image.height
            sheet.dpi = settings.rasterize_dpi
            session.add(sheet)

            # Preview thumbnail first — cheap and lets the UI show
            # something before every tile finishes uploading.
            preview_bytes = tiles_mod.generate_preview(image)
            preview_key = s3_mod.sheet_preview_key(str(drawing.id), str(sheet.id))
            _upload_bytes(preview_bytes, preview_key, content_type="image/webp")
            sheet.preview_s3_key = preview_key

            # Tile pyramid
            overall_tile_start = 50 + int(40 * (page_num - 1) / n)
            overall_tile_end = 50 + int(40 * page_num / n)
            reporter.sheet(
                sheet,
                status=IngestStatus.TILING,
                percent=0,
                overall_percent=overall_tile_start,
                overall_message=f"Generating tiles for page {page_num} of {n}…",
            )
            session.commit()

            max_zoom = _ingest_tiles(
                session, drawing, sheet, image, settings,
                overall_start=overall_tile_start,
                overall_end=overall_tile_end,
                reporter=reporter,
                page_num=page_num,
                total_pages=n,
            )
            sheet.tile_size = settings.tile_size
            sheet.max_zoom = max_zoom
            image.close()

            reporter.sheet(
                sheet,
                status=IngestStatus.COMPLETED,
                percent=100,
                overall_percent=overall_tile_end,
                overall_message=f"Finished page {page_num} of {n}.",
            )
            session.commit()

        # ---- 90-100%: finalize ----
        reporter.drawing(
            status=IngestStatus.TILING,
            percent=95,
            message="Finalizing…",
        )
        session.commit()

        reporter.drawing(
            status=IngestStatus.COMPLETED,
            percent=100,
            message=f"Ingest complete — {metadata.page_count} page(s) ready.",
        )
        session.commit()


# ---- helpers ----


def _download_source(drawing: Drawing, target: Path) -> None:
    try:
        s3_mod.get_s3_client().download_file(
            get_settings().s3_bucket,
            drawing.source_s3_key,
            str(target),
        )
    except Exception as exc:
        raise StorageError(f"Failed to download source PDF from S3: {exc}") from exc
    if not target.exists() or target.stat().st_size == 0:
        raise StorageError("Downloaded source PDF is empty.")


def _create_sheet_rows(
    session: Session, drawing: Drawing, meta: pdf_mod.PdfMetadata, _settings
) -> list[Sheet]:
    rows: list[Sheet] = []
    for idx, size in enumerate(meta.page_sizes, start=1):
        sheet = Sheet(
            drawing_id=drawing.id,
            page_number=idx,
            page_width_pts=size.width_pts,
            page_height_pts=size.height_pts,
            status=IngestStatus.QUEUED.value,
            progress_percent=0,
        )
        session.add(sheet)
        rows.append(sheet)
    session.flush()
    return rows


def _ingest_tiles(
    session: Session,
    drawing: Drawing,
    sheet: Sheet,
    image,
    settings,
    *,
    overall_start: int,
    overall_end: int,
    reporter: ProgressReporter,
    page_num: int,
    total_pages: int,
) -> int:
    """Stream tiles from the pyramid into S3 + insert Tile rows. Returns max_zoom."""
    max_zoom_seen = 0
    tile_count_flush = 0
    last_update_pct = overall_start

    for tile in tiles_mod.generate_tiles(
        image,
        tile_size=settings.tile_size,
        overlap=settings.tile_overlap,
        max_zoom_cap=settings.max_zoom_levels,
        webp_quality=settings.tile_webp_quality,
    ):
        max_zoom_seen = max(max_zoom_seen, tile.zoom)
        key = s3_mod.tile_key(
            str(drawing.id), str(sheet.id), tile.zoom, tile.col, tile.row
        )
        _upload_bytes(tile.content, key, content_type=tile.content_type)

        session.add(
            Tile(
                sheet_id=sheet.id,
                zoom_level=tile.zoom,
                col=tile.col,
                row=tile.row,
                s3_key=key,
                size_bytes=len(tile.content),
                content_type=tile.content_type,
            )
        )
        tile_count_flush += 1

        # Flush rows periodically so a WS client polling the DB sees
        # partial progress, and so we don't hold thousands of pending
        # INSERTs in memory.
        if tile_count_flush >= 64:
            session.flush()
            tile_count_flush = 0

        # Throttle progress updates to every ~2 percentage points so
        # we don't hammer Redis for thousands of trivial deltas.
        approx_pct = overall_start + int(
            (overall_end - overall_start) * (tile.zoom / max(1, settings.max_zoom_levels))
        )
        if approx_pct - last_update_pct >= 2:
            last_update_pct = approx_pct
            reporter.sheet(
                sheet,
                status=IngestStatus.TILING,
                percent=min(99, int(100 * tile.zoom / max(1, settings.max_zoom_levels))),
                overall_percent=approx_pct,
                overall_message=(
                    f"Generating tiles for page {page_num} of {total_pages}"
                    f" (zoom {tile.zoom})…"
                ),
            )
            session.commit()

    session.flush()
    return max_zoom_seen


def _upload_bytes(body: bytes, key: str, *, content_type: str) -> None:
    try:
        s3_mod.get_s3_client().put_object(
            Bucket=get_settings().s3_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )
    except Exception as exc:
        raise StorageError(f"Failed to upload {key}: {exc}") from exc
