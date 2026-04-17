"""Material takeoff computation.

Aggregates Element rows (the M2 extraction output) into a structured
"takeoff" report suitable for cost/quantity estimation. Pure-function
over a list of Element rows — the route layer owns DB fetch + source
resolution.

Phase 1 categories:

- **Walls** — count + total linear length (sum of polyline segment
  distances). Subcategorized by NCS minor group (e.g. EXTR / INTR)
  so a UI can show "exterior walls 36 LF, interior walls 84 LF".
- **Rooms** — count + total floor area (shoelace over the polygon
  ring). Subcategorized by NCS major group (some setups put rooms
  on AREA vs ROOM).
- **Doors / Windows / Columns / Stairs** — count only. We don't yet
  have first-class "type" or "schedule mark" data on these in the
  schema; once an extractor surfaces it we can subcategorize.
- **Other / annotation / dimension / symbol** — counted but not
  measured; relegated to the "uncounted" tail of the report.

Units. We don't know whether the source DXF was authored in feet,
inches, meters, or millimeters — the schema doesn't yet record it.
The takeoff reports raw DXF units with an explicit caveat string in
the response payload so the UI can label numbers honestly.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Subcategory:
    label: str
    count: int = 0
    linear_units: float | None = None
    area_units: float | None = None


@dataclass(slots=True)
class Category:
    kind: str
    label: str
    count: int = 0
    total_linear_units: float | None = None
    total_area_units: float | None = None
    subcategories: list[Subcategory] = field(default_factory=list)


@dataclass(slots=True)
class TakeoffReport:
    categories: list[Category]
    total_elements: int
    kinds_present: list[str]


# ---- public entrypoint ----


def compute_takeoff(elements: Iterable[Any]) -> TakeoffReport:
    """Aggregate ORM ``Element`` rows into a TakeoffReport.

    Accepts anything with the relevant attributes (``kind``,
    ``geometry``, ``ncs_major_group``, ``ncs_minor_group``). Tested
    against both the SQLAlchemy model and lightweight test stand-ins.
    """
    items = list(elements)

    walls = _walls_category([e for e in items if e.kind == "wall"])
    rooms = _rooms_category([e for e in items if e.kind == "room"])
    counted = [
        ("door", "Doors"),
        ("window", "Windows"),
        ("column", "Columns"),
        ("stair", "Stairs"),
    ]
    count_only = [
        Category(kind=k, label=label, count=sum(1 for e in items if e.kind == k))
        for k, label in counted
    ]
    misc_kinds = [
        ("dimension", "Dimensions"),
        ("annotation", "Annotations"),
        ("symbol", "Symbols"),
        ("other", "Other"),
    ]
    miscellaneous = [
        Category(kind=k, label=label, count=sum(1 for e in items if e.kind == k))
        for k, label in misc_kinds
    ]

    # Order matters for the UI: structural / spatial first, then
    # openings, then count-only / annotation cruft at the bottom.
    ordered = [walls, rooms, *count_only, *miscellaneous]
    # Drop empties to keep the report tight; a UI would clutter
    # otherwise with every kind even when zero.
    categories = [c for c in ordered if c.count > 0]

    return TakeoffReport(
        categories=categories,
        total_elements=len(items),
        kinds_present=sorted({e.kind for e in items}),
    )


# ---- per-category builders ----


def _walls_category(walls: list[Any]) -> Category:
    cat = Category(kind="wall", label="Walls", count=len(walls))
    if not walls:
        return cat
    total = 0.0
    by_minor: dict[str | None, list[Any]] = {}
    for w in walls:
        total += polyline_length(_geometry_points(w.geometry, "polyline", "points"))
        by_minor.setdefault(w.ncs_minor_group, []).append(w)
    cat.total_linear_units = round(total, 3)

    for minor, group in sorted(by_minor.items(), key=lambda kv: (kv[0] or "")):
        sub_total = sum(
            polyline_length(_geometry_points(w.geometry, "polyline", "points"))
            for w in group
        )
        label = f"NCS {minor}" if minor else "(no NCS minor)"
        cat.subcategories.append(
            Subcategory(label=label, count=len(group), linear_units=round(sub_total, 3))
        )
    return cat


def _rooms_category(rooms: list[Any]) -> Category:
    cat = Category(kind="room", label="Rooms", count=len(rooms))
    if not rooms:
        return cat
    total = 0.0
    by_major: dict[str | None, list[Any]] = {}
    for r in rooms:
        total += polygon_area(_geometry_points(r.geometry, "polygon", "ring"))
        by_major.setdefault(r.ncs_major_group, []).append(r)
    cat.total_area_units = round(total, 3)

    if len(by_major) > 1:
        for major, group in sorted(by_major.items(), key=lambda kv: (kv[0] or "")):
            sub_total = sum(
                polygon_area(_geometry_points(r.geometry, "polygon", "ring"))
                for r in group
            )
            label = f"NCS {major}" if major else "(no NCS major)"
            cat.subcategories.append(
                Subcategory(label=label, count=len(group), area_units=round(sub_total, 3))
            )
    return cat


# ---- geometry helpers ----


def polyline_length(points: list[dict[str, float]]) -> float:
    """Sum of segment distances. Empty / single-point input returns 0."""
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(len(points) - 1):
        dx = points[i + 1]["x"] - points[i]["x"]
        dy = points[i + 1]["y"] - points[i]["y"]
        total += math.hypot(dx, dy)
    return total


def polygon_area(ring: list[dict[str, float]]) -> float:
    """Absolute shoelace area; degenerate (<3 points) returns 0."""
    if len(ring) < 3:
        return 0.0
    s = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]["x"], ring[i]["y"]
        x1, y1 = ring[(i + 1) % n]["x"], ring[(i + 1) % n]["y"]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def _geometry_points(
    geometry: dict[str, Any] | None,
    expected_kind: str,
    array_key: str,
) -> list[dict[str, float]]:
    """Pull the point sequence out of a geometry blob, defensively.

    Returns an empty list for missing / wrong-shape geometry rather
    than raising — extraction edge cases shouldn't crash a takeoff.
    """
    if not geometry:
        return []
    if geometry.get("kind") != expected_kind:
        return []
    pts = geometry.get(array_key)
    if not isinstance(pts, list):
        return []
    return [p for p in pts if isinstance(p, dict) and "x" in p and "y" in p]
