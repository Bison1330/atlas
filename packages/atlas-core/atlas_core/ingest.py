"""Serialization models for ingest-pipeline API responses.

These mirror the shape of the rows in the ``drawings``, ``sheets``, and
``tiles`` tables — but carry only fields the frontend is meant to see.
They intentionally live in atlas-core (not in the API app) so that any
downstream consumer (worker, analyzer, CLI) can depend on the exact
same contract.

SQLAlchemy stays out of atlas-core. These are plain Pydantic v2 models.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from atlas_core.enums import IngestStatus, SheetDiscipline


class TileRef(BaseModel):
    """Everything the frontend needs to construct a tile URL.

    Tiles are addressed as (zoom_level, col, row) within a single sheet.
    ``s3_key`` is the authoritative location; the frontend typically hits
    a signed-URL endpoint rather than S3 directly.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    zoom_level: int = Field(ge=0)
    col: int = Field(ge=0)
    row: int = Field(ge=0)
    s3_key: str
    size_bytes: int | None = Field(default=None, ge=0)
    content_type: str = "image/webp"


class SheetSummary(BaseModel):
    """A single sheet within a drawing, as returned by the API."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    page_number: int = Field(ge=1)
    sheet_number: str | None = None
    title: str | None = None
    discipline: SheetDiscipline | None = None

    width_px: int | None = Field(default=None, ge=1)
    height_px: int | None = Field(default=None, ge=1)
    dpi: int | None = Field(default=None, ge=1)
    tile_size: int | None = Field(default=None, ge=1)
    max_zoom: int | None = Field(default=None, ge=0)

    preview_s3_key: str | None = None

    status: IngestStatus = IngestStatus.QUEUED
    progress_percent: int = Field(default=0, ge=0, le=100)
    error_message: str | None = None

    created_at: datetime
    completed_at: datetime | None = None


class DrawingSummary(BaseModel):
    """A drawing (an uploaded PDF) plus overall pipeline state."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    project_name: str | None = None
    source_filename: str
    size_bytes: int = Field(ge=0)
    content_hash: str

    page_count: int | None = Field(default=None, ge=0)

    status: IngestStatus = IngestStatus.QUEUED
    progress_percent: int = Field(default=0, ge=0, le=100)
    progress_message: str | None = None

    error_code: str | None = None
    error_message: str | None = None

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    failed_at: datetime | None = None

    sheets: list[SheetSummary] = Field(default_factory=list)


class IngestStatusEvent(BaseModel):
    """A single progress event pushed over the WebSocket channel.

    The API emits these whenever drawing or sheet state changes so that
    connected clients can re-render without polling.
    """

    model_config = ConfigDict(extra="forbid")

    drawing_id: UUID
    sheet_id: UUID | None = None
    status: IngestStatus
    progress_percent: int = Field(ge=0, le=100)
    message: str | None = None
    error_code: str | None = None
    at: datetime
