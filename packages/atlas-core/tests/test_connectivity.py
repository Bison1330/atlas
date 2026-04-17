"""Tests for the connectivity geometric algorithms."""

from __future__ import annotations

import pytest

from atlas_core import connectivity as c

# ---------- door-to-wall hosting ----------


class TestHostWallsForDoors:
    def test_door_on_a_wall_segment(self):
        # Door hinge sits exactly on a wall.
        walls = [((0.0, 0.0), (10.0, 0.0))]
        doors = [(5.0, 0.0)]
        results = c.host_walls_for_doors(doors, walls)
        assert results[0].wall_index == 0
        assert results[0].distance == pytest.approx(0.0)
        assert results[0].parametric_position == pytest.approx(0.5)

    def test_door_near_one_of_many_walls(self):
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),   # bottom
            ((10.0, 0.0), (10.0, 10.0)), # right
            ((10.0, 10.0), (0.0, 10.0)), # top
            ((0.0, 10.0), (0.0, 0.0)),   # left
        ]
        doors = [(7.0, 10.05)]  # near the top wall
        results = c.host_walls_for_doors(doors, walls)
        assert results[0].wall_index == 2

    def test_door_too_far_from_any_wall_unhosted(self):
        walls = [((0.0, 0.0), (10.0, 0.0))]
        doors = [(5.0, 5.0)]  # way off the wall
        results = c.host_walls_for_doors(doors, walls, max_distance=0.5)
        assert results[0].wall_index is None

    def test_clamps_to_segment_endpoints(self):
        # A point past the wall's endpoint shouldn't match it just because
        # it's on the infinite line.
        walls = [((0.0, 0.0), (10.0, 0.0))]
        doors = [(15.0, 0.0)]
        results = c.host_walls_for_doors(doors, walls, max_distance=0.5)
        assert results[0].wall_index is None
        assert results[0].distance == pytest.approx(5.0)

    def test_multiple_doors_each_get_own_result(self):
        walls = [((0.0, 0.0), (10.0, 0.0)), ((0.0, 5.0), (10.0, 5.0))]
        doors = [(2.0, 0.05), (8.0, 5.05)]
        results = c.host_walls_for_doors(doors, walls)
        assert results[0].wall_index == 0
        assert results[1].wall_index == 1


# ---------- wall splitting at intersections ----------


class TestSplitWallsAtIntersections:
    def test_no_intersections_passes_through(self):
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((20.0, 0.0), (30.0, 0.0)),
        ]
        out = c.split_walls_at_intersections(walls)
        assert len(out) == 2

    def test_t_junction_splits_through_wall(self):
        # Horizontal wall passing through a T-junction with a vertical.
        walls = [
            ((0.0, 5.0), (10.0, 5.0)),  # gets split at (5, 5)
            ((5.0, 5.0), (5.0, 10.0)),  # endpoint at (5, 5)
        ]
        out = c.split_walls_at_intersections(walls)
        # The horizontal becomes 2 segments; the vertical stays as 1.
        assert len(out) == 3
        # The two halves of the horizontal share the (5, 5) vertex.
        horizontals = [w for w in out if w[0][1] == 5.0 and w[1][1] == 5.0]
        assert len(horizontals) == 2
        endpoints = {p for w in horizontals for p in w}
        assert (5.0, 5.0) in endpoints

    def test_cross_junction_splits_both(self):
        walls = [
            ((0.0, 5.0), (10.0, 5.0)),
            ((5.0, 0.0), (5.0, 10.0)),
        ]
        out = c.split_walls_at_intersections(walls)
        assert len(out) == 4  # each becomes 2

    def test_endpoint_touching_doesnt_double_split(self):
        # Two walls sharing an endpoint at the meeting point — already a vertex.
        walls = [
            ((0.0, 0.0), (5.0, 0.0)),
            ((5.0, 0.0), (10.0, 0.0)),
        ]
        out = c.split_walls_at_intersections(walls)
        assert len(out) == 2


# ---------- room derivation ----------


