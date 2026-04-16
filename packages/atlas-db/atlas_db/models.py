"""Ingest-pipeline ORM models: Drawing, Sheet, Tile.

Invariants worth noting up front:

- A ``Drawing`` is a single uploaded PDF. ``(content_hash)`` is indexed to
  support dedup lookups before starting a new pipeline run.
- A ``Sheet`` is a single page. Uniqueness on
  ``(drawing_id, page_number)`` prevents accidental double-rasterization.
- A ``Tile`` is a single image tile at a specific zoom level. Uniqueness
  on ``(sheet_id, zoom_level, col, row)`` is the natural coordinate key.
- ``status`` columns are stored as strings with a CHECK constraint rather
  than a Postgres ENUM — adding a new state needs a trivial migration
  instead of ``ALTER TYPE``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atlas_db.base import Base, TimestampMixin

_INGEST_STATUSES = ("queued", "validating", "rasterizing", "tiling", "completed", "failed")


class Drawing(TimestampMixin, Base):
    """One uploaded PDF and its top-level pipeline state."""

    __tablename__ = "drawings"
    __table_args__ = (
        CheckConstraint(
            f"status IN {_INGEST_STATUSES}",
            name="ck_drawings_status_valid",
        ),
        CheckConstraint(
            "progress_percent BETWEEN 0 AND 100",
            name="ck_drawings_progress_range",
        ),
        Index("ix_drawings_status", "status"),
        Index("ix_drawings_created_at_desc", "created_at", postgresql_using="btree"),
        Index("ix_drawings_content_hash", "content_hash"),
        Index("ix_drawings_project_name", "project_name"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)

    project_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    progress_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    extra: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    sheets: Mapped[list[Sheet]] = relationship(
        back_populates="drawing",
        cascade="all, delete-orphan",
        order_by="Sheet.page_number",
        passive_deletes=True,
    )


class Sheet(TimestampMixin, Base):
    """One page within a drawing plus its per-sheet processing state."""

    __tablename__ = "sheets"
    __table_args__ = (
        UniqueConstraint("drawing_id", "page_number", name="uq_sheets_drawing_page"),
        CheckConstraint(
            f"status IN {_INGEST_STATUSES}",
            name="ck_sheets_status_valid",
        ),
        CheckConstraint(
            "progress_percent BETWEEN 0 AND 100",
            name="ck_sheets_progress_range",
        ),
        CheckConstraint("page_number >= 1", name="ck_sheets_page_number_positive"),
        Index("ix_sheets_status", "status"),
        Index("ix_sheets_drawing_id", "drawing_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    drawing_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("drawings.id", ondelete="CASCADE"),
        nullable=False,
    )

    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sheet_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    discipline: Mapped[str | None] = mapped_column(String(1), nullable=True)

    width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dpi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_width_pts: Mapped[float | None] = mapped_column(nullable=True)
    page_height_pts: Mapped[float | None] = mapped_column(nullable=True)

    tile_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_zoom: Mapped[int | None] = mapped_column(Integer, nullable=True)

    preview_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    extra: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    drawing: Mapped[Drawing] = relationship(back_populates="sheets")
    tiles: Mapped[list[Tile]] = relationship(
        back_populates="sheet",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Tile(Base):
    """A single image tile at a specific (zoom, col, row) in a sheet."""

    __tablename__ = "tiles"
    __table_args__ = (
        UniqueConstraint(
            "sheet_id", "zoom_level", "col", "row", name="uq_tiles_coord"
        ),
        CheckConstraint("zoom_level >= 0", name="ck_tiles_zoom_nonneg"),
        CheckConstraint("col >= 0 AND row >= 0", name="ck_tiles_coord_nonneg"),
        Index("ix_tiles_sheet_zoom", "sheet_id", "zoom_level"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    sheet_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("sheets.id", ondelete="CASCADE"),
        nullable=False,
    )

    zoom_level: Mapped[int] = mapped_column(Integer, nullable=False)
    col: Mapped[int] = mapped_column(Integer, nullable=False)
    row: Mapped[int] = mapped_column(Integer, nullable=False)

    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="image/webp", server_default="image/webp"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sheet: Mapped[Sheet] = relationship(back_populates="tiles")
