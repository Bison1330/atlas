"""Pure-function tests for the takeoffs aggregator.

These don't touch the DB — they pass in lightweight stand-ins with
the attribute shape ``compute_takeoff`` consumes. The route-level
test suite covers the SQL/integration path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.services.takeoffs import (
    compute_takeoff,
    polygon_area,
    polyline_length,
)


@dataclass
class FakeElement:
    kind: str
    geometry: dict[str, Any] | None = None
    ncs_major_group: str | None = None
    ncs_minor_group: str | None = None


def _polyline(*pts: tuple[float, float]) -> dict[str, Any]:
    return {"kind": "polyline", "points": [{"x": x, "y": y} for x, y in pts]}


def _polygon(*pts: tuple[float, float]) -> dict[str, Any]:
    return {"kind": "polygon", "ring": [{"x": x, "y": y} for x, y in pts]}


# ---- geometry helpers ----


class TestPolylineLength:
    def test_horizontal_segment(self):
        assert polyline_length([{"x": 0, "y": 0}, {"x": 10, "y": 0}]) == 10.0

    def test_diagonal_segment_pythagorean(self):
        assert polyline_length([{"x": 0, "y": 0}, {"x": 3, "y": 4}]) == pytest.approx(5.0)

    def test_chained_segments(self):
        # 3-4-5 triangle perimeter walk: (0,0)->(3,0)->(3,4)->(0,0) = 3 + 4 + 5 = 12
        pts = [{"x": 0, "y": 0}, {"x": 3, "y": 0}, {"x": 3, "y": 4}, {"x": 0, "y": 0}]
        assert polyline_length(pts) == pytest.approx(12.0)

    def test_empty_returns_zero(self):
        assert polyline_length([]) == 0.0
        assert polyline_length([{"x": 1, "y": 1}]) == 0.0


class TestPolygonArea:
    def test_unit_square(self):
        assert polygon_area([
            {"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}
        ]) == pytest.approx(1.0)

    def test_3_4_5_triangle(self):
        assert polygon_area([
            {"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 0, "y": 3}
        ]) == pytest.approx(6.0)

    def test_orientation_independent(self):
        cw = [{"x": 0, "y": 0}, {"x": 0, "y": 5}, {"x": 5, "y": 5}, {"x": 5, "y": 0}]
        ccw = [{"x": 0, "y": 0}, {"x": 5, "y": 0}, {"x": 5, "y": 5}, {"x": 0, "y": 5}]
        assert polygon_area(cw) == polygon_area(ccw) == pytest.approx(25.0)

    def test_degenerate(self):
        assert polygon_area([]) == 0.0
        assert polygon_area([{"x": 0, "y": 0}, {"x": 1, "y": 1}]) == 0.0


# ---- aggregation ----


class TestComputeTakeoff:
    def test_empty_input(self):
        report = compute_takeoff([])
        assert report.total_elements == 0
        assert report.kinds_present == []
        assert report.categories == []

    def test_walls_aggregate_linear_footage(self):
        walls = [
            FakeElement(
                kind="wall", ncs_minor_group="EXTR",
                geometry=_polyline((0, 0), (10, 0)),
            ),
            FakeElement(
                kind="wall", ncs_minor_group="EXTR",
                geometry=_polyline((10, 0), (10, 8)),
            ),
            FakeElement(
                kind="wall", ncs_minor_group="INTR",
                geometry=_polyline((5, 0), (5, 8)),
            ),
        ]
        report = compute_takeoff(walls)
        wall_cat = next(c for c in report.categories if c.kind == "wall")
        assert wall_cat.count == 3
        assert wall_cat.total_linear_units == pytest.approx(26.0)
        # Subcategories grouped by NCS minor; 2 EXTR + 1 INTR.
        labels = {s.label: s for s in wall_cat.subcategories}
        assert labels["NCS EXTR"].count == 2
        assert labels["NCS EXTR"].linear_units == pytest.approx(18.0)
        assert labels["NCS INTR"].count == 1
        assert labels["NCS INTR"].linear_units == pytest.approx(8.0)

    def test_rooms_aggregate_area(self):
        rooms = [
            FakeElement(
                kind="room", ncs_major_group="ROOM",
                geometry=_polygon((0, 0), (10, 0), (10, 8), (0, 8)),
            ),
            FakeElement(
                kind="room", ncs_major_group="ROOM",
                geometry=_polygon((0, 0), (4, 0), (4, 4), (0, 4)),
            ),
        ]
        report = compute_takeoff(rooms)
        room_cat = next(c for c in report.categories if c.kind == "room")
        assert room_cat.count == 2
        assert room_cat.total_area_units == pytest.approx(96.0)  # 80 + 16
        # Single major group → no subcategorization.
        assert room_cat.subcategories == []

    def test_rooms_subcategorize_when_multiple_majors(self):
        rooms = [
            FakeElement(
                kind="room", ncs_major_group="ROOM",
                geometry=_polygon((0, 0), (4, 0), (4, 4), (0, 4)),
            ),
            FakeElement(
                kind="room", ncs_major_group="AREA",
                geometry=_polygon((0, 0), (3, 0), (3, 3), (0, 3)),
            ),
        ]
        report = compute_takeoff(rooms)
        room_cat = next(c for c in report.categories if c.kind == "room")
        assert len(room_cat.subcategories) == 2
        labels = {s.label for s in room_cat.subcategories}
        assert labels == {"NCS ROOM", "NCS AREA"}

    def test_count_only_categories(self):
        elements = [
            FakeElement(kind="door"),
            FakeElement(kind="door"),
            FakeElement(kind="window"),
        ]
        report = compute_takeoff(elements)
        kinds = {c.kind: c for c in report.categories}
        assert kinds["door"].count == 2
        assert kinds["door"].total_linear_units is None
        assert kinds["door"].total_area_units is None
        assert kinds["window"].count == 1

    def test_zero_count_categories_dropped(self):
        # Only walls present — door/window/etc. categories shouldn't
        # show up just because they're in the canonical list.
        report = compute_takeoff([
            FakeElement(kind="wall", geometry=_polyline((0, 0), (1, 0))),
        ])
        kinds = {c.kind for c in report.categories}
        assert kinds == {"wall"}

    def test_mixed_drawing_full_report(self):
        # Mirrors the synthetic fixture used elsewhere: 4 walls + 1 room + 1 door.
        elements = [
            FakeElement(kind="wall", ncs_minor_group="EXTR",
                        geometry=_polyline((0, 0), (10, 0))),
            FakeElement(kind="wall", ncs_minor_group="EXTR",
                        geometry=_polyline((10, 0), (10, 8))),
            FakeElement(kind="wall", ncs_minor_group="EXTR",
                        geometry=_polyline((10, 8), (0, 8))),
            FakeElement(kind="wall", ncs_minor_group="EXTR",
                        geometry=_polyline((0, 8), (0, 0))),
            FakeElement(kind="room", ncs_major_group="ROOM",
                        geometry=_polygon((0, 0), (10, 0), (10, 8), (0, 8))),
            FakeElement(kind="door"),
        ]
        report = compute_takeoff(elements)
        assert report.total_elements == 6
        assert sorted(report.kinds_present) == ["door", "room", "wall"]

        kinds = {c.kind: c for c in report.categories}
        assert kinds["wall"].total_linear_units == pytest.approx(36.0)  # perimeter
        assert kinds["room"].total_area_units == pytest.approx(80.0)
        assert kinds["door"].count == 1

    def test_garbage_geometry_treated_as_zero(self):
        # Defensive — extraction edge cases shouldn't crash a takeoff.
        bad = [
            FakeElement(kind="wall", geometry=None),
            FakeElement(kind="wall", geometry={"kind": "polygon", "ring": []}),  # wrong kind
            FakeElement(kind="room", geometry={"kind": "polyline", "points": []}),  # wrong kind
            FakeElement(kind="wall", geometry=_polyline((0, 0), (1, 0))),
        ]
        report = compute_takeoff(bad)
        wall = next(c for c in report.categories if c.kind == "wall")
        # 3 walls counted, only one with valid polyline geometry contributes length.
        assert wall.count == 3
        assert wall.total_linear_units == pytest.approx(1.0)
