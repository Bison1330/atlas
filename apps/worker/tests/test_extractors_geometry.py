"""Tests for the geometric validators."""

from __future__ import annotations

import math

import pytest

from worker.extractors import geometry as g

# --------------------------------------------------------------------------
# lines_parallel
# --------------------------------------------------------------------------


class TestLinesParallel:
    def test_identical_horizontal_lines_parallel(self):
        a = ((0.0, 0.0), (10.0, 0.0))
        b = ((0.0, 1.0), (10.0, 1.0))
        result = g.lines_parallel(a, b)
        assert result.is_parallel
        assert result.angle_diff_rad == pytest.approx(0.0)
        assert result.perpendicular_distance == pytest.approx(1.0)
        assert result.confidence == pytest.approx(1.0)

    def test_perpendicular_lines_not_parallel(self):
        a = ((0.0, 0.0), (10.0, 0.0))
        b = ((0.0, 0.0), (0.0, 10.0))
        result = g.lines_parallel(a, b)
        assert not result.is_parallel
        assert result.confidence == 0.0
        assert result.perpendicular_distance is None

    def test_opposite_direction_still_parallel(self):
        # Same line, reversed direction — angle_diff should fold to 0.
        a = ((0.0, 0.0), (10.0, 0.0))
        b = ((10.0, 1.0), (0.0, 1.0))
        result = g.lines_parallel(a, b)
        assert result.is_parallel
        assert result.angle_diff_rad == pytest.approx(0.0)

    def test_within_angle_tolerance(self):
        # 1° offset — well within default 2° tolerance.
        a = ((0.0, 0.0), (10.0, 0.0))
        offset = math.radians(1.0)
        b = (
            (0.0, 1.0),
            (10.0 * math.cos(offset), 10.0 * math.sin(offset) + 1.0),
        )
        result = g.lines_parallel(a, b)
        assert result.is_parallel
        # Confidence falls off proportionally with angle error.
        assert 0.4 < result.confidence < 0.6

    def test_just_outside_angle_tolerance(self):
        # 5° offset — outside default 2° tolerance.
        a = ((0.0, 0.0), (10.0, 0.0))
        offset = math.radians(5.0)
        b = (
            (0.0, 1.0),
            (10.0 * math.cos(offset), 10.0 * math.sin(offset) + 1.0),
        )
        result = g.lines_parallel(a, b)
        assert not result.is_parallel

    def test_max_distance_filter_rejects_distant_pair(self):
        a = ((0.0, 0.0), (10.0, 0.0))
        b = ((0.0, 50.0), (10.0, 50.0))
        result = g.lines_parallel(a, b, max_distance=1.0)
        assert not result.is_parallel
        # Distance is still reported even when rejection is by distance.
        assert result.perpendicular_distance == pytest.approx(50.0)

    def test_diagonal_parallel_pair(self):
        a = ((0.0, 0.0), (10.0, 10.0))
        b = ((1.0, 0.0), (11.0, 10.0))  # parallel, offset by 1 unit perpendicular
        result = g.lines_parallel(a, b)
        assert result.is_parallel
        # Perpendicular distance for a 45° line offset by (1, 0) is √2 / 2.
        assert result.perpendicular_distance == pytest.approx(
            math.sqrt(2) / 2, rel=1e-3
        )


# --------------------------------------------------------------------------
# is_door_swing
# --------------------------------------------------------------------------


class TestIsDoorSwing:
    def test_canonical_90deg_door(self):
        # Door 3 ft wide hinged at origin, 90° swing.
        line = ((0.0, 0.0), (3.0, 0.0))
        result = g.is_door_swing(
            line, arc_center=(0.0, 0.0), arc_radius=3.0, arc_sweep_deg=90.0
        )
        assert result.is_valid_swing
        # Canonical 90° swing should score near peak.
        assert result.confidence > 0.9

    def test_arc_center_at_other_endpoint(self):
        line = ((0.0, 0.0), (3.0, 0.0))
        result = g.is_door_swing(
            line, arc_center=(3.0, 0.0), arc_radius=3.0, arc_sweep_deg=90.0
        )
        assert result.is_valid_swing  # hinge can be either end

    def test_radius_mismatch_rejects(self):
        line = ((0.0, 0.0), (3.0, 0.0))
        # Radius 5.0 != line length 3.0 (66% off, way over default 10% tol).
        result = g.is_door_swing(
            line, arc_center=(0.0, 0.0), arc_radius=5.0, arc_sweep_deg=90.0
        )
        assert not result.is_valid_swing
        assert result.confidence == 0.0
        assert "radius" in result.reason.lower()

    def test_arc_center_offset_rejects(self):
        line = ((0.0, 0.0), (3.0, 0.0))
        # Center way off either endpoint.
        result = g.is_door_swing(
            line, arc_center=(1.5, 0.0), arc_radius=3.0, arc_sweep_deg=90.0
        )
        assert not result.is_valid_swing
        assert "endpoint" in result.reason.lower()

    def test_full_circle_rejects(self):
        line = ((0.0, 0.0), (3.0, 0.0))
        # 360° sweep — that's a circle annotation, not a door.
        result = g.is_door_swing(
            line, arc_center=(0.0, 0.0), arc_radius=3.0, arc_sweep_deg=360.0
        )
        assert not result.is_valid_swing
        assert "sweep" in result.reason.lower()

    def test_sliver_sweep_rejects(self):
        line = ((0.0, 0.0), (3.0, 0.0))
        # 10° is too narrow to be a real door.
        result = g.is_door_swing(
            line, arc_center=(0.0, 0.0), arc_radius=3.0, arc_sweep_deg=10.0
        )
        assert not result.is_valid_swing

    def test_zero_length_line_rejects(self):
        result = g.is_door_swing(
            ((0.0, 0.0), (0.0, 0.0)),
            arc_center=(0.0, 0.0),
            arc_radius=3.0,
            arc_sweep_deg=90.0,
        )
        assert not result.is_valid_swing

    def test_within_radius_tolerance(self):
        # 5% radius mismatch — within default 10%, accepted but
        # confidence below the canonical case.
        line = ((0.0, 0.0), (3.0, 0.0))
        result = g.is_door_swing(
            line, arc_center=(0.0, 0.0), arc_radius=3.15, arc_sweep_deg=90.0
        )
        assert result.is_valid_swing
        assert 0.5 < result.confidence < 0.95


