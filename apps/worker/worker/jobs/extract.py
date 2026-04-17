"""Element-extraction orchestrator.

Composes the Phase 2 reader + validators + Phase 3 DXF reader and
persists the result as ``Element`` rows under a new ``ElementSource``.
Phase 3 ships the function-shaped entrypoint; Phase 4 will wrap it
in an RQ job and wire it to the upload flow for non-PDF formats.

Lifecycle of a single run:

1. Insert ``ElementSource`` row with ``status=running``, publish
   ``extraction.started`` event.
2. Read the DXF — get a list of candidates plus a summary.
3. For each candidate, build the ``Element`` row attached to the
   chosen sheet + source. Periodically publish progress events so a
   future WS subscriber sees the stream as it lands.
4. On success, mark the source ``completed``, store the layer/skip
   summary in ``ElementSource.summary``, publish
   ``extraction.completed``. Return :class:`ExtractionRunSummary`.
5. On any exception, mark the source ``failed`` with the error
   code/message, publish ``extraction.failed``, and re-raise so the
   caller (or RQ) sees the original traceback.

Event payloads on Redis (channel ``atlas:drawing:{id}:events``):

    {"type": "extraction.started",   "drawing_id": ..., "source_id": ...}
    {"type": "extraction.progress",  "drawing_id": ..., "source_id": ...,
                                      "elements_so_far": N}
    {"type": "extraction.completed", "drawing_id": ..., "source_id": ...,
                                      "summary": {...}}
    {"type": "extraction.failed",    "drawing_id": ..., "source_id": ...,
                                      "error_code": ..., "error_message": ...}
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import structlog
from atlas_db import Element, ElementSource, Sheet
from sqlalchemy import select
from sqlalchemy.orm import Session

from worker import events
from worker.extractors import dxf

log = structlog.get_logger("atlas.worker.jobs.extract")

PRODUCER_NAME = "dxf_ncs_extractor"
PRODUCER_VERSION = "0.1.0"
PROGRESS_EVERY = 25  # publish a progress event every N elements


@dataclass(slots=True)
class ExtractionRunSummary:
    """Returned by :func:`extract_from_dxf` on success."""

    source_id: UUID
    elements_written: int
    elements_by_kind: dict[str, int] = field(default_factory=dict)
    duration_seconds: float = 0.0
    layer_counts: dict[str, int] = field(default_factory=dict)
    skipped_entity_types: dict[str, int] = field(default_factory=dict)


def extract_from_dxf(
    session: Session,
    drawing_id: UUID,
    dxf_path: Path,
    *,
    source_id: UUID | None = None,
    sheet_id: UUID | None = None,
    producer_version: str = PRODUCER_VERSION,
) -> ExtractionRunSummary:
    """Run the DXF extractor against a drawing.

    The caller owns the SQLAlchemy session; we commit at meaningful
    boundaries so a partial run leaves a coherent ``ElementSource``
    in the DB even if the host process crashes.

    ``source_id`` selects between two modes:

    - **None (standalone path).** The orchestrator inserts a fresh
      ``ElementSource`` row in ``running`` state and runs to
      completion. Used by direct callers and the existing test
      fixtures.
    - **Provided (RQ path).** The API has already created the source
      in ``queued`` state and enqueued this job. The orchestrator
      transitions it to ``running`` and proceeds. The source row's
      ``params`` typically already records the DXF's S3 key + size.

    ``sheet_id`` selects which sheet to attach elements to. If None,
    the drawing's first (lowest ``page_number``) sheet is used —
    this matches the common case where a DXF represents one sheet.
    """
    started = time.monotonic()
    sheet_uuid = _resolve_sheet_id(session, drawing_id, sheet_id)

    if source_id is None:
        source = ElementSource(
            drawing_id=drawing_id,
            source_kind="extraction",
            producer_name=PRODUCER_NAME,
            producer_version=producer_version,
            status="running",
            started_at=datetime.now(UTC),
            params={"dxf_path": str(dxf_path)},
        )
        session.add(source)
        session.commit()
        session.refresh(source)
    else:
        source = session.get(ElementSource, source_id)
        if source is None:
            raise ValueError(f"ElementSource {source_id} not found")
        if source.drawing_id != drawing_id:
            raise ValueError(
                f"ElementSource {source_id} belongs to a different drawing"
            )
        source.status = "running"
        source.started_at = datetime.now(UTC)
        session.add(source)
        session.commit()
        session.refresh(source)

    events.publish(
        drawing_id,
        {
            "type": "extraction.started",
            "drawing_id": str(drawing_id),
            "source_id": str(source.id),
            "producer": f"{PRODUCER_NAME}@{producer_version}",
        },
    )
    log.info(
        "extract.started",
        drawing_id=str(drawing_id),
        source_id=str(source.id),
        dxf_path=str(dxf_path),
    )

    try:
        read_summary = dxf.read_dxf(dxf_path)
        kind_counts: dict[str, int] = {}
        elements_written = 0

        for candidate in read_summary.candidates:
            session.add(_candidate_to_element(candidate, sheet_uuid, source.id))
            kind_counts[candidate.kind.value] = kind_counts.get(candidate.kind.value, 0) + 1
            elements_written += 1

            if elements_written % PROGRESS_EVERY == 0:
                session.flush()
                events.publish(
                    drawing_id,
                    {
                        "type": "extraction.progress",
                        "drawing_id": str(drawing_id),
                        "source_id": str(source.id),
                        "elements_so_far": elements_written,
                    },
                )

        # Final flush + finalize.
        session.flush()
        source.status = "completed"
        source.finished_at = datetime.now(UTC)
        source.summary = {
            "elements_written": elements_written,
            "elements_by_kind": kind_counts,
            "layer_counts": read_summary.layer_counts,
            "skipped_entity_types": read_summary.skipped_entity_types,
            "skipped_unknown_layers": read_summary.skipped_unknown_layers,
        }
        session.add(source)
        session.commit()

        duration = round(time.monotonic() - started, 3)
        events.publish(
            drawing_id,
            {
                "type": "extraction.completed",
                "drawing_id": str(drawing_id),
                "source_id": str(source.id),
                "summary": source.summary,
                "duration_seconds": duration,
            },
        )
        log.info(
            "extract.completed",
            drawing_id=str(drawing_id),
            source_id=str(source.id),
            elements=elements_written,
            duration_seconds=duration,
        )

        return ExtractionRunSummary(
            source_id=source.id,
            elements_written=elements_written,
            elements_by_kind=kind_counts,
            duration_seconds=duration,
            layer_counts=read_summary.layer_counts,
            skipped_entity_types=read_summary.skipped_entity_types,
        )

    except Exception as exc:
        # Roll back any pending element inserts so the source row is
        # the only thing that lands; mark it failed in a fresh tx.
        session.rollback()
        source = session.get(ElementSource, source.id)
        if source is not None:
            source.status = "failed"
            source.error_code = type(exc).__name__
            source.error_message = str(exc)[:2048]
            source.finished_at = datetime.now(UTC)
            session.commit()
            events.publish(
                drawing_id,
                {
                    "type": "extraction.failed",
                    "drawing_id": str(drawing_id),
                    "source_id": str(source.id),
                    "error_code": source.error_code,
                    "error_message": source.error_message,
                },
            )
        log.exception(
            "extract.failed",
            drawing_id=str(drawing_id),
            source_id=str(source.id) if source else None,
        )
        raise


def _resolve_sheet_id(
    session: Session, drawing_id: UUID, sheet_id: UUID | None
) -> UUID:
    if sheet_id is not None:
        return sheet_id
    sheet = session.execute(
        select(Sheet)
        .where(Sheet.drawing_id == drawing_id)
        .order_by(Sheet.page_number.asc())
        .limit(1)
    ).scalar_one_or_none()
    if sheet is None:
        raise ValueError(
            f"Drawing {drawing_id} has no sheets; cannot attach elements"
        )
    return sheet.id


def _candidate_to_element(
    candidate: dxf.ElementCandidate,
    sheet_id: UUID,
    source_id: UUID,
) -> Element:
    return Element(
        sheet_id=sheet_id,
        source_id=source_id,
        kind=candidate.kind.value,
        confidence=candidate.confidence,
        source_layer=candidate.source_layer,
        ncs_layer=candidate.ncs_layer,
        ncs_major_group=candidate.ncs_major_group,
        ncs_minor_group=candidate.ncs_minor_group,
        ifc_type=candidate.ifc_type,
        ifc_properties=candidate.ifc_properties,
        geometry=candidate.geometry,
        bbox=candidate.bbox,
        attrs=candidate.attrs,
    )


def candidates_to_elements(
    candidates: Iterable[dxf.ElementCandidate],
    sheet_id: UUID,
    source_id: UUID,
) -> list[Element]:
    """Helper: bulk convert candidates → Element rows. Used by tests."""
    return [_candidate_to_element(c, sheet_id, source_id) for c in candidates]


# ---------- RQ entrypoint ----------


def run_dxf_extraction(source_id_str: str) -> None:
    """RQ entrypoint: download the queued DXF from S3 and run the orchestrator.

    The API is responsible for:

    1. Uploading the DXF to S3 under
       ``drawings/{drawing_id}/extractions/{source_id}/source.dxf``.
    2. Inserting an ``ElementSource`` row in ``queued`` state with
       ``params = {"dxf_s3_key": "...", "dxf_size_bytes": ...}``.
    3. Enqueuing this job with the source_id as a string (RQ
       serializes args via pickle but UUID-typed args have hit
       compatibility quirks across versions; strings are safer).

    On any error before extraction begins (S3 download fails, source
    row missing) we mark the source ``failed`` and emit
    ``extraction.failed`` so listeners aren't left hanging. Errors
    *during* extraction are handled by ``extract_from_dxf``.
    """
    # Local imports avoid a cycle when extract.py is imported at
    # worker module load (s3.py already pulls config which pulls env).
    import tempfile

    from worker import s3 as s3_mod
    from worker.config import get_settings
    from worker.db import session_scope

    source_id = UUID(source_id_str)
    log.info("extract.rq.start", source_id=source_id_str)

    with session_scope() as session:
        source = session.get(ElementSource, source_id)
        if source is None:
            raise RuntimeError(f"ElementSource {source_id} not found")

        drawing_id = source.drawing_id
        params = dict(source.params or {})
        dxf_s3_key = params.get("dxf_s3_key")
        if not dxf_s3_key:
            _fail_source(
                session,
                source,
                drawing_id,
                code="missing_s3_key",
                message="ElementSource.params.dxf_s3_key is missing",
            )
            raise RuntimeError(f"ElementSource {source_id} has no dxf_s3_key")

        with tempfile.TemporaryDirectory(prefix="atlas-extract-") as workdir:
            local_path = Path(workdir) / "source.dxf"
            try:
                s3_mod.get_s3_client().download_file(
                    get_settings().s3_bucket,
                    dxf_s3_key,
                    str(local_path),
                )
            except Exception as exc:
                _fail_source(
                    session,
                    source,
                    drawing_id,
                    code="s3_download_failed",
                    message=str(exc),
                )
                raise

            # Hand off to the existing orchestrator which transitions
            # queued → running and handles its own failure mode.
            extract_from_dxf(
                session,
                drawing_id,
                local_path,
                source_id=source_id,
            )


def _fail_source(
    session: Session,
    source: ElementSource,
    drawing_id: UUID,
    *,
    code: str,
    message: str,
) -> None:
    """Mark a source failed before the orchestrator runs (e.g. S3 missing).

    Mirrors the orchestrator's failure path so the API/WS see the
    same event shape regardless of where in the pipeline it died.
    """
    source.status = "failed"
    source.error_code = code
    source.error_message = message[:2048]
    source.finished_at = datetime.now(UTC)
    session.add(source)
    session.commit()
    events.publish(
        drawing_id,
        {
            "type": "extraction.failed",
            "drawing_id": str(drawing_id),
            "source_id": str(source.id),
            "error_code": code,
            "error_message": source.error_message,
        },
    )
    log.error(
        "extract.rq.failed_pre_orchestrator",
        source_id=str(source.id),
        code=code,
        message=message,
    )
