"""Atlas shared domain model."""

from atlas_core.enums import ElementKind, IngestStatus, SheetDiscipline, Units
from atlas_core.geometry import BoundingBox, Point, Polygon, Polyline
from atlas_core.ingest import (
    DrawingSummary,
    IngestStatusEvent,
    SheetSummary,
    TileRef,
)
from atlas_core.models import (
    Door,
    DrawingElement,
    Room,
    StructuredDrawing,
    StructuredSheet,
    Wall,
    Window,
)

__all__ = [
    "BoundingBox",
    "Door",
    "DrawingElement",
    "DrawingSummary",
    "ElementKind",
    "IngestStatus",
    "IngestStatusEvent",
    "Point",
    "Polygon",
    "Polyline",
    "Room",
    "SheetDiscipline",
    "SheetSummary",
    "StructuredDrawing",
    "StructuredSheet",
    "TileRef",
    "Units",
    "Wall",
    "Window",
]

__version__ = "0.2.0"
