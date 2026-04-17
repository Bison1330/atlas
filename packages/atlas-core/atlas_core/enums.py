"""Enumerations for the Atlas domain model."""

from __future__ import annotations

from enum import StrEnum


class Units(StrEnum):
    """Linear units used in a drawing's coordinate system."""

    MILLIMETERS = "mm"
    CENTIMETERS = "cm"
    METERS = "m"
    INCHES = "in"
    FEET = "ft"


class SheetDiscipline(StrEnum):
    """AEC disciplines following the CSI sheet-identification standard."""

    GENERAL = "G"
    HAZARDOUS = "H"
    SURVEY = "V"
    CIVIL = "C"
    LANDSCAPE = "L"
    STRUCTURAL = "S"
    ARCHITECTURAL = "A"
    INTERIORS = "I"
    EQUIPMENT = "Q"
    FIRE_PROTECTION = "F"
    PLUMBING = "P"
    MECHANICAL = "M"
    ELECTRICAL = "E"
    TELECOMMUNICATIONS = "T"


class IngestStatus(StrEnum):
    """Lifecycle of a drawing as it moves through the ingest pipeline.

    The order of declaration reflects the normal forward progression. A
    drawing only ever moves forward through these states, except into the
    terminal ``FAILED`` state which can be reached from any non-terminal
    state.
    """

    QUEUED = "queued"
    VALIDATING = "validating"
    RASTERIZING = "rasterizing"
    TILING = "tiling"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {IngestStatus.COMPLETED, IngestStatus.FAILED}

    @property
    def is_in_progress(self) -> bool:
        return self in {
            IngestStatus.VALIDATING,
            IngestStatus.RASTERIZING,
            IngestStatus.TILING,
        }


class ElementKind(StrEnum):
    """Top-level classification for a DrawingElement."""

    ROOM = "room"
    WALL = "wall"
    DOOR = "door"
    WINDOW = "window"
    COLUMN = "column"
    STAIR = "stair"
    DIMENSION = "dimension"
    ANNOTATION = "annotation"
    SYMBOL = "symbol"
    OTHER = "other"


class ElementSourceKind(StrEnum):
    """How an element came into existence — see D-05/D-06."""

    EXTRACTION = "extraction"  # produced by an extractor (NCS parser, OCR, CV…)
    GENERATION = "generation"  # produced by a generative pipeline
    MANUAL_OVERRIDE = "manual_override"  # human authoring or correction


class ElementSourceStatus(StrEnum):
    """Lifecycle of an ``element_sources`` row."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {ElementSourceStatus.COMPLETED, ElementSourceStatus.FAILED}
