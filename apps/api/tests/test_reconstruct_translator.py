"""Tests for ``app.services.reconstruct_translator``.

Unit tests with synthetic ``Element`` rows — no DB, no extractor. The
goal is to pin down exactly how the translator patches sparse real-
world extractor output so ``atlas_core.reconstruct3d`` can consume it.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.db import Element, Sheet
from app.services.reconstruct_translator import (
    TranslatorStats,
    elements_to_structured_sheet,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sheet() -> Sheet:
    return Sheet(id=uuid4(), drawing_id=uuid4(), page_number=1)


def _wall(
    *,
    thickness: float | None = 0.2,
    height: float | None = 2.8,
    ncs_minor: str | None = None,
    bbox: dict | None = None,
    sheet_id: UUID | None = None,
) -> Element:
    attrs: dict = {}
    if thickness is not None:
        attrs["thickness"] = thickness
    if height is not None:
        attrs["height"] = height
    return Element(
        id=uuid4(),
        sheet_id=sheet_id or uuid4(),
        source_id=uuid4(),
        kind="wall",
        ncs_minor_group=ncs_minor,
        geometry={
            "kind": "polyline",
            "points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}],
        },
        bbox=bbox if bbox is not None else {"minx": 0, "miny": 0, "maxx": 10, "maxy": 0},
        attrs=attrs,
        ifc_properties={},
    )


def _arc_door(*, host_id: UUID | None = None, with_width: bool = False) -> Element:
    attrs: dict = {"source_entity": "ARC", "swing_angle_deg": 90.0}
    if with_width:
        attrs["width"] = 0.9
    return Element(
        id=uuid4(),
        sheet_id=uuid4(),
        source_id=uuid4(),
        kind="door",
        host_element_id=host_id,
        geometry={
            "kind": "arc",
            "center": {"x": 3, "y": 6},
            "radius": 1.0,
            "start_angle_deg": 0.0,
            "end_angle_deg": 90.0,
        },
        bbox={"minx": 2, "miny": 5, "maxx": 4, "maxy": 7},
        attrs=attrs,
        ifc_properties={},
    )


def _insert_door(*, host_id: UUID | None = None) -> Element:
    return Element(
        id=uuid4(),
        sheet_id=uuid4(),
        source_id=uuid4(),
        kind="door",
        host_element_id=host_id,
        geometry={
            "kind": "insert",
            "center": {"x": 15, "y": 6},
            "x_scale": 1.0,
            "y_scale": 1.0,
            "rotation_deg": 0.0,
        },
        bbox=None,
        attrs={"block_name": "ATLAS_DOOR_SINGLE", "source_entity": "INSERT"},
        ifc_properties={},
    )


def _insert_window(*, host_id: UUID | None = None) -> Element:
    return Element(
        id=uuid4(),
        sheet_id=uuid4(),
        source_id=uuid4(),
        kind="window",
        host_element_id=host_id,
        geometry={
            "kind": "insert",
            "center": {"x": 3, "y": 12},
            "x_scale": 1.0,
            "y_scale": 1.0,
            "rotation_deg": 0.0,
        },
        bbox=None,
        attrs={"block_name": "ATLAS_WINDOW_DOUBLE", "source_entity": "INSERT"},
        ifc_properties={},
    )


def _room(ring: list[tuple[float, float]]) -> Element:
    return Element(
        id=uuid4(),
        sheet_id=uuid4(),
        source_id=uuid4(),
        kind="room",
        name="R1",
        geometry={
            "kind": "polygon",
            "ring": [{"x": x, "y": y} for x, y in ring],
        },
        attrs={"area": 100.0, "derived": True},
        ifc_properties={},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClean:
    def test_empty_returns_empty_sheet_zero_stats(self):
        sheet, stats = elements_to_structured_sheet(_sheet(), [])
        assert sheet.elements == []
        assert stats == TranslatorStats()

    def test_wall_with_all_fields_no_defaults_applied(self):
        w = _wall(thickness=0.2, height=2.8)
        sheet, stats = elements_to_structured_sheet(_sheet(), [w])
        assert len(sheet.elements) == 1
        assert stats.missing_wall_thickness == 0
        assert sheet.elements[0].thickness == 0.2
        assert sheet.elements[0].height == 2.8


class TestWallDefaults:
    def test_missing_thickness_uses_default_and_counts(self):
        w = _wall(thickness=None, height=None)
        sheet, stats = elements_to_structured_sheet(
            _sheet(), [w], default_wall_thickness_m=0.18
        )
        assert stats.missing_wall_thickness == 1
        assert sheet.elements[0].thickness == 0.18
        # Height stays None — reconstruct3d has its own default there.
        assert sheet.elements[0].height is None

    def test_is_exterior_inferred_from_ncs(self):
        w = _wall(ncs_minor="EXTR")
        sheet, _ = elements_to_structured_sheet(_sheet(), [w])
        assert sheet.elements[0].is_exterior is True

    def test_is_exterior_false_when_no_hint(self):
        w = _wall(ncs_minor=None)
        sheet, _ = elements_to_structured_sheet(_sheet(), [w])
        assert sheet.elements[0].is_exterior is False


class TestDoorDefaults:
    def test_arc_door_with_existing_bbox_and_no_width(self):
        # ARC doors get an extractor-computed bbox — no synthesis needed.
        d = _arc_door(with_width=False)
        sheet, stats = elements_to_structured_sheet(_sheet(), [d])
        assert stats.missing_door_width == 1
        assert stats.synthesized_insert_bbox == 0
        assert sheet.elements[0].width == 0.91
        assert sheet.elements[0].bbox is not None

    def test_insert_door_needs_width_and_bbox_synthesized(self):
        d = _insert_door()
        sheet, stats = elements_to_structured_sheet(
            _sheet(), [d], default_insert_bbox_m=0.6
        )
        assert stats.missing_door_width == 1
        assert stats.synthesized_insert_bbox == 1
        bb = sheet.elements[0].bbox
        assert bb is not None
        # Centered on (15, 6) with half-side 0.3.
        assert bb.minx == 14.7 and bb.maxx == 15.3
        assert bb.miny == 5.7 and bb.maxy == 6.3

    def test_door_with_width_in_attrs_no_default_applied(self):
        d = _arc_door(with_width=True)
        sheet, stats = elements_to_structured_sheet(_sheet(), [d])
        assert stats.missing_door_width == 0
        assert sheet.elements[0].width == 0.9


class TestWindowDefaults:
    def test_insert_window_default_width_and_synthesized_bbox(self):
        wn = _insert_window()
        sheet, stats = elements_to_structured_sheet(_sheet(), [wn])
        assert stats.missing_window_width == 1
        assert stats.synthesized_insert_bbox == 1
        assert sheet.elements[0].width == 1.22
        assert sheet.elements[0].bbox is not None


class TestRoomDrop:
    def test_malformed_polygon_dropped_with_reason(self):
        # Fewer than 3 points → can't build a polygon.
        bad = _room([(0, 0), (1, 0)])
        sheet, stats = elements_to_structured_sheet(_sheet(), [bad])
        assert sheet.elements == []
        assert stats.dropped_elements == 1
        assert stats.dropped_reasons == {"room_malformed": 1}

    def test_self_intersecting_polygon_dropped(self):
        # Bowtie-shaped self-intersecting polygon.
        bow = _room([(0, 0), (2, 2), (2, 0), (0, 2)])
        sheet, stats = elements_to_structured_sheet(_sheet(), [bow])
        assert sheet.elements == []
        assert stats.dropped_reasons == {"room_malformed": 1}

    def test_valid_room_passes_through(self):
        r = _room([(0, 0), (5, 0), (5, 4), (0, 4)])
        sheet, stats = elements_to_structured_sheet(_sheet(), [r])
        assert len(sheet.elements) == 1
        assert stats.dropped_elements == 0
        assert sheet.elements[0].name == "R1"


class TestOther:
    def test_non_structural_kinds_skipped_silently(self):
        # Columns/stairs/dimensions aren't consumed by reconstruct3d;
        # they should drop out without hitting dropped_elements (which
        # is reserved for rows we *tried* to translate but couldn't).
        col = Element(
            id=uuid4(), sheet_id=uuid4(), source_id=uuid4(),
            kind="column",
            geometry={"kind": "circle", "center": {"x": 5, "y": 5}, "radius": 0.3},
            attrs={}, ifc_properties={},
        )
        sheet, stats = elements_to_structured_sheet(_sheet(), [col])
        assert sheet.elements == []
        assert stats.dropped_elements == 0

    def test_wall_with_empty_geometry_dropped(self):
        w = Element(
            id=uuid4(), sheet_id=uuid4(), source_id=uuid4(),
            kind="wall",
            geometry={"kind": "polyline", "points": []},
            attrs={}, ifc_properties={},
        )
        sheet, stats = elements_to_structured_sheet(_sheet(), [w])
        assert sheet.elements == []
        assert stats.dropped_reasons == {"wall_missing_centerline": 1}


class TestOpeningCenterDispatch:
    """Regression tests for the (0, 0) fallback bug.

    Pre-fix, any door/window whose geometry lacked an extractor-
    computed bbox AND wasn't an INSERT fell through to ``bbox=None``
    and got silently dropped by reconstruct3d. Now the translator
    dispatches per geometry kind (polyline/arc/circle/polygon) and
    synthesises a bbox around the real centre.
    """

    def test_polyline_door_without_bbox_synthesises_bbox_at_real_center(self):
        # Polyline door: two points at y=0.05, centre at x=3.
        pts = [{"x": 2.55, "y": 0.05}, {"x": 3.45, "y": 0.05}]
        d = Element(
            id=uuid4(), sheet_id=uuid4(), source_id=uuid4(),
            kind="door", host_element_id=uuid4(),
            geometry={"kind": "polyline", "points": pts},
            bbox=None,
            attrs={"source_entity": "LWPOLYLINE"},
            ifc_properties={},
        )
        sheet, stats = elements_to_structured_sheet(
            _sheet(), [d], default_insert_bbox_m=0.5
        )
        assert len(sheet.elements) == 1
        assert stats.unhostable_openings == 0
        assert stats.synthesized_insert_bbox == 1
        bb = sheet.elements[0].bbox
        assert bb is not None
        # Bbox is centred on the polyline's mean point (3.0, 0.05).
        assert (bb.minx + bb.maxx) / 2 == pytest.approx(3.0, abs=1e-6)
        assert (bb.miny + bb.maxy) / 2 == pytest.approx(0.05, abs=1e-6)

    def test_polyline_window_without_bbox_synthesises_bbox(self):
        pts = [{"x": 5.5, "y": 8.0}, {"x": 6.5, "y": 8.0}]
        wn = Element(
            id=uuid4(), sheet_id=uuid4(), source_id=uuid4(),
            kind="window", host_element_id=uuid4(),
            geometry={"kind": "polyline", "points": pts},
            bbox=None,
            attrs={"source_entity": "LWPOLYLINE"},
            ifc_properties={},
        )
        sheet, stats = elements_to_structured_sheet(_sheet(), [wn])
        assert len(sheet.elements) == 1
        assert stats.unhostable_openings == 0
        assert stats.synthesized_insert_bbox == 1
        bb = sheet.elements[0].bbox
        assert (bb.minx + bb.maxx) / 2 == pytest.approx(6.0, abs=1e-6)

    def test_arc_door_without_bbox_synthesises_from_arc_center(self):
        d = Element(
            id=uuid4(), sheet_id=uuid4(), source_id=uuid4(),
            kind="door", host_element_id=uuid4(),
            geometry={
                "kind": "arc", "center": {"x": 7.0, "y": 6.0},
                "radius": 1.0, "start_angle_deg": 0.0, "end_angle_deg": 90.0,
            },
            bbox=None,
            attrs={"source_entity": "ARC", "swing_angle_deg": 90.0},
            ifc_properties={},
        )
        sheet, stats = elements_to_structured_sheet(_sheet(), [d])
        bb = sheet.elements[0].bbox
        assert (bb.minx + bb.maxx) / 2 == pytest.approx(7.0, abs=1e-6)
        assert (bb.miny + bb.maxy) / 2 == pytest.approx(6.0, abs=1e-6)
        assert stats.unhostable_openings == 0

    def test_unknown_geometry_door_is_unhostable(self):
        d = Element(
            id=uuid4(), sheet_id=uuid4(), source_id=uuid4(),
            kind="door", host_element_id=uuid4(),
            geometry={"kind": "raw", "entity_type": "HATCH"},
            bbox=None, attrs={}, ifc_properties={},
        )
        sheet, stats = elements_to_structured_sheet(_sheet(), [d])
        assert sheet.elements == []
        assert stats.unhostable_openings == 1
        assert stats.dropped_elements == 1
        assert stats.dropped_reasons == {"unhostable_opening": 1}

    def test_window_with_no_geometry_is_unhostable(self):
        wn = Element(
            id=uuid4(), sheet_id=uuid4(), source_id=uuid4(),
            kind="window", host_element_id=uuid4(),
            geometry={}, bbox=None, attrs={}, ifc_properties={},
        )
        sheet, stats = elements_to_structured_sheet(_sheet(), [wn])
        assert sheet.elements == []
        assert stats.unhostable_openings == 1

    def test_pathological_polyline_near_origin_does_not_synthesise_at_origin(self):
        # Regression guard for the (0, 0) fallback bug: a polyline
        # opening NEAR but not AT origin must synthesise its bbox
        # around its real centre, not around origin.
        pts = [{"x": 100.0, "y": 100.0}, {"x": 100.5, "y": 100.0}]
        d = Element(
            id=uuid4(), sheet_id=uuid4(), source_id=uuid4(),
            kind="door", host_element_id=uuid4(),
            geometry={"kind": "polyline", "points": pts},
            bbox=None, attrs={}, ifc_properties={},
        )
        sheet, stats = elements_to_structured_sheet(_sheet(), [d])
        bb = sheet.elements[0].bbox
        # Bbox centre near (100.25, 100) — NOT near origin.
        assert (bb.minx + bb.maxx) / 2 == pytest.approx(100.25, abs=1e-6)
        assert bb.minx > 99 and bb.maxx < 101
        assert stats.unhostable_openings == 0


class TestMixedBatch:
    def test_ten_element_mix_matches_expected_tallies(self):
        wall_id = uuid4()
        walled_sheet = _sheet()
        elements = [
            # 3 walls: 1 clean + 2 missing thickness
            _wall(thickness=0.2, sheet_id=walled_sheet.id),
            _wall(thickness=None, sheet_id=walled_sheet.id),
            _wall(thickness=None, sheet_id=walled_sheet.id),
            # 3 doors: 1 ARC-clean(with width) + 1 ARC-no-width + 1 INSERT
            _arc_door(with_width=True),
            _arc_door(with_width=False),
            _insert_door(),
            # 2 windows: both INSERT (the real-world common case)
            _insert_window(),
            _insert_window(),
            # 2 rooms: 1 clean + 1 malformed
            _room([(0, 0), (5, 0), (5, 4), (0, 4)]),
            _room([(0, 0), (1, 0)]),  # too few points
        ]
        sheet, stats = elements_to_structured_sheet(walled_sheet, elements)
        # 3 walls + 3 doors + 2 windows + 1 room = 9 salvaged; 1 dropped.
        assert len(sheet.elements) == 9
        assert stats.missing_wall_thickness == 2
        assert stats.missing_door_width == 2  # ARC-no-width + INSERT
        assert stats.missing_window_width == 2
        assert stats.synthesized_insert_bbox == 3  # 1 door + 2 windows
        assert stats.dropped_elements == 1
        assert stats.dropped_reasons == {"room_malformed": 1}
