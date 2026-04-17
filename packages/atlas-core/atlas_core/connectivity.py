"""Geometric connectivity analysis on extracted elements.

Three concerns, in strict dependency order:

1. **Door-to-wall hosting** — for each door arc, identify the wall
   it sits in. Geometric: nearest wall to the arc's hinge point,
   within a tolerance. Outputs a host wall index + parametric
   position along that wall.

2. **Room derivation** — find the planar faces of the wall graph.
   Walls are split at every intersection so T-junctions become
   real vertices, then a half-edge traversal walks each face. The
   outer (boundary) face has negative signed area and is dropped;
   the remaining CCW faces are rooms.

3. **Room adjacency** — graph of rooms connected by hosted doors.
   A door whose boundary touches two rooms is an edge between them.

All inputs are bare Python tuples / dicts. The orchestrator
translates ORM rows to these shapes before calling. This keeps the
geometry layer free of SQLAlchemy and trivially testable from
synthetic inputs.

Algorithmic notes:

- The wall-splitting preprocessor is O(n²). Floor plans typically
  have <200 walls per sheet so this is fine; if that ever becomes a
  hotspot, replace with a spatial index (Bentley-Ottmann sweep).
- The half-edge face walk uses the standard "next CCW around vertex
  from the reverse incoming half-edge, going one step CW" rule.
  Faces lie to the left of each half-edge they bound.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

Point = tuple[float, float]
Segment = tuple[Point, Point]


# ---------------------------------------------------------------------------
# Door-to-wall hosting
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HostingResult:
    """Outcome for one door.

    ``wall_index`` is None when no wall is within ``max_distance``;
    callers should treat the door as un-hosted (likely a free-floating
    annotation arc that only happened to land on A-DOOR).
    """

    door_index: int
    wall_index: int | None
    distance: float | None
    parametric_position: float | None  # 0..1 along the wall


def host_walls_for_doors(
    doors: list[Point],
    walls: list[Segment],
    *,
    max_distance: float = 0.5,
) -> list[HostingResult]:
    """Match each door to its nearest wall within ``max_distance``.

    Distance is point-to-segment (clamped at endpoints), so a door
    that lies on a wall's *extension* but past either endpoint won't
    be matched — that's intentional: the hinge has to actually sit
    on the wall, not near where the wall would be if it kept going.
    """
    results: list[HostingResult] = []
    for di, door in enumerate(doors):
        best_wi: int | None = None
        best_dist = float("inf")
        best_t: float | None = None
        for wi, wall in enumerate(walls):
            d, t = _point_to_segment_distance(door, wall)
            if d < best_dist:
                best_dist = d
                best_wi = wi
                best_t = t
        if best_wi is not None and best_dist <= max_distance:
            results.append(
                HostingResult(
                    door_index=di,
                    wall_index=best_wi,
                    distance=best_dist,
                    parametric_position=best_t,
                )
            )
        else:
            results.append(
                HostingResult(
                    door_index=di,
                    wall_index=None,
                    distance=best_dist if best_dist != float("inf") else None,
                    parametric_position=None,
                )
            )
    return results


# ---------------------------------------------------------------------------
# Wall splitting at intersections
# ---------------------------------------------------------------------------


def split_walls_at_intersections(
    walls: list[Segment],
    *,
    snap_tol: float = 1e-4,
) -> list[Segment]:
    """Split each wall at its intersections with other walls.

    Required preprocessing for the planar face walker — without it,
    a wall passing *through* a T-junction (like the y=5 line in the
    three-room fixture passing through (5, 5) where the vertical
    partition starts) won't have a vertex at the junction, and the
    face walk produces nonsense.
    """
    split_at: list[set[float]] = [set() for _ in walls]

    for i, w1 in enumerate(walls):
        for j in range(i + 1, len(walls)):
            w2 = walls[j]
            for t1, t2 in _segment_intersections(w1, w2):
                # Only split when the intersection is interior to the segment;
                # endpoint-to-endpoint connections are already vertices.
                if 0 < t1 < 1:
                    split_at[i].add(round(t1, 6))
                if 0 < t2 < 1:
                    split_at[j].add(round(t2, 6))

    out: list[Segment] = []
    for i, w in enumerate(walls):
        ts = sorted(split_at[i])
        ts = [0.0, *ts, 1.0]
        for k in range(len(ts) - 1):
            t_a, t_b = ts[k], ts[k + 1]
            if t_b - t_a < snap_tol:
                continue
            out.append((_along(w, t_a), _along(w, t_b)))
    return out


def _segment_intersections(s1: Segment, s2: Segment) -> list[tuple[float, float]]:
    """Compute parametric intersection of two segments.

    Returns ``(t1, t2)`` for each intersection inside both segments.
    Parallel / collinear segments return an empty list — collinear
    overlap doesn't need splitting (the duplicate edges collapse
    after snapping).
    """
    (x1, y1), (x2, y2) = s1
    (x3, y3), (x4, y4) = s2
    denom = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(denom) < 1e-12:
        return []
    t1 = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / denom
    t2 = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / denom
    eps = 1e-6
    if -eps <= t1 <= 1 + eps and -eps <= t2 <= 1 + eps:
        return [(max(0.0, min(1.0, t1)), max(0.0, min(1.0, t2)))]
    return []


def _along(seg: Segment, t: float) -> Point:
    (x0, y0), (x1, y1) = seg
    return (x0 + t * (x1 - x0), y0 + t * (y1 - y0))


# ---------------------------------------------------------------------------
# Planar face decomposition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DerivedRoom:
    """An interior face of the wall planar graph."""

    ring: list[Point]
    area: float
    bbox: tuple[float, float, float, float]  # minx, miny, maxx, maxy


def derive_rooms_from_walls(
    walls: list[Segment],
    *,
    snap_tol: float = 0.01,
) -> list[DerivedRoom]:
    """Find interior rooms from the wall graph.

    Returns each interior face as a CCW-ordered ring with cached
    area + bbox. The outer (boundary) face is filtered out by sign:
    walking with the "next-CW-around-vertex" rule traces interior
    faces with positive signed area; the outer face traces with
    negative signed area and gets dropped.
    """
    split = split_walls_at_intersections(walls)

    # Snap endpoints to canonical positions.
    snapped: dict[Point, Point] = {}
    edges: list[Segment] = []
    for a, b in split:
        sa = _snap(a, snapped, snap_tol)
        sb = _snap(b, snapped, snap_tol)
        if sa != sb:
            edges.append((sa, sb))

    # Build half-edges: each undirected edge becomes 2 directed half-edges.
    half_edges: list[tuple[Point, Point]] = []
    for u, v in edges:
        half_edges.append((u, v))
        half_edges.append((v, u))

    # For each vertex, sort outgoing half-edges by angle (CCW from +x).
    out_edges: dict[Point, list[tuple[Point, Point]]] = defaultdict(list)
    for he in half_edges:
        out_edges[he[0]].append(he)
    for u, outs in out_edges.items():
        outs.sort(key=lambda he: math.atan2(he[1][1] - u[1], he[1][0] - u[0]))

    # next-in-face[(u, v)]: at v, take the outgoing edge immediately CW
    # from rev = (v, u). That keeps the face on the LEFT of every half-edge.
    next_in_face: dict[tuple[Point, Point], tuple[Point, Point]] = {}
    for he in half_edges:
        u, v = he
        outs = out_edges[v]
        idx = outs.index((v, u))
        next_in_face[he] = outs[(idx - 1) % len(outs)]

    # Walk faces.
    visited: set[tuple[Point, Point]] = set()
    faces: list[list[Point]] = []
    for he in half_edges:
        if he in visited:
            continue
        face: list[Point] = []
        cur = he
        steps = 0
        while cur not in visited:
            visited.add(cur)
            face.append(cur[0])
            cur = next_in_face[cur]
            steps += 1
            if steps > 10_000:  # pathological-input safety
                break
        if len(face) >= 3:
            faces.append(face)

    # Interior faces have positive signed area; outer face is negative.
    rooms: list[DerivedRoom] = []
    for face in faces:
        a = _signed_area(face)
        if a > 0:
            xs = [p[0] for p in face]
            ys = [p[1] for p in face]
            rooms.append(
                DerivedRoom(
                    ring=face,
                    area=a,
                    bbox=(min(xs), min(ys), max(xs), max(ys)),
                )
            )
    # Stable-sort by area descending so the largest room is index 0 — handy
    # for tests + for picking a "primary" room when plans have one big space.
    rooms.sort(key=lambda r: -r.area)
    return rooms


# ---------------------------------------------------------------------------
# Room adjacency via doors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoomAdjacency:
    """One edge of the room-connectivity graph."""

    room_a_index: int
    room_b_index: int
    door_index: int


def room_adjacency_via_doors(
    rooms: list[DerivedRoom],
    doors: list[Point],
    *,
    max_distance: float = 0.5,
) -> list[RoomAdjacency]:
    """Find pairs of rooms connected by a door.

    A door whose hinge sits within ``max_distance`` of the boundary
    of exactly two rooms = an adjacency edge. Doors that touch one
    room (exterior doors) or zero rooms (annotation arcs) produce
    no edge.
    """
    edges: list[RoomAdjacency] = []
    for di, door in enumerate(doors):
        touched: list[int] = []
        for ri, room in enumerate(rooms):
            for k in range(len(room.ring)):
                seg = (room.ring[k], room.ring[(k + 1) % len(room.ring)])
                d, _ = _point_to_segment_distance(door, seg)
                if d <= max_distance:
                    touched.append(ri)
                    break
        if len(touched) == 2:
            a, b = sorted(touched)
            edges.append(
                RoomAdjacency(room_a_index=a, room_b_index=b, door_index=di)
            )
    return edges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _point_to_segment_distance(p: Point, seg: Segment) -> tuple[float, float]:
    """Distance from a point to a segment, clamped at the endpoints.

    Returns ``(distance, t)`` where ``t`` is the parametric position
    on the segment of the closest point.
    """
    (x0, y0), (x1, y1) = seg
    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(p[0] - x0, p[1] - y0), 0.0
    t = ((p[0] - x0) * dx + (p[1] - y0) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    closest = (x0 + t * dx, y0 + t * dy)
    return math.hypot(p[0] - closest[0], p[1] - closest[1]), t


def _snap(p: Point, snapped: dict[Point, Point], tol: float) -> Point:
    for q in snapped:
        if abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol:
            return q
    snapped[p] = p
    return p


def _signed_area(ring: list[Point]) -> float:
    s = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0