# --------------------------------------------------------------------------
# find_closed_loop
# --------------------------------------------------------------------------


class TestFindClosedLoop:
    def test_perfect_square(self):
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 10.0)),
            ((10.0, 10.0), (0.0, 10.0)),
            ((0.0, 10.0), (0.0, 0.0)),
        ]
        ring = g.find_closed_loop(walls)
        assert ring is not None
        assert len(ring) == 4
        # All four corners present (order may vary).
        assert set(ring) == {(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)}

    def test_loop_with_endpoint_noise_within_tolerance(self):
        # Endpoints don't quite match — but within snap tolerance.
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.001, 0.0), (10.0, 10.0)),
            ((10.0, 10.001), (0.0, 10.0)),
            ((0.001, 10.0), (0.0, 0.0)),
        ]
        ring = g.find_closed_loop(walls, snap_tol=0.01)
        assert ring is not None
        assert len(ring) == 4

    def test_open_chain_returns_none(self):
        # Three walls, but the fourth side is missing.
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 10.0)),
            ((10.0, 10.0), (0.0, 10.0)),
        ]
        assert g.find_closed_loop(walls) is None

    def test_two_disconnected_loops_returns_none(self):
        # Two squares — function only detects single connected loops.
        walls = [
            # Square 1
            ((0.0, 0.0), (1.0, 0.0)),
            ((1.0, 0.0), (1.0, 1.0)),
            ((1.0, 1.0), (0.0, 1.0)),
            ((0.0, 1.0), (0.0, 0.0)),
            # Square 2 (well clear of square 1)
            ((10.0, 10.0), (11.0, 10.0)),
            ((11.0, 10.0), (11.0, 11.0)),
            ((11.0, 11.0), (10.0, 11.0)),
            ((10.0, 11.0), (10.0, 10.0)),
        ]
        assert g.find_closed_loop(walls) is None

    def test_t_junction_returns_none(self):
        # A junction where one vertex has degree 3 — not a single loop.
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (10.0, 10.0)),
            ((10.0, 10.0), (0.0, 10.0)),
            ((0.0, 10.0), (0.0, 0.0)),
            ((10.0, 0.0), (20.0, 0.0)),  # extra branch off (10, 0)
        ]
        assert g.find_closed_loop(walls) is None

    def test_empty_input_returns_none(self):
        assert g.find_closed_loop([]) is None

    def test_zero_length_wall_returns_none(self):
        walls = [
            ((0.0, 0.0), (0.0, 0.0)),  # collapses to a point
            ((0.0, 0.0), (1.0, 0.0)),
        ]
        assert g.find_closed_loop(walls) is None

    def test_triangle_loop(self):
        walls = [
            ((0.0, 0.0), (10.0, 0.0)),
            ((10.0, 0.0), (5.0, 8.66)),
            ((5.0, 8.66), (0.0, 0.0)),
        ]
        ring = g.find_closed_loop(walls)
        assert ring is not None
        assert len(ring) == 3


# --------------------------------------------------------------------------
# polygon_area
# --------------------------------------------------------------------------


class TestPolygonArea:
    def test_unit_square_ccw(self):
        ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        assert g.polygon_area(ring) == pytest.approx(1.0)

    def test_unit_square_cw_is_negative(self):
        ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
        assert g.polygon_area(ring) == pytest.approx(-1.0)

    def test_triangle(self):
        ring = [(0.0, 0.0), (4.0, 0.0), (0.0, 3.0)]
        assert abs(g.polygon_area(ring)) == pytest.approx(6.0)

    def test_degenerate_returns_zero(self):
        assert g.polygon_area([(0.0, 0.0), (1.0, 1.0)]) == 0.0
        assert g.polygon_area([]) == 0.0
