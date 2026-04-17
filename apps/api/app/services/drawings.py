"""Drawing-ingest business logic.

The REST routes keep to HTTP concerns (validation, status codes, headers)
and delegate the actual work here. This module owns:

- Streaming uploads through a bounded hasher onto disk
- Putting the source PDF into S3
- Creating the ``drawings`` row and enqueueing the ingest job
- Rolling back (best effort) when any step fails
- Mapping ORM rows to the shared ``DrawingSummary`` response model
"""

from __future__ import annotations

import hashlib
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog
from atlas_core import DrawingSummary, IngestStatus, IngestStatusEvent, SheetSummary
from fastapi import UploadFile
from sqlalchemy.orm import Session, selectinload

from app.core import events
from app.core.config import get_settings
from app.core.queue import enqueue_ingest
from app.core.s3 import drawing_source_key, get_s3_client
from app.db import Drawing, Sheet
from app.schemas.errors import (
    InvalidFileError,
    MissingFileError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceError,
    UnsupportedMediaTypeError,
)

if TYPE_CHECKING:
    from sqlalchemy import Select

log = structlog.get_logger("atlas.services.drawings")

# Size we read per chunk while hashing / streaming the upload onto disk.
_CHUNK = 1024 * 1024  # 1 MiB
# PDF magic bytes — sniffed from the first few bytes of the upload so we
# can reject renamed text files even if their MIME type says PDF.
_PDF_MAGIC = b"%PDF-"


async def create_drawing_from_upload(
    db: Session,
    upload: UploadFile,
    *,
    project_name: str | None = None,
    owner_id: UUID | None = None,
) -> Drawing:
    """Validate + store an uploaded PDF and create the Drawing row.

    Raises one of the typed APIErrors from ``app.schemas.errors`` for
    every user-facing failure mode. Internal errors (S3 down, DB down,
    queue down) bubble as ``ServiceError`` with a 5xx status.
    """
    settings = get_settings()

    if upload is None or not upload.filename:
        raise MissingFileError()

    content_type = (upload.content_type or "").lower()
    allowed = settings.allowed_mime_set
    if content_type not in allowed:
        raise UnsupportedMediaTypeError(received=content_type, allowed=sorted(allowed))

    tmp_path, content_hash, size_bytes = await _stream_to_tempfile(
        upload, max_bytes=settings.max_upload_bytes
    )

    try:
        drawing_id = uuid4()
        s3_key = drawing_source_key(str(drawing_id))

        _put_pdf(tmp_path, s3_key)

        drawing = Drawing(
            id=drawing_id,
            owner_id=owner_id,
            project_name=project_name,
            source_filename=upload.filename,
            source_s3_key=s3_key,
            size_bytes=size_bytes,
            content_hash=f"sha256:{content_hash}",
            status=IngestStatus.QUEUED.value,
            progress_percent=0,
            progress_message="Queued for ingest",
        )
        db.add(drawing)
        db.flush()  # populate defaults / created_at before we publish

        try:
            enqueue_ingest(str(drawing_id))
        except Exception as exc:
            db.rollback()
            _best_effort_delete(s3_key)
            log.exception("enqueue_failed", drawing_id=str(drawing_id))
            raise ServiceError.queue_unavailable() from exc

        db.commit()
        db.refresh(drawing)

        events.publish(
            drawing.id,
            IngestStatusEvent(
                drawing_id=drawing.id,
                status=IngestStatus.QUEUED,
                progress_percent=0,
                message="Queued for ingest",
                at=datetime.now(UTC),
            ).model_dump(mode="json"),
        )

        log.info(
            "drawing.created",
            drawing_id=str(drawing.id),
            size_bytes=size_bytes,
            content_hash=content_hash[:16],
            filename=upload.filename,
        )
        return drawing
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            log.warning("tempfile_cleanup_failed", path=str(tmp_path))


async def _stream_to_tempfile(
    upload: UploadFile, *, max_bytes: int
) -> tuple[Path, str, int]:
    """Read the upload into a temp file while hashing and size-checking.

    Returns (tempfile_path, sha256_hex, total_bytes). Raises ``PayloadTooLargeError``
    as soon as the cumulative size exceeds ``max_bytes`` so we don't keep
    reading a hostile oversized upload. Raises ``InvalidFileError`` when
    the content doesn't look like a PDF.
    """
    hasher = hashlib.sha256()
    total = 0
    first_chunk: bytes | None = None

    # delete=False — we're responsible for unlinking. suffix helps S3
    # debugging if we ever inspect the tempfile on disk.
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    try:
        while True:
            chunk = await upload.read(_CHUNK)
            if not chunk:
                break
            if first_chunk is None:
                first_chunk = chunk[:8]
            total += len(chunk)
            if total > max_bytes:
                raise PayloadTooLargeError(max_bytes=max_bytes, received_bytes=total)
            hasher.update(chunk)
            tmp.write(chunk)
    finally:
        tmp.close()

    if total == 0:
        Path(tmp.name).unlink(missing_ok=True)
        raise InvalidFileError("file is empty")

    if first_chunk is None or not first_chunk.startswith(_PDF_MAGIC):
        Path(tmp.name).unlink(missing_ok=True)
        raise InvalidFileError(
            "file does not start with the PDF magic number (%PDF-)"
        )

    return Path(tmp.name), hasher.hexdigest(), total


