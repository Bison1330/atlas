"""Geometry primitives used throughout the Atlas domain model.

Coordinates are expressed in the Units declared on the owning
StructuredSheet. The origin and orientation are sheet-local; world
placement is handled upstream.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Point(BaseModel):
    """A 2D point in sheet-local coordinates."""

    model_config = ConfigDict(frozen=True)

    x: float
    y: float


class BoundingBox(BaseModel):
    """Axis-aligned bounding box (minx, miny, maxx, maxy)."""

    model_config = ConfigDict(frozen=True)

    minx: float
    miny: float
    maxx: float
    maxy: float

    @field_validator("maxx")
    @classmethod
    def _check_x(cls, v: float, info) -> float:
        if "minx" in info.data and v < info.data["minx"]:
            raise ValueError("maxx must be >= minx")
        return v

    @field_validator("maxy")
    @classmethod
    def _check_y(cls, v: float, info) -> float:
        if "miny" in info.data and v < info.data["miny"]:
            raise ValueError("maxy must be >= miny")
        return v

    @property
    def width(self) -> float:
        return self.maxx - self.minx

    @property
    def height(self) -> float:
        return self.maxy - self.miny

    @property
    def area(self) -> float:
        return self.width * self.height


class Polyline(BaseModel):
    """An ordered sequence of 2+ points. Not implicitly closed."""

    points: list[Point] = Field(min_length=2)


class Polygon(BaseModel):
    """A closed ring of 3+ points. First point is not repeated as last."""

    ring: list[Point] = Field(min_length=3)
    holes: list[list[Point]] = Field(default_factory=list)
