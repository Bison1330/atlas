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