def _put_pdf(path: Path, s3_key: str) -> None:
    client = get_s3_client()
    bucket = get_settings().s3_bucket
    try:
        client.upload_file(
            str(path),
            bucket,
            s3_key,
            ExtraArgs={"ContentType": "application/pdf"},
        )
    except Exception as exc:
        log.exception("s3_put_failed", bucket=bucket, key=s3_key)
        raise ServiceError.storage_unavailable() from exc


def _best_effort_delete(s3_key: str) -> None:
    try:
        get_s3_client().delete_object(Bucket=get_settings().s3_bucket, Key=s3_key)
    except Exception:
        log.warning("s3_best_effort_delete_failed", key=s3_key)


# ---------- reads ----------


def get_drawing(db: Session, drawing_id: UUID, *, with_sheets: bool = False) -> Drawing:
    q: Select = _select_drawing(with_sheets=with_sheets).where(Drawing.id == drawing_id)
    drawing = db.execute(q).scalars().one_or_none()
    if drawing is None:
        raise NotFoundError("Drawing", str(drawing_id))
    return drawing


def list_readable_drawings(
    db: Session, user_id: UUID, *, limit: int = 100,
) -> list[Drawing]:
    """Drawings the caller can read — owner OR project-member OR unclaimed.

    Mirrors the per-drawing ``drawing_readable_by`` predicate in
    :mod:`app.services.auth` but as a single query. Ordered by
    ``created_at DESC``. Soft cap ``limit`` (default 100) so the
    response stays bounded without real pagination yet.

    The query plan:
    - owner_id = :user_id         (own drawings)
    - OR project_id IN (          (drawings in a project I'm in)
          SELECT project_id FROM project_members WHERE user_id = :user_id
        )
    - OR owner_id IS NULL         (legacy / unclaimed)
    """
    from sqlalchemy import or_, select

    from app.db import ProjectMember

    my_projects = (
        select(ProjectMember.project_id)
        .where(ProjectMember.user_id == user_id)
        .scalar_subquery()
    )

    stmt = (
        select(Drawing)
        .where(
            or_(
                Drawing.owner_id == user_id,
                Drawing.owner_id.is_(None),
                Drawing.project_id.in_(my_projects),
            )
        )
        .order_by(Drawing.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def _select_drawing(*, with_sheets: bool):
    from sqlalchemy import select

    stmt = select(Drawing)
    if with_sheets:
        stmt = stmt.options(selectinload(Drawing.sheets))
    return stmt


def drawing_to_summary(drawing: Drawing, *, include_sheets: bool = False) -> DrawingSummary:
    sheets: list[SheetSummary] = []
    if include_sheets:
        sheets = [_sheet_to_summary(s) for s in drawing.sheets]
    return DrawingSummary(
        id=drawing.id,
        project_name=drawing.project_name,
        source_filename=drawing.source_filename,
        size_bytes=drawing.size_bytes,
        content_hash=drawing.content_hash,
        page_count=drawing.page_count,
        status=IngestStatus(drawing.status),
        progress_percent=drawing.progress_percent,
        progress_message=drawing.progress_message,
        error_code=drawing.error_code,
        error_message=drawing.error_message,
        created_at=drawing.created_at,
        updated_at=drawing.updated_at,
        completed_at=drawing.completed_at,
        failed_at=drawing.failed_at,
        sheets=sheets,
    )


def _sheet_to_summary(sheet: Sheet) -> SheetSummary:
    from atlas_core import SheetDiscipline

    disc: SheetDiscipline | None = None
    if sheet.discipline:
        try:
            disc = SheetDiscipline(sheet.discipline)
        except ValueError:
            disc = None
    return SheetSummary(
        id=sheet.id,
        page_number=sheet.page_number,
        sheet_number=sheet.sheet_number,
        title=sheet.title,
        discipline=disc,
        width_px=sheet.width_px,
        height_px=sheet.height_px,
        dpi=sheet.dpi,
        tile_size=sheet.tile_size,
        max_zoom=sheet.max_zoom,
        preview_s3_key=sheet.preview_s3_key,
        status=IngestStatus(sheet.status),
        progress_percent=sheet.progress_percent,
        error_message=sheet.error_message,
        created_at=sheet.created_at,
        completed_at=sheet.completed_at,
    )