class TestDeriveRoomsFromWalls:
    def test_single_room_perimeter(self):
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 8.0)),
            ((10.0, 8.0), (0.0, 8.0)),
            ((0.0, 8.0), (0.0, 0.0)),
        ]
        rooms = c.derive_rooms_from_walls(walls)
        assert len(rooms) == 1
        assert rooms[0].area == pytest.approx(80.0)
        assert rooms[0].bbox == (0.0, 0.0, 10.0, 8.0)

    def test_two_rooms_split_by_partition(self):
        # 10x10 box split vertically at x=5.
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 10.0)),
            ((10.0, 10.0), (0.0, 10.0)),
            ((0.0, 10.0), (0.0, 0.0)),
            ((5.0, 0.0), (5.0, 10.0)),
        ]
        rooms = c.derive_rooms_from_walls(walls)
        assert len(rooms) == 2
        # Each room is 5x10 = 50 sq units.
        for r in rooms:
            assert r.area == pytest.approx(50.0)

    def test_three_rooms_t_junction(self):
        # Mirrors build_three_room_floor — top row is split into two
        # rooms (R1, R2), bottom is one big room (R3).
        walls = [
            # Exterior
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 10.0)),
            ((10.0, 10.0), (0.0, 10.0)),
            ((0.0, 10.0), (0.0, 0.0)),
            # Horizontal partition at y=5 (continuous, will be split at x=5)
            ((0.0, 5.0), (10.0, 5.0)),
            # Vertical partition between R1 and R2 in the upper half
            ((5.0, 5.0), (5.0, 10.0)),
        ]
        rooms = c.derive_rooms_from_walls(walls)
        assert len(rooms) == 3
        areas = sorted(r.area for r in rooms)
        # R1=25, R2=25, R3=50
        assert areas == pytest.approx([25.0, 25.0, 50.0])

    def test_unclosed_walls_produce_no_rooms(self):
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 10.0)),
            ((10.0, 10.0), (0.0, 10.0)),
            # No fourth wall; not a closed loop.
        ]
        rooms = c.derive_rooms_from_walls(walls)
        assert rooms == []

    def test_endpoint_noise_within_snap_tolerance(self):
        # Wall endpoints don't quite meet — within snap tolerance, should still close.
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.001, 0.0), (10.0, 10.0)),
            ((10.0, 10.005), (0.0, 10.0)),
            ((0.001, 10.0), (0.0, 0.0)),
        ]
        rooms = c.derive_rooms_from_walls(walls, snap_tol=0.01)
        assert len(rooms) == 1
        assert rooms[0].area == pytest.approx(100.0, rel=0.01)


# ---------- room adjacency ----------


class TestRoomAdjacencyViaDoors:
    def test_door_between_two_rooms(self):
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 5.0)),
            ((10.0, 5.0), (0.0, 5.0)),
            ((0.0, 5.0), (0.0, 0.0)),
            ((0.0, 5.0), (10.0, 5.0)),  # duplicate ish? no — separates from below
        ]
        # Easier: build it as a clean two-room plan.
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 10.0)),
            ((10.0, 10.0), (0.0, 10.0)),
            ((0.0, 10.0), (0.0, 0.0)),
            ((0.0, 5.0), (10.0, 5.0)),  # horizontal partition
        ]
        rooms = c.derive_rooms_from_walls(walls)
        assert len(rooms) == 2

        # Door on the partition wall.
        doors = [(5.0, 5.0)]
        adj = c.room_adjacency_via_doors(rooms, doors)
        assert len(adj) == 1
        assert adj[0].room_a_index != adj[0].room_b_index
        assert adj[0].door_index == 0

    def test_door_on_exterior_wall_not_an_edge(self):
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 10.0)),
            ((10.0, 10.0), (0.0, 10.0)),
            ((0.0, 10.0), (0.0, 0.0)),
        ]
        rooms = c.derive_rooms_from_walls(walls)
        # Door on bottom exterior wall — touches one room only.
        doors = [(5.0, 0.0)]
        adj = c.room_adjacency_via_doors(rooms, doors)
        assert adj == []

    def test_three_room_plan_yields_two_edges(self):
        # Mirrors build_three_room_floor with two interior doors at y=5.
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 10.0)),
            ((10.0, 10.0), (0.0, 10.0)),
            ((0.0, 10.0), (0.0, 0.0)),
            ((0.0, 5.0), (10.0, 5.0)),
            ((5.0, 5.0), (5.0, 10.0)),
        ]
        rooms = c.derive_rooms_from_walls(walls)
        assert len(rooms) == 3
        # R1 at (2.5, 7.5), R2 at (7.5, 7.5), R3 at (5, 2.5).
        # Doors at (2.5, 5) and (7.5, 5) connect R1↔R3 and R2↔R3.
        doors = [(2.5, 5.0), (7.5, 5.0)]
        adj = c.room_adjacency_via_doors(rooms, doors)
        assert len(adj) == 2

        # The big room (R3, area=50) should be in BOTH edges.
        # Find the index of the largest-area room (sort key in derive_).
        # rooms[0] is the largest by sort.
        big_room = 0
        for edge in adj:
            assert big_room in (edge.room_a_index, edge.room_b_index)


