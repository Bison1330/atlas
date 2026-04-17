"""Extraction-trigger business logic.

The route layer keeps to HTTP concerns; this module owns:

- Streaming the DXF upload through a bounded hasher onto disk.
- Putting the source DXF into S3 under the per-extraction prefix.
- Creating the ``element_sources`` row in ``queued`` state.
- Enqueueing the worker job.
- Publishing the initial ``extraction.queued`` event so the WS sees
  the run from the moment the API accepts it.
- Best-effort rollback when any step fails (S3 cleanup, DB rollback).

Mirrors the M1 ``services/drawings.py`` shape so the two pipelines
stay easy to compare.
"""

from __future__ import annotations

import hashlib
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from atlas_db import Drawing, ElementSource, Sheet
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import events
from app.core.config import get_settings
from app.core.queue import enqueue_extraction
from app.core.s3 import extraction_source_key, get_s3_client
from app.schemas.errors import (
    InvalidFileError,
    MissingFileError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceError,
)

log = structlog.get_logger("atlas.services.extractions")

_CHUNK = 1024 * 1024  # 1 MiB
_DXF_MAX_BYTES = 100 * 1024 * 1024  # 100 MiB cap — DXFs rarely exceed this
# DXF doesn't have a single magic header — both ASCII and binary DXFs exist.
# ASCII starts with ``  0\nSECTION\n`` (the leading whitespace is intentional);
# binary DXF starts with ``AutoCAD Binary DXF\r\n\x1a\x00``. We sniff cheaply
# and fall back to "not a DXF" when neither matches.
_BINARY_DXF_MAGIC = b"AutoCAD Binary DXF"


async def create_extraction_from_upload(
    db: Session,
    drawing_id: UUID,
    upload: UploadFile,
) -> ElementSource:
    """Validate + store a DXF and queue an extraction run.

    Raises typed errors for every user-visible failure mode; service
    errors (S3 down, queue down) bubble as ``ServiceError`` (5xx).
    """
    if upload is None or not upload.filename:
        raise MissingFileError()

    if not upload.filename.lower().endswith(".dxf"):
        raise InvalidFileError("Atlas accepts .dxf files for extraction in M2.")

    drawing = _require_drawing_with_sheet(db, drawing_id)

    tmp_path, _content_hash, size_bytes = await _stream_dxf(upload)

    source_id = uuid4()
    s3_key = extraction_source_key(str(drawing_id), str(source_id))

    try:
        _put_dxf(tmp_path, s3_key)

        source = ElementSource(
            id=source_id,
            drawing_id=drawing.id,
            source_kind="extraction",
            producer_name="dxf_ncs_extractor",
            producer_version="0.1.0",
            status="queued",
            params={
                "dxf_s3_key": s3_key,
                "dxf_size_bytes": size_bytes,
                "dxf_filename": upload.filename,
            },
        )
        db.add(source)
        db.flush()

        try:
            enqueue_extraction(str(source_id))
        except Exception as exc:
            db.rollback()
            _best_effort_delete(s3_key)
            log.exception(
                "extraction.enqueue_failed", source_id=str(source_id)
            )
            raise ServiceError.queue_unavailable() from exc

        db.commit()
        db.refresh(source)

        events.publish(
            drawing.id,
            {
                "type": "extraction.queued",
                "drawing_id": str(drawing.id),
                "source_id": str(source.id),
                "filename": upload.filename,
                "size_bytes": size_bytes,
                "at": datetime.now(UTC).isoformat(),
            },
        )

        log.info(
            "extraction.queued",
            drawing_id=str(drawing.id),
            source_id=str(source.id),
            size_bytes=size_bytes,
        )
        return source
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            log.warning("tempfile_cleanup_failed", path=str(tmp_path))


def list_extractions(db: Session, drawing_id: UUID) -> list[ElementSource]:
    """Newest-first list of extraction runs for a drawing."""
    rows = db.execute(
        select(ElementSource)
        .where(ElementSource.drawing_id == drawing_id)
        .order_by(ElementSource.created_at.desc())
    ).scalars().all()
    return list(rows)


# ---------- helpers ----------


def _require_drawing_with_sheet(db: Session, drawing_id: UUID) -> Drawing:
    drawing = db.execute(
        select(Drawing).where(Drawing.id == drawing_id)
    ).scalar_one_or_none()
    if drawing is None:
        raise NotFoundError("Drawing", str(drawing_id))
    has_sheet = db.execute(
        select(Sheet.id).where(Sheet.drawing_id == drawing_id).limit(1)
    ).scalar_one_or_none()
    if has_sheet is None:
        raise InvalidFileError(
            "Drawing has no sheets to attach elements to. "
            "Wait for ingest to complete before triggering extraction."
        )
    return drawing


async def _stream_dxf(upload: UploadFile) -> tuple[Path, str, int]:
    hasher = hashlib.sha256()
    total = 0
    first_chunk: bytes | None = None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".dxf")
    try:
        while True:
            chunk = await upload.read(_CHUNK)
            if not chunk:
                break
            if first_chunk is None:
                first_chunk = chunk[:64]
            total += len(chunk)
            if total > _DXF_MAX_BYTES:
                raise PayloadTooLargeError(
                    max_bytes=_DXF_MAX_BYTES, received_bytes=total
                )
            hasher.update(chunk)
            tmp.write(chunk)
    finally:
        tmp.close()

    if total == 0:
        Path(tmp.name).unlink(missing_ok=True)
        raise InvalidFileError("file is empty")

    if not _looks_like_dxf(first_chunk or b""):
        Path(tmp.name).unlink(missing_ok=True)
        raise InvalidFileError("file does not look like a DXF (header sniff failed)")

    return Path(tmp.name), hasher.hexdigest(), total


def _looks_like_dxf(head: bytes) -> bool:
    """Cheap sniff for ASCII or binary DXF.

    ASCII DXFs start with the SECTION group code: ``0`` on its own line
    (often with leading whitespace), then ``SECTION``. Binary DXFs lead
    with the literal "AutoCAD Binary DXF" sentinel.
    """
    if head.startswith(_BINARY_DXF_MAGIC):
        return True
    text = head.decode("ascii", errors="ignore")
    stripped = text.lstrip()
    if stripped.startswith("0") and "SECTION" in stripped[:64]:
        return True
    return False


def _put_dxf(path: Path, s3_key: str) -> None:
    client = get_s3_client()
    bucket = get_settings().s3_bucket
    try:
        client.upload_file(
            str(path),
            bucket,
            s3_key,
            ExtraArgs={"ContentType": "application/dxf"},
        )
    except Exception as exc:
        log.exception("s3_put_failed", bucket=bucket, key=s3_key)
        raise ServiceError.storage_unavailable() from exc


def _best_effort_delete(s3_key: str) -> None:
    try:
        get_s3_client().delete_object(
            Bucket=get_settings().s3_bucket, Key=s3_key
        )
    except Exception:
        log.warning("s3_best_effort_delete_failed", key=s3_key)
