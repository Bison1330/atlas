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


# ---------------------------------------------------------------------------
# M2 — structured drawings
# ---------------------------------------------------------------------------
#
# Decisions captured in /opt/atlas/docs/research/decisions.md:
#   D-01: polymorphic ``elements`` table with kind + JSONB attrs.
#   D-02: JSONB geometry; PostGIS deferred to M3.
#   D-05: ``element_sources`` carries provenance + lifecycle for each
#         extraction/generation/manual-override run.
#   D-06: source_kind discriminator generalizes "extraction" to cover
#         generated and human-authored elements too.

_ELEMENT_SOURCE_KINDS = ("extraction", "generation", "manual_override")
_ELEMENT_SOURCE_STATUSES = ("queued", "running", "completed", "failed")
_ELEMENT_KINDS = (
    "room",
    "wall",
    "door",
    "window",
    "column",
    "stair",
    "dimension",
    "annotation",
    "symbol",
    "other",
)


class ElementSource(TimestampMixin, Base):
    """One run of an element-producing pipeline against a drawing.

    Every Element FKs to exactly one ElementSource. Re-running an
    extractor inserts a new source + new elements; older ones stay
    queryable so we can diff runs and compare extractor versions.
    """

    __tablename__ = "element_sources"
    __table_args__ = (
        CheckConstraint(
            f"source_kind IN {_ELEMENT_SOURCE_KINDS}",
            name="ck_element_sources_kind_valid",
        ),
        CheckConstraint(
            f"status IN {_ELEMENT_SOURCE_STATUSES}",
            name="ck_element_sources_status_valid",
        ),
        Index("ix_element_sources_drawing_id", "drawing_id"),
        Index("ix_element_sources_status", "status"),
        Index(
            "ix_element_sources_drawing_finished",
            "drawing_id",
            "finished_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    drawing_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("drawings.id", ondelete="CASCADE"),
        nullable=False,
    )

    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    producer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    producer_version: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Free-form JSONB so producers can record their config + output stats
    # without us having to ALTER TABLE every time a new extractor adds a
    # tunable.
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    drawing: Mapped[Drawing] = relationship()
    elements: Mapped[list[Element]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Element(TimestampMixin, Base):
    """A polymorphic structured-drawing element.

    See module-level note for the design rationale. Kind-specific
    fields live in ``attrs`` JSONB (e.g. wall.thickness,
    door.swing_angle_deg) — the canonical shape per kind is the
    matching atlas_core Pydantic model.
    """

    __tablename__ = "elements"
    __table_args__ = (
        CheckConstraint(
            f"kind IN {_ELEMENT_KINDS}",
            name="ck_elements_kind_valid",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_elements_confidence_range",
        ),
        Index("ix_elements_sheet_id", "sheet_id"),
        Index("ix_elements_source_id", "source_id"),
        Index("ix_elements_sheet_kind", "sheet_id", "kind"),
        Index("ix_elements_ncs_major_group", "ncs_major_group"),
        Index("ix_elements_host_element_id", "host_element_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    sheet_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("sheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("element_sources.id", ondelete="CASCADE"),
        nullable=False,
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)

    # Display + identity attributes used across kinds.
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Provenance: confidence is NULL when the producer is deterministic
    # or human (vs. a probabilistic extractor).
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    source_layer: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # NCS classification (US National CAD Standard) — first-class so we
    # can index ``WHERE ncs_major_group = 'WALL'`` without parsing JSONB.
    ncs_layer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ncs_major_group: Mapped[str | None] = mapped_column(String(4), nullable=True)
    ncs_minor_group: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # IFC compatibility — uniform property-set surface across all kinds.
    ifc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ifc_properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Geometry + spatial summary. Both are JSONB per D-02; PostGIS
    # migration deferred to M3.
    geometry: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Kind-specific bag (wall.thickness, door.swing_angle_deg, …).
    attrs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Hosting relationship: doors and windows reference their parent wall.
    host_element_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("elements.id", ondelete="SET NULL"),
        nullable=True,
    )

    sheet: Mapped[Sheet] = relationship()
    source: Mapped[ElementSource] = relationship(back_populates="elements")
    host: Mapped[Element | None] = relationship(
        remote_side="Element.id", foreign_keys=[host_element_id]
    )


class Annotation(TimestampMixin, Base):
    """User-authored note attached to a single extracted element (M6).

    Intentionally narrow in v1:

    - One note per target element (no threading; add a ``parent_id``
      self-FK when that ships).
    - No ``author_id`` — Atlas has no auth yet, so ``author_name`` is a
      free-form string the client supplies. An M7 auth migration will
      add the FK and either demote or drop this column.
    - No ``source_id``. Annotations attach to ``element_id`` directly;
      re-extraction creates a new source with new element IDs, and
      old annotations stay pointing at the old run's elements. See
      D-10 in ``docs/research/m6-annotations.md``.

    FK policy:

    - ``drawing_id`` cascades (deleting a drawing removes every
      annotation scoped to it).
    - ``element_id`` restricts — deleting an element under an
      annotation is a schema invariant violation surfaced loudly
      rather than silent data loss. Under the immutable-source
      model this should never happen in practice.
    """

    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint(
            "char_length(author_name) BETWEEN 1 AND 120",
            name="ck_annotations_author_name_len",
        ),
        CheckConstraint(
            "char_length(body) BETWEEN 1 AND 4000",
            name="ck_annotations_body_len",
        ),
        Index(
            "ix_annotations_drawing_created",
            "drawing_id", "created_at",
        ),
        Index("ix_annotations_element_id", "element_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4,
    )
    drawing_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("drawings.id", ondelete="CASCADE"),
        nullable=False,
    )
    element_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("elements.id", ondelete="RESTRICT"),
        nullable=False,
    )
    author_name: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(String(4000), nullable=False)

    drawing: Mapped[Drawing] = relationship()
    element: Mapped[Element] = relationship()
