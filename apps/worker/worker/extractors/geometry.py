"""Geometric validators for extracted building elements.

These functions confirm or refute element classifications produced
by :mod:`worker.extractors.ncs` (or by any other classifier). They
work on bare 2D primitives — points as ``(x, y)`` tuples, line
segments as ``(p0, p1)``, arcs as a center + radius + angular
extent — so they're trivially testable from synthetic inputs and
have no shapely / numpy dependency.

Three families:

- :func:`lines_parallel` — parallelism test for two segments, with
  perpendicular distance returned. The double-line pattern is the
  cheapest signal for "this is a wall" in 2D plans.
- :func:`is_door_swing` — does an arc + line pair look like a door
  in plan view (arc centered on one line endpoint, radius matching
  the line length, sensible swing angle)?
- :func:`find_closed_loop` — given a set of wall segments, do they
  form a single closed loop (a room boundary)? Returns the ordered
  ring or ``None``.

Tolerances are explicit parameters with sensible defaults — caller
controls how strict to be.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

Point = tuple[float, float]
Segment = tuple[Point, Point]


# --------------------------------------------------------------------------
# Wall detection: parallel double-lines
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParallelismResult:
    """Outcome of :func:`lines_parallel`.

    ``angle_diff_rad`` is the absolute angle between the two segments
    (always in ``[0, π/2]`` because direction is irrelevant).
    ``perpendicular_distance`` is the shortest distance between the
    two parallel lines if they are parallel, else ``None``.
    ``confidence`` is in ``[0, 1]``: 1.0 for perfect parallel within
    the tolerance, decreasing linearly to 0.0 at the tolerance edge.
    """

    is_parallel: bool
    angle_diff_rad: float
    perpendicular_distance: float | None
    confidence: float


def _segment_angle(seg: Segment) -> float:
    """Angle of the segment, normalized to ``[0, π)``."""
    (x0, y0), (x1, y1) = seg
    a = math.atan2(y1 - y0, x1 - x0)
    if a < 0:
        a += math.pi
    if a >= math.pi:
        a -= math.pi
    return a


def _point_to_line_distance(p: Point, line: Segment) -> float:
    """Perpendicular distance from ``p`` to the infinite line through ``line``."""
    (x0, y0), (x1, y1) = line
    px, py = p
    dx, dy = x1 - x0, y1 - y0
    norm = math.hypot(dx, dy)
    if norm == 0:
        return math.hypot(px - x0, py - y0)
    # Cross-product magnitude / |line|
    return abs(dy * (px - x0) - dx * (py - y0)) / norm


def lines_parallel(
    a: Segment,
    b: Segment,
    *,
    angle_tol_rad: float = math.radians(2.0),
    max_distance: float | None = None,
) -> ParallelismResult:
    """Are two segments parallel within ``angle_tol_rad``?

    If ``max_distance`` is given, segments farther apart than that
    are reported as not parallel even if their angles match — useful
    for pruning candidate wall pairs by likely thickness range.
    """
    angle_a = _segment_angle(a)
    angle_b = _segment_angle(b)
    diff = abs(angle_a - angle_b)
    diff = min(diff, math.pi - diff)  # fold to [0, π/2]

    if diff > angle_tol_rad:
        return ParallelismResult(
            is_parallel=False,
            angle_diff_rad=diff,
            perpendicular_distance=None,
            confidence=0.0,
        )

    # Distance from one endpoint of b to the infinite line of a; for
    # parallel lines this is the perpendicular distance between them.
    distance = _point_to_line_distance(b[0], a)

    if max_distance is not None and distance > max_distance:
        return ParallelismResult(
            is_parallel=False,
            angle_diff_rad=diff,
            perpendicular_distance=distance,
            confidence=0.0,
        )

    confidence = 1.0 - (diff / angle_tol_rad) if angle_tol_rad > 0 else 1.0
    return ParallelismResult(
        is_parallel=True,
        angle_diff_rad=diff,
        perpendicular_distance=distance,
        confidence=max(0.0, min(1.0, confidence)),
    )


# --------------------------------------------------------------------------
# Door detection: arc + line pair
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DoorSwingResult:
    """Outcome of :func:`is_door_swing`."""

    is_valid_swing: bool
    confidence: float
    reason: str


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def is_door_swing(
    line: Segment,
    arc_center: Point,
    arc_radius: float,
    arc_sweep_deg: float,
    *,
    radius_tol: float = 0.1,  # ±10% of line length
    center_tol: float = 0.05,  # arc center must lie within this fraction of line length
    min_sweep_deg: float = 30.0,
    max_sweep_deg: float = 180.0,
) -> DoorSwingResult:
    """Does this line + arc look like a door swing?

    Plan-view doors are drawn as a line (the closed door position) plus
    an arc (the swing path). For the pair to qualify:

    - the arc's center must coincide (within tolerance) with one of
      the line's endpoints (the hinge),
    - the arc's radius must match the line's length (the door's
      width) within ``radius_tol``,
    - the swing must be a meaningful angular span — narrow enough that
      it isn't a full circle (which would be an annotation symbol),
      wide enough to be a real door (typically 60-180°).
    """
    line_length = _distance(line[0], line[1])
    if line_length == 0:
        return DoorSwingResult(False, 0.0, "Line has zero length")

    # 1. Arc center must sit on (or near) one endpoint.
    d_to_a = _distance(arc_center, line[0])
    d_to_b = _distance(arc_center, line[1])
    hinge_dist = min(d_to_a, d_to_b)
    if hinge_dist > center_tol * line_length:
        return DoorSwingResult(
            False,
            0.0,
            f"Arc center is {hinge_dist:.3f} from nearest line endpoint "
            f"(tol {center_tol * line_length:.3f}).",
        )

    # 2. Arc radius must match line length.
    radius_err = abs(arc_radius - line_length) / line_length
    if radius_err > radius_tol:
        return DoorSwingResult(
            False,
            0.0,
            f"Arc radius {arc_radius:.3f} != line length {line_length:.3f} "
            f"({radius_err * 100:.1f}% off, tol {radius_tol * 100:.1f}%).",
        )

    # 3. Swept angle must be in the door-swing range.
    sweep = abs(arc_sweep_deg)
    if sweep < min_sweep_deg or sweep > max_sweep_deg:
        return DoorSwingResult(
            False,
            0.0,
            f"Sweep {sweep:.1f}° outside door range "
            f"[{min_sweep_deg:.0f}°, {max_sweep_deg:.0f}°].",
        )

    # Confidence: blend geometric closeness scores.
    hinge_score = 1.0 - (hinge_dist / (center_tol * line_length))
    radius_score = 1.0 - (radius_err / radius_tol)
    # Sweep score: peak at 90° (the canonical door drawing), decays
    # toward the edges of the acceptable band.
    sweep_score = 1.0 - abs(sweep - 90.0) / 90.0
    confidence = max(0.0, min(1.0, (hinge_score + radius_score + sweep_score) / 3.0))

    return DoorSwingResult(
        is_valid_swing=True,
        confidence=confidence,
        reason="Valid door swing pattern.",
    )


# --------------------------------------------------------------------------
# Room detection: closed wall loops
# --------------------------------------------------------------------------


def _snap_point(
    p: Point, snapped: dict[Point, Point], tol: float
) -> Point:
    """Find or create the canonical position for ``p`` within ``tol``."""
    for q in snapped:
        if abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol:
            return q
    snapped[p] = p
    return p


def find_closed_loop(
    walls: Iterable[Segment],
    *,
    snap_tol: float = 0.01,
) -> list[Point] | None:
    """If ``walls`` form a single closed loop, return its ordered ring.

    Returns ``None`` when the walls don't form a single connected
    closed loop. Endpoints within ``snap_tol`` of each other are
    treated as the same vertex (so hand-drawn or floating-point-noisy
    inputs work).

    Multi-room face finding (planar graph decomposition) is *out of
    scope for Phase 2* — that needs a real spatial planner and is
    deferred to the worker job in Phase 3. This function is the
    cheap sanity check: "do these N walls fence in exactly one
    room?"
    """
    walls_list = list(walls)
    if not walls_list:
        return None

    # Snap all endpoints to canonical positions.
    snapped: dict[Point, Point] = {}
    edges: list[tuple[Point, Point]] = []
    for a, b in walls_list:
        sa = _snap_point(a, snapped, snap_tol)
        sb = _snap_point(b, snapped, snap_tol)
        if sa == sb:
            return None  # zero-length wall after snapping
        edges.append((sa, sb))

    # Build adjacency: each point lists its neighbors and the edge
    # index that connects them.
    adj: dict[Point, list[tuple[Point, int]]] = {}
    for i, (a, b) in enumerate(edges):
        adj.setdefault(a, []).append((b, i))
        adj.setdefault(b, []).append((a, i))

    # For a single closed loop every vertex must have degree 2.
    if any(len(neighbors) != 2 for neighbors in adj.values()):
        return None

    # Walk the loop, consuming each edge exactly once.
    start = next(iter(adj))
    ring: list[Point] = [start]
    used: set[int] = set()
    current = start
    while True:
        choices = [(p, i) for (p, i) in adj[current] if i not in used]
        if not choices:
            break
        next_pt, edge_idx = choices[0]
        used.add(edge_idx)
        if next_pt == start:
            break
        ring.append(next_pt)
        current = next_pt

    # All edges must have been consumed (rules out disconnected
    # components like two separate rooms presented together).
    if len(used) != len(edges):
        return None

    return ring


def polygon_area(ring: list[Point]) -> float:
    """Signed shoelace area of a ring; sign indicates orientation."""
    if len(ring) < 3:
        return 0.0
    s = 0.0
    for i in range(len(ring)):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % len(ring)]
        s += x0 * y1 - x1 * y0
    return s / 2.0
