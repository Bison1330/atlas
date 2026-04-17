"""Top-level structured drawing models.

A `StructuredDrawing` is a set of `StructuredSheet`s — one per sheet in a
drawing package. Each sheet carries a list of typed `DrawingElement`s
(rooms, walls, doors, windows, etc.) along with their geometry.

These models are the canonical exchange format between the ingest
pipeline, the analyzers, and the API layer. Per the M2 research
findings (see ``docs/research/decisions.md``):

- **IFC compatibility.** Every element carries an optional IFC entity
  type (``ifc_type``, e.g. ``"IfcWallStandardCase"``) and a free-form
  ``ifc_properties`` mapping for IFC property sets like
  ``Pset_WallCommon``. We don't validate the inner shape of property
  sets — buildingSMART's catalog is huge and evolving — but we
  reserve the surface so importers/exporters have a stable home.
- **NCS layer classification.** When extraction starts from CAD
  layers following the National CAD Standard, we capture the raw
  layer string plus the parsed major/minor groups. These are
  first-class fields (not buried in ``properties``) so they can be
  indexed at the storage layer.
- **Confidence is nullable.** ``None`` means "not probabilistic"
  (deterministic extraction or human authoring); a float in [0, 1]
  is the extractor's belief. See D-05.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from atlas_core.enums import ElementKind, SheetDiscipline, Units
from atlas_core.geometry import BoundingBox, Polygon, Polyline


class _ElementBase(BaseModel):
    """Common fields shared by every DrawingElement kind."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)

    # Provenance & confidence — see D-05.
    confidence: float | None = Field(default=1.0, ge=0.0, le=1.0)
    source_layer: str | None = None  # raw layer name (CAD or PDF), pre-parse.

    # NCS (US National CAD Standard) layer classification — see D-03.
    # Layer names look like ``A-WALL-EXTR-FULL``:
    # <discipline>-<major>-<minor>-<modifier>.
    ncs_layer: str | None = None
    ncs_major_group: str | None = Field(default=None, max_length=4)  # WALL, DOOR…
    ncs_minor_group: str | None = Field(default=None, max_length=8)  # EXTR, INTR…

    # IFC compatibility — see D-01.
    ifc_type: str | None = None  # e.g. "IfcWallStandardCase", "IfcDoor".
    ifc_properties: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Spatial summary + free-form extractor-specific bag.
    bbox: BoundingBox | None = None
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class Room(_ElementBase):
    kind: Literal[ElementKind.ROOM] = ElementKind.ROOM
    name: str | None = None
    number: str | None = None
    boundary: Polygon
    area: float | None = Field(default=None, ge=0.0)


class Wall(_ElementBase):
    kind: Literal[ElementKind.WALL] = ElementKind.WALL
    centerline: Polyline
    thickness: float | None = Field(default=None, gt=0.0)
    height: float | None = Field(default=None, gt=0.0)
    is_exterior: bool = False


class Door(_ElementBase):
    kind: Literal[ElementKind.DOOR] = ElementKind.DOOR
    width: float = Field(gt=0.0)
    height: float | None = Field(default=None, gt=0.0)
    hinge: Polyline | None = None
    swing_angle_deg: float | None = Field(default=None, ge=0.0, le=360.0)
    host_wall_id: UUID | None = None


class Window(_ElementBase):
    kind: Literal[ElementKind.WINDOW] = ElementKind.WINDOW
    width: float = Field(gt=0.0)
    height: float | None = Field(default=None, gt=0.0)
    sill_height: float | None = None
    host_wall_id: UUID | None = None


class GenericElement(_ElementBase):
    """Fallback for element kinds without a dedicated model yet."""

    kind: Literal[
        ElementKind.COLUMN,
        ElementKind.STAIR,
        ElementKind.DIMENSION,
        ElementKind.ANNOTATION,
        ElementKind.SYMBOL,
        ElementKind.OTHER,
    ]
    text: str | None = None
    geometry: Polyline | Polygon | None = None


DrawingElement = Annotated[
    Room | Wall | Door | Window | GenericElement,
    Field(discriminator="kind"),
]


class StructuredSheet(BaseModel):
    """A single sheet's structured content."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    sheet_number: str
    title: str | None = None
    discipline: SheetDiscipline = SheetDiscipline.ARCHITECTURAL
    scale: str | None = None
    units: Units = Units.FEET
    page_size: tuple[float, float] | None = None
    elements: list[DrawingElement] = Field(default_factory=list)

    def elements_of(self, kind: ElementKind) -> list[DrawingElement]:
        return [e for e in self.elements if e.kind == kind]


class StructuredDrawing(BaseModel):
    """A full structured drawing package — one or more sheets."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    project_name: str | None = None
    source_filename: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sheets: list[StructuredSheet] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    def sheet_by_number(self, sheet_number: str) -> StructuredSheet | None:
        for s in self.sheets:
            if s.sheet_number == sheet_number:
                return s
        return None
