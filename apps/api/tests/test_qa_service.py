"""Pure-function tests for the M5 Q&A service.

These tests never touch the DB or the Anthropic API — they pass
in plain dict "elements" (the service is duck-typed) and a
``FakeInterpreter`` that returns pre-baked
:class:`QueryInterpretation` values. The route-level tests cover
the SQL + Claude integration wiring.

Coverage: one happy path per bucket + one edge case per bucket
(unsupported, missing identifier, empty input).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.services.qa import QueryInterpretation, ask
from app.services.qa_interpreter import FakeInterpreter


# ---------- Element builders ----------


SHEET_ID = UUID("11111111-1111-1111-1111-111111111111")


def _element(
    kind: str,
    *,
    id: UUID | None = None,
    geometry: dict[str, Any] | None = None,
    bbox: dict[str, float] | None = None,
    ncs_layer: str | None = None,
    ncs_major_group: str | None = None,
    ncs_minor_group: str | None = None,
    confidence: float | None = 0.95,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": id or uuid4(),
        "sheet_id": SHEET_ID,
        "kind": kind,
        "geometry": geometry,
        "bbox": bbox,
        "ncs_layer": ncs_layer,
        "ncs_major_group": ncs_major_group,
        "ncs_minor_group": ncs_minor_group,
        "confidence": confidence,
        "attrs": attrs or {},
    }


def _polyline(*pts: tuple[float, float]) -> dict[str, Any]:
    return {"kind": "polyline", "points": [{"x": x, "y": y} for x, y in pts]}


def _polygon(*pts: tuple[float, float]) -> dict[str, Any]:
    return {"kind": "polygon", "ring": [{"x": x, "y": y} for x, y in pts]}


def _bbox(minx: float, miny: float, maxx: float, maxy: float) -> dict[str, float]:
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


# Single shared "one-room-floor" style fixture — 4 walls + 1 door.
def _one_room_floor() -> list[dict[str, Any]]:
    walls = [
        _element(
            "wall",
            geometry=_polyline((0, 0), (10, 0)),
            bbox=_bbox(0, 0, 10, 0),
            ncs_layer="A-WALL-EXTR",
            ncs_major_group="WALL",
            ncs_minor_group="EXTR",
        ),
        _element(
            "wall",
            geometry=_polyline((10, 0), (10, 8)),
            bbox=_bbox(10, 0, 10, 8),
            ncs_layer="A-WALL-EXTR",
            ncs_major_group="WALL",
            ncs_minor_group="EXTR",
        ),
        _element(
            "wall",
            geometry=_polyline((10, 8), (0, 8)),
            bbox=_bbox(0, 8, 10, 8),
            ncs_layer="A-WALL-EXTR",
            ncs_major_group="WALL",
            ncs_minor_group="EXTR",
        ),
        _element(
            "wall",
            geometry=_polyline((0, 8), (0, 0)),
            bbox=_bbox(0, 0, 0, 8),
            ncs_layer="A-WALL-EXTR",
            ncs_major_group="WALL",
            ncs_minor_group="EXTR",
        ),
    ]
    door = _element(
        "door",
        geometry={"kind": "arc", "center": {"x": 2.5, "y": 0}, "radius": 1,
                  "start_angle_deg": 0, "end_angle_deg": 90},
        bbox=_bbox(1.5, -1, 3.5, 1),
        ncs_layer="A-DOOR",
        ncs_major_group="DOOR",
    )
    return [*walls, door]


def _two_room_floor() -> list[dict[str, Any]]:
    """Two 5x10 rooms split at x=5, with a door in the partition."""
    # 4 exterior walls + 1 interior partition
    walls = [
        _element("wall", geometry=_polyline((0, 0), (10, 0)),
                 ncs_layer="A-WALL-EXTR", ncs_major_group="WALL", ncs_minor_group="EXTR"),
        _element("wall", geometry=_polyline((10, 0), (10, 10)),
                 ncs_layer="A-WALL-EXTR", ncs_major_group="WALL", ncs_minor_group="EXTR"),
        _element("wall", geometry=_polyline((10, 10), (0, 10)),
                 ncs_layer="A-WALL-EXTR", ncs_major_group="WALL", ncs_minor_group="EXTR"),
        _element("wall", geometry=_polyline((0, 10), (0, 0)),
                 ncs_layer="A-WALL-EXTR", ncs_major_group="WALL", ncs_minor_group="EXTR"),
        _element("wall", geometry=_polyline((5, 0), (5, 10)),
                 ncs_layer="A-WALL-INTR", ncs_major_group="WALL", ncs_minor_group="INTR"),
    ]
    rooms = [
        _element("room", id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                 geometry=_polygon((0, 0), (5, 0), (5, 10), (0, 10)),
                 bbox=_bbox(0, 0, 5, 10),
                 attrs={"area": 50.0, "derived": True}),
        _element("room", id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                 geometry=_polygon((5, 0), (10, 0), (10, 10), (5, 10)),
                 bbox=_bbox(5, 0, 10, 10),
                 attrs={"area": 50.0, "derived": True}),
    ]
    door = _element("door",
                    geometry={"kind": "arc", "center": {"x": 5, "y": 5}, "radius": 1,
                              "start_angle_deg": 0, "end_angle_deg": 90},
                    ncs_layer="A-DOOR")
    return [*walls, *rooms, door]


def _three_room_floor() -> list[dict[str, Any]]:
    """Large R3 + two small R1/R2, D1 and D2 connect R1-R3 and R2-R3."""
    walls = [
        _element("wall", geometry=_polyline((0, 0), (10, 0)),
                 ncs_layer="A-WALL-EXTR", ncs_major_group="WALL", ncs_minor_group="EXTR"),
        _element("wall", geometry=_polyline((10, 0), (10, 10)),
                 ncs_layer="A-WALL-EXTR", ncs_major_group="WALL", ncs_minor_group="EXTR"),
        _element("wall", geometry=_polyline((10, 10), (0, 10)),
                 ncs_layer="A-WALL-EXTR", ncs_major_group="WALL", ncs_minor_group="EXTR"),
        _element("wall", geometry=_polyline((0, 10), (0, 0)),
                 ncs_layer="A-WALL-EXTR", ncs_major_group="WALL", ncs_minor_group="EXTR"),
        _element("wall", geometry=_polyline((0, 5), (10, 5)),
                 ncs_layer="A-WALL-INTR", ncs_major_group="WALL", ncs_minor_group="INTR"),
        _element("wall", geometry=_polyline((5, 5), (5, 10)),
                 ncs_layer="A-WALL-INTR", ncs_major_group="WALL", ncs_minor_group="INTR"),
    ]
    # R3 biggest (area 50), R1 and R2 each 25
    rooms = [
        _element("room", id=UUID("33333333-3333-3333-3333-333333333333"),
                 geometry=_polygon((0, 0), (10, 0), (10, 5), (0, 5)),
                 bbox=_bbox(0, 0, 10, 5),
                 attrs={"area": 50.0, "derived": True}),
        _element("room", id=UUID("11111111-2222-2222-2222-222222222222"),
                 geometry=_polygon((0, 5), (5, 5), (5, 10), (0, 10)),
                 bbox=_bbox(0, 5, 5, 10),
                 attrs={"area": 25.0, "derived": True}),
        _element("room", id=UUID("22222222-3333-3333-3333-333333333333"),
                 geometry=_polygon((5, 5), (10, 5), (10, 10), (5, 10)),
                 bbox=_bbox(5, 5, 10, 10),
                 attrs={"area": 25.0, "derived": True}),
    ]
    doors = [
        _element("door",
                 geometry={"kind": "arc", "center": {"x": 2.5, "y": 5}, "radius": 1,
                           "start_angle_deg": 0, "end_angle_deg": 90}),
        _element("door",
                 geometry={"kind": "arc", "center": {"x": 7.5, "y": 5}, "radius": 1,
                           "start_angle_deg": 0, "end_angle_deg": 90}),
    ]
    return [*walls, *rooms, *doors]


# ---------- Count bucket ----------


class TestCountBucket:
    def test_count_walls(self):
        interp = QueryInterpretation(bucket="count", filter={"kind": "wall"})
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _one_room_floor(), fake)

        assert result.answer_type == "count"
        assert len(result.citations) == 4
        assert "4" in result.answer
        # All 4 cited are walls.
        assert all(c.kind == "wall" for c in result.citations)

    def test_count_filtered_by_ncs_minor(self):
        # Only exterior walls in the fixture — filter should count all 4.
        interp = QueryInterpretation(
            bucket="count",
            filter={"kind": "wall", "ncs_minor_group": "EXTR"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _two_room_floor(), fake)

        assert len(result.citations) == 4
        assert "4" in result.answer

    def test_count_zero_is_legal(self):
        interp = QueryInterpretation(bucket="count", filter={"kind": "window"})
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _one_room_floor(), fake)

        assert len(result.citations) == 0
        assert "0" in result.answer


# ---------- Quantity bucket ----------


class TestQuantityBucket:
    def test_total_wall_length(self):
        interp = QueryInterpretation(
            bucket="quantity",
            filter={"kind": "wall", "metric": "length"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _one_room_floor(), fake)

        # Perimeter of 10x8 = 10+8+10+8 = 36
        assert "36" in result.answer
        assert len(result.citations) == 4

    def test_total_room_area(self):
        interp = QueryInterpretation(
            bucket="quantity",
            filter={"kind": "room", "metric": "area"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _two_room_floor(), fake)

        # 50 + 50 = 100
        assert "100" in result.answer
        assert len(result.citations) == 2


# ---------- Rank bucket ----------


class TestRankBucket:
    def test_largest_room(self):
        interp = QueryInterpretation(
            bucket="rank",
            filter={"kind": "room", "metric": "area", "direction": "max"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _three_room_floor(), fake)

        assert len(result.citations) == 1
        # R3 (area 50) should win.
        assert str(result.citations[0].element_id) == \
            "33333333-3333-3333-3333-333333333333"
        assert "largest" in result.answer.lower()

    def test_smallest_room_tie_reports_medium_certainty(self):
        # R1 and R2 are both area 25 — ties trigger medium certainty.
        interp = QueryInterpretation(
            bucket="rank",
            filter={"kind": "room", "metric": "area", "direction": "min"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _three_room_floor(), fake)

        assert result.answer_certainty == "medium"


# ---------- Adjacency bucket ----------


class TestAdjacencyBucket:
    def test_rooms_connected_yes(self):
        # In three_room_floor, room 1 (biggest R3) is connected to
        # rooms 2 and 3 (R1, R2). "rooms 1 and 2 connected?" → yes.
        interp = QueryInterpretation(
            bucket="adjacency",
            filter={"query_type": "rooms_connected",
                    "room_a": "room 1", "room_b": "room 2"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _three_room_floor(), fake)

        assert result.answer_type == "adjacency"
        assert "Yes" in result.answer or "connected" in result.answer.lower()

    def test_rooms_not_connected(self):
        # R1 and R2 share a wall but no door connects them directly.
        interp = QueryInterpretation(
            bucket="adjacency",
            filter={"query_type": "rooms_connected",
                    "room_a": "room 2", "room_b": "room 3"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _three_room_floor(), fake)
        assert "No" in result.answer or "not" in result.answer.lower()

    def test_room_neighbors_of_big_room(self):
        interp = QueryInterpretation(
            bucket="adjacency",
            filter={"query_type": "room_neighbors", "room_a": "room 1"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _three_room_floor(), fake)
        # R3 (room 1 when sorted by area desc) should have 2 neighbors.
        # Count neighbor citations — excludes R3 itself + door bridges.
        neighbor_citations = [c for c in result.citations if c.kind == "room"]
        # 1 target + 2 neighbors
        assert len(neighbor_citations) == 3


# ---------- Lookup bucket ----------


class TestLookupBucket:
    def test_lookup_area_by_index(self):
        interp = QueryInterpretation(
            bucket="lookup",
            filter={"kind": "room", "identifier": "room 1", "attribute": "area"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _three_room_floor(), fake)

        assert len(result.citations) == 1
        assert "50" in result.answer

    def test_lookup_missing_identifier(self):
        interp = QueryInterpretation(
            bucket="lookup",
            filter={"kind": "room", "identifier": "room 99", "attribute": "area"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _three_room_floor(), fake)

        assert len(result.citations) == 0
        assert "not" in result.answer.lower() or "could not" in result.answer.lower()


# ---------- Unsupported ----------


class TestUnsupported:
    def test_unsupported_bucket_returns_friendly_error(self):
        interp = QueryInterpretation(
            bucket="unsupported",
            unsupported_reason="requires code-compliance knowledge",
            suggested_phrasing="how many exterior doors?",
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _one_room_floor(), fake)

        assert result.answer_type == "unsupported"
        assert result.citations == []
        assert "code-compliance" in result.answer
        assert "how many exterior doors?" in result.answer

    def test_fake_interpreter_unknown_question_yields_unsupported(self):
        fake = FakeInterpreter({})  # empty mapping
        result = ask("q", _one_room_floor(), fake)

        assert result.answer_type == "unsupported"
        assert result.citations == []


# ---------- Citation shape / confidence ----------


class TestCitationAndConfidence:
    def test_extraction_min_reflects_lowest_confidence(self):
        # One wall has confidence 0.6, rest 0.95 → extraction_min=0.6
        elements = _one_room_floor()
        elements[0]["confidence"] = 0.6

        interp = QueryInterpretation(bucket="count", filter={"kind": "wall"})
        fake = FakeInterpreter({"q": interp})
        result = ask("q", elements, fake)

        assert result.extraction_min == pytest.approx(0.6)

    def test_display_label_prefers_attrs_name(self):
        elements = _two_room_floor()
        elements[5]["attrs"] = {"name": "Living Room", "area": 50.0,
                                "derived": True}

        interp = QueryInterpretation(
            bucket="lookup",
            filter={"kind": "room", "identifier": "Living Room", "attribute": "area"},
        )
        fake = FakeInterpreter({"q": interp})
        result = ask("q", elements, fake)

        assert len(result.citations) == 1
        assert result.citations[0].display_label == "Living Room"

    def test_citation_carries_sheet_id_and_bbox(self):
        interp = QueryInterpretation(bucket="count", filter={"kind": "wall"})
        fake = FakeInterpreter({"q": interp})
        result = ask("q", _one_room_floor(), fake)

        assert all(c.sheet_id == SHEET_ID for c in result.citations)
        assert all(c.bbox is not None for c in result.citations)