# ---------- end-to-end on synthetic fixture geometry ----------


class TestEndToEnd:
    def test_pipeline_on_three_room_geometry(self):
        """Hosting + derivation + adjacency all run cleanly on the fixture geometry."""
        walls: list[c.Segment] = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 10.0)),
            ((10.0, 10.0), (0.0, 10.0)),
            ((0.0, 10.0), (0.0, 0.0)),
            ((0.0, 5.0), (10.0, 5.0)),
            ((5.0, 5.0), (5.0, 10.0)),
        ]
        doors = [(2.5, 5.0), (7.5, 5.0)]

        # Hosting — the y=5 horizontal wall hosts both interior doors.
        # NOTE: post-split the horizontal wall is two segments; we still
        # report the original input wall index for hosting.
        hosting = c.host_walls_for_doors(doors, walls)
        # Both should host on wall index 4 (the y=5 line in the input list).
        assert hosting[0].wall_index == 4
        assert hosting[1].wall_index == 4

        rooms = c.derive_rooms_from_walls(walls)
        assert len(rooms) == 3

        adj = c.room_adjacency_via_doors(rooms, doors)
        assert len(adj) == 2


# ---------- helpers ----------


class TestPointToSegmentDistance:
    def test_perpendicular_distance(self):
        d, t = c._point_to_segment_distance((5.0, 3.0), ((0.0, 0.0), (10.0, 0.0)))
        assert d == pytest.approx(3.0)
        assert t == pytest.approx(0.5)

    def test_clamps_at_endpoints(self):
        d, t = c._point_to_segment_distance((-5.0, 0.0), ((0.0, 0.0), (10.0, 0.0)))
        assert d == pytest.approx(5.0)
        assert t == pytest.approx(0.0)
        d, t = c._point_to_segment_distance((15.0, 0.0), ((0.0, 0.0), (10.0, 0.0)))
        assert d == pytest.approx(5.0)
        assert t == pytest.approx(1.0)

    def test_zero_length_segment(self):
        d, t = c._point_to_segment_distance((3.0, 4.0), ((0.0, 0.0), (0.0, 0.0)))
        assert d == pytest.approx(5.0)
        assert t == pytest.approx(0.0)


class TestSignedArea:
    def test_ccw_positive(self):
        ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        assert c._signed_area(ring) == pytest.approx(100.0)

    def test_cw_negative(self):
        ring = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]
        assert c._signed_area(ring) == pytest.approx(-100.0)

    def test_collinear_zero(self):
        ring = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]
        assert c._signed_area(ring) == pytest.approx(0.0)


# Cross-check between the dxf_builders fixture and the connectivity
# algorithms lives in test_jobs_extract_connectivity (where the
# orchestrator + DB end-to-end test runs the full pipeline).
