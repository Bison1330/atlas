"""Tests for the 3D scene reconstruction layer."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from atlas_core.enums import Units
from atlas_core.geometry import BoundingBox, Point, Polygon, Polyline
from atlas_core.models import Door, Room, StructuredSheet, Wall, Window
from atlas_core.reconstruct3d import Scene3D, reconstruct_sheet


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _wall(points: list[tuple[float, float]], **kw) -> Wall:
    return Wall(centerline=Polyline(points=[Point(x=x, y=y) for x, y in points]), **kw)


def _room(ring: list[tuple[float, float]], **kw) -> Room:
    return Room(boundary=Polygon(ring=[Point(x=x, y=y) for x, y in ring]), **kw)


def _four_wall_square(side: float = 10.0, *, units: Units = Units.METERS) -> tuple[
    StructuredSheet, list[Wall], Room
]:
    """Build a square room with four walls and one explicit Room polygon.

    Walls go CCW: bottom, right, top, left. The room polygon covers
    the full square. No doors — callers add those.
    """
    w_bot = _wall([(0.0, 0.0), (side, 0.0)])
    w_rt = _wall([(side, 0.0), (side, side)])
    w_top = _wall([(side, side), (0.0, side)])
    w_lf = _wall([(0.0, side), (0.0, 0.0)])
    walls = [w_bot, w_rt, w_top, w_lf]
    room = _room([(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)], name="R1")
    sheet = StructuredSheet(sheet_number="A-101", units=units, elements=[*walls, room])
    return sheet, walls, room


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyAndSingle:
    def test_empty_sheet_returns_empty_scene(self):
        sheet = StructuredSheet(sheet_number="EMPTY")
        scene = reconstruct_sheet(sheet)
        assert isinstance(scene, Scene3D)
        assert scene.units == "m"
        assert scene.walls == []
        assert scene.floors == []
        assert scene.openings == []
        assert scene.bbox.min == [0.0, 0.0, 0.0]
        assert scene.bbox.max == [0.0, 0.0, 0.0]

    def test_single_straight_wall_no_openings(self):
        wall = _wall([(0.0, 0.0), (10.0, 0.0)])
        sheet = StructuredSheet(
            sheet_number="W", units=Units.METERS, elements=[wall]
        )
        scene = reconstruct_sheet(sheet)
        assert len(scene.walls) == 1
        assert len(scene.floors) == 0
        assert scene.openings == []

        # 8 vertices = 1 box. 12 triangles.
        wm = scene.walls[0]
        assert len(wm.vertices) == 8 * 3
        assert len(wm.indices) == 12 * 3
        assert wm.parent_wall_id == str(wall.id)

        # z range is [0, default_wall_height_m = 2.74].
        zs = wm.vertices[2::3]
        assert min(zs) == pytest.approx(0.0)
        assert max(zs) == pytest.approx(2.74)


class TestFourWallRoomWithDoor:
    def test_door_cuts_only_host_wall(self):
        sheet, walls, room = _four_wall_square(10.0)
        w_bot = walls[0]
        door = Door(
            width=0.9,
            height=2.1,
            host_wall_id=w_bot.id,
            properties={"parametric_position": 0.5},
        )
        sheet.elements.append(door)

        scene = reconstruct_sheet(sheet)
        assert len(scene.walls) == 4
        assert len(scene.floors) == 1
        assert len(scene.openings) == 1
        assert scene.openings[0].kind == "door"
        assert scene.openings[0].wall_id == str(w_bot.id)
        assert scene.openings[0].failed is False

        host = next(w for w in scene.walls if w.parent_wall_id == str(w_bot.id))
        others = [w for w in scene.walls if w.parent_wall_id != str(w_bot.id)]

        # Host wall mesh has more vertices than a plain box (boolean adds them).
        host_verts = len(host.vertices) // 3
        assert host_verts > 8
        # Every non-host wall is still a plain box.
        for w in others:
            assert len(w.vertices) // 3 == 8

    def test_window_uses_sill_height(self):
        sheet, walls, _ = _four_wall_square(10.0)
        w_bot = walls[0]
        window = Window(
            width=1.2,
            height=1.0,
            sill_height=1.0,
            host_wall_id=w_bot.id,
            properties={"parametric_position": 0.5},
        )
        sheet.elements.append(window)

        scene = reconstruct_sheet(sheet)
        opening = scene.openings[0]
        assert opening.kind == "window"
        # Bottom of the window is at sill=1.0.
        assert opening.bbox.min[2] == pytest.approx(1.0, abs=1e-6)
        assert opening.bbox.max[2] == pytest.approx(2.0, abs=1e-6)


class TestMultiSegmentWall:
    def test_l_shaped_wall_splits_into_segments(self):
        # An L-shaped wall: (0,0) → (5,0) → (5,5). Two segments.
        wall = _wall([(0.0, 0.0), (5.0, 0.0), (5.0, 5.0)])
        sheet = StructuredSheet(
            sheet_number="L", units=Units.METERS, elements=[wall]
        )
        scene = reconstruct_sheet(sheet)
        assert len(scene.walls) == 2
        for wm in scene.walls:
            assert wm.parent_wall_id == str(wall.id)
            # Each segment is a plain box (no openings).
            assert len(wm.vertices) // 3 == 8

    def test_duplicate_points_collapse(self):
        # A polyline with a zero-length middle segment should be dropped.
        wall = _wall([(0.0, 0.0), (5.0, 0.0), (5.0, 0.0), (10.0, 0.0)])
        sheet = StructuredSheet(
            sheet_number="D", units=Units.METERS, elements=[wall]
        )
        scene = reconstruct_sheet(sheet)
        assert len(scene.walls) == 2


class TestUnitNormalization:
    def test_feet_vs_meters_produces_scaled_bbox(self):
        # Same 10-unit wall expressed in feet vs meters.
        wall_m = _wall([(0.0, 0.0), (10.0, 0.0)])
        wall_ft = _wall([(0.0, 0.0), (10.0, 0.0)])
        sheet_m = StructuredSheet(
            sheet_number="M", units=Units.METERS, elements=[wall_m]
        )
        sheet_ft = StructuredSheet(
            sheet_number="F", units=Units.FEET, elements=[wall_ft]
        )
        scene_m = reconstruct_sheet(sheet_m)
        scene_ft = reconstruct_sheet(sheet_ft)

        # X-extent in meters should equal X-extent in feet * 0.3048.
        x_m = scene_m.bbox.max[0] - scene_m.bbox.min[0]
        x_ft = scene_ft.bbox.max[0] - scene_ft.bbox.min[0]
        assert x_ft == pytest.approx(x_m * 0.3048, rel=1e-6)

        # Z-extent is the wall height — defaults are in meters and
        # should be identical regardless of sheet units.
        z_m = scene_m.bbox.max[2] - scene_m.bbox.min[2]
        z_ft = scene_ft.bbox.max[2] - scene_ft.bbox.min[2]
        assert z_m == pytest.approx(z_ft, rel=1e-6)
        assert z_m == pytest.approx(2.74, rel=1e-6)

    def test_inches_millimeters_centimeters(self):
        for units, factor in [
            (Units.INCHES, 0.0254),
            (Units.MILLIMETERS, 0.001),
            (Units.CENTIMETERS, 0.01),
        ]:
            wall = _wall([(0.0, 0.0), (100.0, 0.0)])
            sheet = StructuredSheet(
                sheet_number="U", units=units, elements=[wall]
            )
            scene = reconstruct_sheet(sheet)
            x = scene.bbox.max[0] - scene.bbox.min[0]
            assert x == pytest.approx(100.0 * factor, rel=1e-6)


class TestRoomAreaAndFloor:
    def test_rectangular_room_area(self):
        # 5m × 4m rectangle.
        room = _room([(0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)], name="R")
        sheet = StructuredSheet(
            sheet_number="R", units=Units.METERS, elements=[room]
        )
        scene = reconstruct_sheet(sheet)
        assert len(scene.floors) == 1
        assert scene.floors[0].area_m2 == pytest.approx(20.0, rel=1e-6)
        assert scene.floors[0].name == "R"
        # Centroid of a 5×4 rect anchored at origin is (2.5, 2.0).
        assert scene.floors[0].centroid[0] == pytest.approx(2.5, rel=1e-6)
        assert scene.floors[0].centroid[1] == pytest.approx(2.0, rel=1e-6)

    def test_floor_z_offset_above_ground(self):
        room = _room([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        sheet = StructuredSheet(
            sheet_number="R", units=Units.METERS, elements=[room]
        )
        scene = reconstruct_sheet(sheet)
        zs = scene.floors[0].vertices[2::3]
        assert all(z > 0 for z in zs)  # z-offset applied
        assert max(zs) < 0.01  # but small


class TestBooleanFailureRecovery:
    def test_boolean_failure_emits_wall_and_marks_opening_failed(self):
        sheet, walls, _ = _four_wall_square(10.0)
        w_bot = walls[0]
        door = Door(
            width=0.9,
            height=2.1,
            host_wall_id=w_bot.id,
            properties={"parametric_position": 0.5},
        )
        sheet.elements.append(door)

        # Force trimesh.boolean.difference to blow up. The reconstruct
        # code should fall back to emitting the uncut wall and mark
        # the opening failed=True.
        import atlas_core.reconstruct3d as r3d

        def boom(*_a, **_kw):
            raise RuntimeError("synthetic boolean failure")

        with patch.object(r3d.trimesh.boolean, "difference", side_effect=boom):
            scene = reconstruct_sheet(sheet)

        # Still four walls, each a plain box (no cut).
        assert len(scene.walls) == 4
        for wm in scene.walls:
            assert len(wm.vertices) // 3 == 8

        # Opening is recorded but marked failed.
        assert len(scene.openings) == 1
        assert scene.openings[0].failed is True


class TestRoomAssociation:
    def test_walls_get_room_ids_when_on_boundary(self):
        sheet, walls, room = _four_wall_square(10.0)
        scene = reconstruct_sheet(sheet)
        # Every wall sits on the room's boundary.
        for wm in scene.walls:
            assert str(room.id) in wm.room_ids

    def test_wall_off_boundary_has_no_room(self):
        # Room covers (0..10, 0..10). Put a wall at y=20 — well outside.
        room = _room([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
        stray = _wall([(0.0, 20.0), (10.0, 20.0)])
        sheet = StructuredSheet(
            sheet_number="S",
            units=Units.METERS,
            elements=[room, stray],
        )
        scene = reconstruct_sheet(sheet)
        stray_mesh = next(w for w in scene.walls if w.parent_wall_id == str(stray.id))
        assert stray_mesh.room_ids == []


class TestOpeningPlacement:
    def test_parametric_position_picks_correct_segment(self):
        # Two-segment horizontal polyline: (0,0) → (10,0) → (20,0), total 20m.
        # A door at parametric=0.75 → abs=15m → segment index 1, local_t=0.5.
        wall = _wall([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])
        door = Door(
            width=0.9,
            height=2.1,
            host_wall_id=wall.id,
            properties={"parametric_position": 0.75},
        )
        sheet = StructuredSheet(
            sheet_number="P",
            units=Units.METERS,
            elements=[wall, door],
        )
        scene = reconstruct_sheet(sheet)
        # Door should be centered at x=15 in world space.
        op_bbox = scene.openings[0].bbox
        center_x = 0.5 * (op_bbox.min[0] + op_bbox.max[0])
        assert center_x == pytest.approx(15.0, abs=1e-6)

        # The second segment's wall mesh is the one with the cut (not a plain box).
        second = [
            w for w in scene.walls
            if w.parent_wall_id == str(wall.id) and len(w.vertices) // 3 > 8
        ]
        assert len(second) == 1

    def test_bbox_center_used_when_parametric_absent(self):
        wall = _wall([(0.0, 0.0), (10.0, 0.0)])
        door = Door(
            width=0.9,
            height=2.1,
            host_wall_id=wall.id,
            # No properties['parametric_position'] — relies on bbox projection.
            bbox=BoundingBox(minx=7.55, miny=-0.05, maxx=8.45, maxy=0.05),
        )
        sheet = StructuredSheet(
            sheet_number="B",
            units=Units.METERS,
            elements=[wall, door],
        )
        scene = reconstruct_sheet(sheet)
        op = scene.openings[0]
        center_x = 0.5 * (op.bbox.min[0] + op.bbox.max[0])
        assert center_x == pytest.approx(8.0, abs=1e-6)

    def test_unplaceable_opening_is_skipped(self):
        # No host_wall_id → can't place → dropped entirely.
        wall = _wall([(0.0, 0.0), (10.0, 0.0)])
        door = Door(width=0.9, height=2.1)
        sheet = StructuredSheet(
            sheet_number="X",
            units=Units.METERS,
            elements=[wall, door],
        )
        scene = reconstruct_sheet(sheet)
        assert scene.openings == []

    def test_opening_on_host_without_locator_is_skipped(self):
        # Has host_wall_id but no parametric_position and no bbox.
        wall = _wall([(0.0, 0.0), (10.0, 0.0)])
        door = Door(width=0.9, height=2.1, host_wall_id=wall.id)
        sheet = StructuredSheet(
            sheet_number="Y",
            units=Units.METERS,
            elements=[wall, door],
        )
        scene = reconstruct_sheet(sheet)
        # Wall still emitted; opening silently dropped (can't place it).
        assert len(scene.walls) == 1
        assert scene.openings == []


class TestWallOverrides:
    def test_wall_thickness_and_height_overrides(self):
        # Wall with explicit thickness 0.30m and height 3.00m.
        wall = Wall(
            centerline=Polyline(points=[Point(x=0, y=0), Point(x=5, y=0)]),
            thickness=0.30,
            height=3.00,
        )
        sheet = StructuredSheet(
            sheet_number="T", units=Units.METERS, elements=[wall]
        )
        scene = reconstruct_sheet(sheet)
        ys = scene.walls[0].vertices[1::3]
        zs = scene.walls[0].vertices[2::3]
        assert max(ys) - min(ys) == pytest.approx(0.30, rel=1e-6)
        assert max(zs) == pytest.approx(3.00, rel=1e-6)

    def test_wall_with_all_zero_length_segments_skipped(self):
        # Polyline where every consecutive pair is identical → no real segments.
        wall = _wall([(1.0, 1.0), (1.0, 1.0), (1.0, 1.0)])
        sheet = StructuredSheet(
            sheet_number="Z", units=Units.METERS, elements=[wall]
        )
        scene = reconstruct_sheet(sheet)
        assert scene.walls == []


class TestDoorLocatorFallback:
    def test_non_numeric_parametric_falls_through_to_bbox(self):
        # Extractor dumped something non-numeric under the parametric key.
        # We should fall back to the bbox-center projection path.
        wall = _wall([(0.0, 0.0), (10.0, 0.0)])
        door = Door(
            width=0.9,
            height=2.1,
            host_wall_id=wall.id,
            properties={"parametric_position": "??"},
            bbox=BoundingBox(minx=2.55, miny=-0.05, maxx=3.45, maxy=0.05),
        )
        sheet = StructuredSheet(
            sheet_number="F", units=Units.METERS, elements=[wall, door]
        )
        scene = reconstruct_sheet(sheet)
        center_x = 0.5 * (scene.openings[0].bbox.min[0] + scene.openings[0].bbox.max[0])
        # Center of the bbox was (3.0, 0) → parametric 0.3 → center_x = 3.0.
        assert center_x == pytest.approx(3.0, abs=1e-6)


class TestWindowDefaults:
    def test_window_uses_default_height_and_sill(self):
        # Window with no explicit height or sill — both come from defaults.
        wall = _wall([(0.0, 0.0), (10.0, 0.0)])
        window = Window(
            width=1.0,
            host_wall_id=wall.id,
            properties={"parametric_position": 0.5},
        )
        sheet = StructuredSheet(
            sheet_number="WD", units=Units.METERS, elements=[wall, window]
        )
        scene = reconstruct_sheet(sheet)
        op = scene.openings[0]
        assert op.bbox.min[2] == pytest.approx(0.91, abs=1e-6)  # default sill
        assert op.bbox.max[2] == pytest.approx(0.91 + 1.22, abs=1e-6)  # + default height


class TestJSONSerialisable:
    def test_scene_round_trips_through_json(self):
        sheet, _, _ = _four_wall_square(8.0)
        scene = reconstruct_sheet(sheet)
        # model_dump_json should work without a custom encoder.
        js = scene.model_dump_json()
        assert '"units":"m"' in js
        assert '"walls"' in js
        assert '"floors"' in js

        # And round-trip back to a model.
        parsed = Scene3D.model_validate_json(js)
        assert len(parsed.walls) == len(scene.walls)
        assert len(parsed.floors) == len(scene.floors)
