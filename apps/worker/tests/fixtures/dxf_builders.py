"""Reusable synthetic-DXF builders for worker tests.

Inline `ezdxf.new()` snippets had started duplicating across the
M2/M3 test suites; gathering them here so the geometric scenarios
each test exercises stay legible (one named call per scenario).

Conventions:

- All plans are drawn in the lower-left quadrant with positive
  coordinates so debug renders (and the future SVG preview) read
  the same way as the source.
- Walls live on ``A-WALL-EXTR`` (perimeter) or ``A-WALL-INTR``
  (interior partitions). Doors live on ``A-DOOR``.
- Each wall is one DXF ``LINE`` entity; doors are ``ARC`` entities
  with the arc center at the hinge point. This matches the entity
  shapes the M2 ``read_dxf`` reader expects.
- No explicit ``A-ROOM`` polygons — the M3 connectivity algorithms
  are responsible for *deriving* rooms from the wall planar graph.
  Helpers that want explicit rooms can layer them on top.
"""

from __future__ import annotations

from pathlib import Path

import ezdxf


def _new_doc():
    doc = ezdxf.new(dxfversion="R2018")
    for layer in (
        "A-WALL-EXTR",
        "A-WALL-INTR",
        "A-DOOR",
        "A-WIND",
        "A-COLS",
        "A-ROOM",
    ):
        doc.layers.add(layer)
    return doc


def _ensure_door_block(doc) -> str:
    """Define a minimal door-swing block once per doc.

    Mirrors the Revit / Archicad pattern where every door in the plan
    is an INSERT pointing at a named block definition (e.g.
    ``M_Door-Single``). The block contains the arc + hinge line; we
    only care that a block definition exists so INSERT references
    resolve cleanly.
    """
    name = "ATLAS_DOOR_SINGLE"
    if name not in doc.blocks:
        block = doc.blocks.new(name=name)
        block.add_arc(center=(0, 0), radius=1, start_angle=0, end_angle=90)
        block.add_line((0, 0), (1, 0))
    return name


def _ensure_window_block(doc) -> str:
    """Minimal window block: two parallel lines representing the glazing."""
    name = "ATLAS_WINDOW_DOUBLE"
    if name not in doc.blocks:
        block = doc.blocks.new(name=name)
        block.add_line((0, 0), (2, 0))
        block.add_line((0, 0.1), (2, 0.1))
    return name


def _ensure_column_block(doc) -> str:
    """Minimal column block: a unit circle at the origin."""
    name = "ATLAS_COLUMN_ROUND"
    if name not in doc.blocks:
        block = doc.blocks.new(name=name)
        block.add_circle(center=(0, 0), radius=0.25)
    return name


def build_one_room_floor(path: Path) -> Path:
    """Single 10×8 room — the minimal multi-element case.

    Useful as a "everything works on the easy case" baseline before
    multi-room logic is exercised.
    """
    doc = _new_doc()
    msp = doc.modelspace()
    for a, b in [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 8)),
        ((10, 8), (0, 8)),
        ((0, 8), (0, 0)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})
    msp.add_arc(
        center=(0, 0), radius=3, start_angle=0, end_angle=90,
        dxfattribs={"layer": "A-DOOR"},
    )
    doc.saveas(str(path))
    return path


def build_two_room_floor(path: Path) -> Path:
    """A 10×10 footprint split by an interior wall into 2 rooms.

    Layout (Y up)::

        +-------+-------+   y=10
        |       |       |
        |  R1   |  R2   |
        |       |       |
        +---D---+-------+   y=0
        x=0    x=5     x=10

    R1 occupies (0,0)-(5,10), R2 occupies (5,0)-(10,10). A door
    at (2.5, 0) sits on the south exterior wall of R1.

    Note no door connects R1 ↔ R2 — that's intentional, so a
    test can assert "two rooms, no internal connectivity" as a
    distinct case from the three-room scenario below.
    """
    doc = _new_doc()
    msp = doc.modelspace()
    # Exterior perimeter
    for a, b in [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 10)),
        ((10, 10), (0, 10)),
        ((0, 10), (0, 0)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})
    # Interior partition at x=5
    msp.add_line(
        (5, 0), (5, 10), dxfattribs={"layer": "A-WALL-INTR"}
    )
    # Door on the south wall of R1
    msp.add_arc(
        center=(2.5, 0), radius=1, start_angle=0, end_angle=90,
        dxfattribs={"layer": "A-DOOR"},
    )
    doc.saveas(str(path))
    return path


def build_three_room_floor(path: Path) -> Path:
    """A 10×10 footprint split into three rooms with two interior doors.

    Layout (Y up)::

        +-------+-------+   y=10
        |       |       |
        |  R1   |  R2   |
        |       |       |
        +--D1---+---D2--+   y=5
        |               |
        |      R3       |
        |               |
        +---------------+   y=0

    R1 = (0,5)-(5,10), R2 = (5,5)-(10,10), R3 = (0,0)-(10,5).
    D1 connects R1 ↔ R3, D2 connects R2 ↔ R3. R1 and R2 share an
    interior wall but no door (so they are NOT directly adjacent
    in the connectivity graph — only via R3).

    This is the canonical test plan for room connectivity: it has
    one internal junction (the T at x=5, y=5), two interior doors,
    and a known-correct adjacency graph (R1-R3, R2-R3, NOT R1-R2).
    """
    doc = _new_doc()
    msp = doc.modelspace()
    # Exterior perimeter
    for a, b in [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 10)),
        ((10, 10), (0, 10)),
        ((0, 10), (0, 0)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})
    # Horizontal partition at y=5 (between top rooms and R3)
    msp.add_line((0, 5), (10, 5), dxfattribs={"layer": "A-WALL-INTR"})
    # Vertical partition between R1 and R2 (no door here)
    msp.add_line((5, 5), (5, 10), dxfattribs={"layer": "A-WALL-INTR"})
    # Doors on the y=5 wall, hinged at the doorway centerlines
    msp.add_arc(
        center=(2.5, 5), radius=1, start_angle=0, end_angle=90,
        dxfattribs={"layer": "A-DOOR"},
    )
    msp.add_arc(
        center=(7.5, 5), radius=1, start_angle=0, end_angle=90,
        dxfattribs={"layer": "A-DOOR"},
    )
    doc.saveas(str(path))
    return path


def build_insert_elements_floor(path: Path) -> Path:
    """10×8 floor where the door, window, and column are all INSERTs.

    Matches the dominant Revit / Archicad export pattern: every
    "real" element is a block reference rather than raw geometry on
    the appropriate NCS layer. Exercises G-R3 (INSERT handling) for
    DOOR / WINDOW / COLUMN simultaneously, plus G-C1 for the INSERT
    window path.

    Layout::

        +---------------+   y=8
        |            []|<- window (INSERT on A-WIND)
        |              |
        |       [col]  |<- column (INSERT on A-COLS, mid-room)
        |              |
        +D=============+   y=0
        x=0    ^       x=10
               |
               hinged door (INSERT on A-DOOR, at (3,0))
    """
    doc = _new_doc()
    door_block = _ensure_door_block(doc)
    window_block = _ensure_window_block(doc)
    column_block = _ensure_column_block(doc)
    msp = doc.modelspace()

    for a, b in [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 8)),
        ((10, 8), (0, 8)),
        ((0, 8), (0, 0)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})

    msp.add_blockref(
        door_block, insert=(3, 0), dxfattribs={"layer": "A-DOOR"}
    )
    msp.add_blockref(
        window_block, insert=(7, 8), dxfattribs={"layer": "A-WIND"}
    )
    msp.add_blockref(
        column_block, insert=(5, 4), dxfattribs={"layer": "A-COLS"}
    )

    doc.saveas(str(path))
    return path


def build_polyline_window_floor(path: Path) -> Path:
    """10×8 floor with a window drawn as a raw LWPOLYLINE on A-WIND.

    Exercises the non-block window path (G-C1) — some CAD authors
    draw windows as sill+jamb polylines rather than block references.
    No door; no adjacencies to assert.
    """
    doc = _new_doc()
    msp = doc.modelspace()

    for a, b in [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 8)),
        ((10, 8), (0, 8)),
        ((0, 8), (0, 0)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})

    # Window on the north wall, drawn as an open polyline (sill line).
    msp.add_lwpolyline(
        [(6, 8), (9, 8)],
        close=False,
        dxfattribs={"layer": "A-WIND"},
    )

    doc.saveas(str(path))
    return path


def build_l_shaped_wall_floor(path: Path) -> Path:
    """L-shaped room where one wall is a multi-vertex LWPOLYLINE.

    Layout::

        (0,10)----(3,10)
          |          |
          |          |      <- single LWPOLYLINE wall from
          |          |         (10,3) → (3,3) → (3,10) → (0,10)
          |          (3,3)-----------(10,3)
          |                             |
          |                             |
        (0,0)-----------------------(10,0)

    Interior L-area = 10*10 - 7*7 = 51. Without G-R5, the polyline
    wall collapses to a straight (10,3)→(0,10) diagonal and the face
    walker derives a quadrilateral of area 65 — distinct from the
    correct 51, so the eval diagnoses the fix. A door sits on the
    south wall at (5, 0).
    """
    doc = _new_doc()
    msp = doc.modelspace()

    # Straight walls: south, east-lower, west
    for a, b in [
        ((0, 0), (10, 0)),   # south
        ((10, 0), (10, 3)),  # east lower
        ((0, 10), (0, 0)),   # west
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})

    # The L-bend as a single LWPOLYLINE — the exact shape that G-R5
    # exists to handle. 4 vertices → 3 segments post-expansion.
    msp.add_lwpolyline(
        [(10, 3), (3, 3), (3, 10), (0, 10)],
        close=False,
        dxfattribs={"layer": "A-WALL-EXTR"},
    )

    # Door on south wall
    msp.add_arc(
        center=(5, 0), radius=1, start_angle=0, end_angle=90,
        dxfattribs={"layer": "A-DOOR"},
    )

    doc.saveas(str(path))
    return path


def build_explicit_and_derived_room_floor(path: Path) -> Path:
    """10×8 floor with BOTH wall loop AND an explicit A-ROOM polygon.

    Production CAD often ships both: the walls define the boundary
    and an A-ROOM polygon carries the author's room name / number.
    Before G-O1, the orchestrator would persist *two* room elements
    for the same footprint — the explicit polygon and a derived
    wall-loop room — and the takeoffs endpoint would double-count.

    After G-O1, the explicit element is annotated with
    ``attrs.derivation_confirmed = True`` and no duplicate derived
    room is inserted.
    """
    doc = _new_doc()
    msp = doc.modelspace()

    for a, b in [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 8)),
        ((10, 8), (0, 8)),
        ((0, 8), (0, 0)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})

    # Explicit room polygon covering the same footprint as the wall loop
    msp.add_lwpolyline(
        [(0, 0), (10, 0), (10, 8), (0, 8)],
        close=True,
        dxfattribs={"layer": "A-ROOM"},
    )

    doc.saveas(str(path))
    return path


def build_apartment_grid_floor(path: Path) -> Path:
    """Rich 2×3 apartment grid: 13 walls, 3 doors, 2 windows, 6 derivable rooms.

    The smallest plan this repo has that clears the ≥10-wall threshold
    some downstream consumers (notably 3D reconstruction acceptance
    tests) need in order to exercise multi-wall / multi-room code
    paths end-to-end.

    Layout (Y up, 18×12 footprint)::

        +---+----+--------+-------+   y=12
        | R1|    |   R2   |  R3   |
        |   | wn |        | wn    |
        +-D-+----+---D----+---D---+   y=6  (doors open to lower strip)
        |                          |
        | R4     |   R5    |  R6   |
        |        |         |       |
        +---+----+---------+-------+   y=0
           x=6         x=12        x=18

    Wall entity count (stored as individual LINEs so the connectivity
    splitter has real vertices at every junction):

    - South perimeter: 2 (split at x=9)
    - North perimeter: 2 (split at x=9)
    - East / West: 1 each
    - Horizontal partition y=6: 3 (split at x=6 and x=12)
    - Vertical partitions (top row): 2 (x=6, x=12, from y=6 to y=12)
    - Vertical partitions (bottom row): 2 (x=6, x=12, from y=0 to y=6)

    → 13 wall entities total.

    Doors (3): centered on the y=6 partition, one per upper-room /
    lower-room pair. Two are ARCs on ``A-DOOR`` (the classic CAD
    hinged-door representation); the third is an INSERT of the
    standard door block, so both extraction paths (G-R3 and the
    raw-arc path) are exercised by a single fixture.

    Windows (2): INSERTs of the window block on ``A-WIND``, sitting
    on the north exterior between the top rooms.
    """
    doc = _new_doc()
    door_block = _ensure_door_block(doc)
    window_block = _ensure_window_block(doc)
    msp = doc.modelspace()

    # --- Exterior perimeter (split at midpoints so junctions are real) ---
    for a, b in [
        # South
        ((0, 0), (9, 0)),
        ((9, 0), (18, 0)),
        # East
        ((18, 0), (18, 12)),
        # North
        ((18, 12), (9, 12)),
        ((9, 12), (0, 12)),
        # West
        ((0, 12), (0, 0)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})

    # --- Horizontal partition at y=6, split at x=6 and x=12 ---
    for a, b in [
        ((0, 6), (6, 6)),
        ((6, 6), (12, 6)),
        ((12, 6), (18, 6)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-INTR"})

    # --- Vertical partitions (top row between R1/R2/R3) ---
    for a, b in [
        ((6, 6), (6, 12)),
        ((12, 6), (12, 12)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-INTR"})

    # --- Vertical partitions (bottom row between R4/R5/R6) ---
    for a, b in [
        ((6, 0), (6, 6)),
        ((12, 0), (12, 6)),
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-INTR"})

    # --- Doors on the y=6 partition ---
    # R1 ↔ R4 (ARC-style door).
    msp.add_arc(
        center=(3, 6), radius=1, start_angle=0, end_angle=90,
        dxfattribs={"layer": "A-DOOR"},
    )
    # R2 ↔ R5 (ARC-style door).
    msp.add_arc(
        center=(9, 6), radius=1, start_angle=0, end_angle=90,
        dxfattribs={"layer": "A-DOOR"},
    )
    # R3 ↔ R6 (INSERT-style door, exercises the block-ref path).
    msp.add_blockref(
        door_block, insert=(15, 6), dxfattribs={"layer": "A-DOOR"}
    )

    # --- Windows on the north exterior wall ---
    msp.add_blockref(
        window_block, insert=(3, 12), dxfattribs={"layer": "A-WIND"}
    )
    msp.add_blockref(
        window_block, insert=(15, 12), dxfattribs={"layer": "A-WIND"}
    )

    doc.saveas(str(path))
    return path


def build_spline_wall_floor(path: Path) -> Path:
    """10×8 floor whose north wall is a SPLINE bowing upward.

    Three LINE walls (south, east, west) plus one SPLINE wall along
    the north, with endpoints at (10, 8) and (0, 8) and a control
    point bulging outward at (5, 9). Exercises G-R1; combined with
    G-R5 (Phase 2), the flattened polyline's sub-segments now feed
    the face walker so the derived room traces the bulge and
    reports the correct ~86.22-unit bowed area rather than the
    straight-chord 80.
    """
    doc = _new_doc()
    msp = doc.modelspace()

    # Straight walls
    for a, b in [
        ((0, 0), (10, 0)),   # south
        ((10, 0), (10, 8)),  # east
        ((0, 8), (0, 0)),    # west
    ]:
        msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})

    # Curved north wall as a SPLINE
    msp.add_spline(
        fit_points=[(10, 8), (5, 9), (0, 8)],
        dxfattribs={"layer": "A-WALL-EXTR"},
    )

    doc.saveas(str(path))
    return path


# ---------------------------------------------------------------------------
# Demo presets — realistic floor plans for the shared demo account.
#
# Four typologies: 2BR/1BA bungalow, 2BR apartment, small office fit-out,
# retail showroom. Each builder emits a DXF with varied room sizes and
# realistic door/window placement — the earlier uniform-grid fixtures
# read as synthetic to an architect's eye. See the external-review notes
# in the session-3 retrospective.
#
# **Units convention.** We author these plans in metres (what an
# architect thinks in), but the downstream 3D reconstructor defaults
# to ``Units.FEET`` when ``StructuredSheet`` doesn't explicitly say
# otherwise. Since the demo drawings never set ``$INSUNITS``, every
# coordinate written to the DXF is multiplied by ``_M_TO_FT`` so that
# the final 3D-scene output (which divides by ``_M_TO_FT`` internally
# via ``_UNIT_TO_METERS[Units.FEET] = 0.3048``) lands on the intended
# metre dimensions. The ``*_ROOM_LABELS`` centroids are stored in the
# same scaled (feet) space so ``scripts/seed_demo_account.py`` can
# match them directly against the derived-room bboxes in the DB —
# those bboxes are in DXF units, not metres.
#
# Per-preset ``*_ROOM_LABELS`` tuples carry ``(name, centroid_x, centroid_y)``
# (in DXF feet) for each room the plan contains. The seed script reads
# these and assigns ``Element.name`` on the derived-room rows after
# extraction, so the 3D viewer renders "LIVING ROOM 24.0 m²" instead of
# a placeholder.
# ---------------------------------------------------------------------------

# International foot. Chosen over the US survey foot since the 3D
# pipeline uses the same ratio (atlas_core.reconstruct3d uses 0.3048
# for FEET → METERS).
_M_TO_FT: float = 1.0 / 0.3048


def _edges_from_rectangles(
    rects: list[tuple[float, float, float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float], bool]]:
    """Generate wall line segments from a set of rectangular rooms.

    Every edge of every room is a wall. Shared edges between adjacent
    rooms collapse to a single wall. Each edge is split at every
    vertex that lies on it, so the planar graph has a real vertex at
    every junction — matches how ``apartment_grid`` was hand-tuned.

    Returns a list of ``(start, end, is_exterior)`` tuples so the
    caller can route exterior walls to ``A-WALL-EXTR`` and interior
    partitions to ``A-WALL-INTR``.
    """
    # Canonicalise endpoints before deduping so shared edges collapse.
    raw: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    verts: set[tuple[float, float]] = set()
    for x0, y0, x1, y1 in rects:
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        verts.update(corners)
        for a, b in [
            (corners[0], corners[1]),
            (corners[1], corners[2]),
            (corners[2], corners[3]),
            (corners[3], corners[0]),
        ]:
            key = tuple(sorted([a, b]))
            raw.add(key)  # type: ignore[arg-type]

    # Outer bounding box → exterior-wall classifier.
    xmin = min(r[0] for r in rects)
    ymin = min(r[1] for r in rects)
    xmax = max(r[2] for r in rects)
    ymax = max(r[3] for r in rects)

    tol = 1e-6

    def _on_segment(p, a, b):
        ax, ay = a
        bx, by = b
        px, py = p
        if abs(ax - bx) < tol:  # vertical
            return (
                abs(px - ax) < tol
                and min(ay, by) - tol <= py <= max(ay, by) + tol
            )
        if abs(ay - by) < tol:  # horizontal
            return (
                abs(py - ay) < tol
                and min(ax, bx) - tol <= px <= max(ax, bx) + tol
            )
        return False

    def _is_exterior(a, b):
        ax, ay = a
        bx, by = b
        if abs(ax - bx) < tol:  # vertical
            return abs(ax - xmin) < tol or abs(ax - xmax) < tol
        if abs(ay - by) < tol:  # horizontal
            return abs(ay - ymin) < tol or abs(ay - ymax) < tol
        return False

    out: list[tuple[tuple[float, float], tuple[float, float], bool]] = []
    for a, b in raw:
        on_seg = [a, b]
        for v in verts:
            if v in (a, b):
                continue
            if _on_segment(v, a, b):
                on_seg.append(v)
        on_seg.sort()
        for i in range(len(on_seg) - 1):
            out.append((on_seg[i], on_seg[i + 1], _is_exterior(a, b)))
    return out


def _floor_plan_from_spec(
    path: Path,
    *,
    rooms_rects_m: list[tuple[float, float, float, float]],
    doors_m: list[tuple[float, float]],
    door_blocks_m: list[tuple[float, float]] = [],
    windows_m: list[tuple[float, float]] = [],
) -> Path:
    """Serialize a rectangular floor-plan spec into a DXF.

    Inputs are in metres (human-legible). We scale by ``_M_TO_FT``
    before writing to the DXF so the reconstructor's default
    ``Units.FEET`` interpretation lands on the intended metre
    dimensions downstream. Walls are generated via
    :func:`_edges_from_rectangles`; doors are ARCs (plus optional
    INSERT door blocks to exercise that code path); windows are
    block INSERTs on ``A-WIND``.
    """
    s = _M_TO_FT

    def _scale_pt(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0] * s, p[1] * s)

    rects_ft = [
        (x0 * s, y0 * s, x1 * s, y1 * s) for x0, y0, x1, y1 in rooms_rects_m
    ]

    doc = _new_doc()
    door_block = _ensure_door_block(doc)
    window_block = _ensure_window_block(doc)
    msp = doc.modelspace()

    for a, b, is_ext in _edges_from_rectangles(rects_ft):
        msp.add_line(
            a, b,
            dxfattribs={"layer": "A-WALL-EXTR" if is_ext else "A-WALL-INTR"},
        )
    # Door-arc radius scales with the plan — 0.9m is a plausible swing.
    for cx, cy in doors_m:
        msp.add_arc(
            center=_scale_pt((cx, cy)),
            radius=0.9 * s,
            start_angle=0, end_angle=90,
            dxfattribs={"layer": "A-DOOR"},
        )
    for cx, cy in door_blocks_m:
        msp.add_blockref(
            door_block, insert=_scale_pt((cx, cy)),
            dxfattribs={"layer": "A-DOOR"},
        )
    for cx, cy in windows_m:
        msp.add_blockref(
            window_block, insert=_scale_pt((cx, cy)),
            dxfattribs={"layer": "A-WIND"},
        )

    doc.saveas(str(path))
    return path


def _scaled_labels(
    rooms: tuple[tuple[str, tuple[float, float, float, float]], ...],
) -> tuple[tuple[str, float, float], ...]:
    """Compute ``(name, cx, cy)`` label tuples in DXF-feet space.

    Centroids must match what the extractor sees in the DB (DXF
    units), not the metre values the builders think in. This
    multiplies each rectangle's centre by ``_M_TO_FT``.
    """
    s = _M_TO_FT
    return tuple(
        (name, (r[0] + r[2]) / 2 * s, (r[1] + r[3]) / 2 * s)
        for name, r in rooms
    )


# ---------- Bungalow: 2BR/1BA, ~80 m² footprint ----------------------------

_BUNGALOW_ROOMS: tuple[tuple[str, tuple[float, float, float, float]], ...] = (
    # (name, (x0, y0, x1, y1)) — areas in the comment for sanity.
    ("kitchen",          (0.0, 0.0,  3.5, 4.5)),  # 15.75 m²
    ("living_room",      (3.5, 0.0, 10.0, 4.5)),  # 29.25 m²
    ("bedroom_primary",  (0.0, 4.5,  4.0, 8.0)),  # 14.00 m²
    ("bedroom_2",        (4.0, 4.5,  7.0, 8.0)),  # 10.50 m²
    ("bathroom",         (7.0, 4.5,  9.0, 8.0)),  # 7.00 m²
    ("utility",          (9.0, 4.5, 10.0, 8.0)),  # 3.50 m²
)

BUNGALOW_ROOM_LABELS: tuple[tuple[str, float, float], ...] = _scaled_labels(
    _BUNGALOW_ROOMS,
)


def build_bungalow_floor(path: Path) -> Path:
    """Single-family bungalow, ~900 sqft / 80 m² footprint.

    Six rooms — kitchen, living, two bedrooms, bath, utility closet —
    laid out sleeping-rooms-north / living-rooms-south. Doors open
    off the living room into each of the north-side rooms, plus a
    kitchen ↔ living pass-through and a street entry on the south
    exterior. Windows on west (kitchen), south (living), east (bath),
    and two on the north exterior (bedrooms).

    Coordinates below are in metres; see the ``_M_TO_FT`` note in the
    module docstring for why the on-disk DXF is in feet.
    """
    return _floor_plan_from_spec(
        path,
        rooms_rects_m=[r[1] for r in _BUNGALOW_ROOMS],
        doors_m=[
            (3.5, 2.5),   # kitchen ↔ living
            (3.8, 4.5),   # bed1 ↔ living
            (5.5, 4.5),   # bed2 ↔ living
            (8.0, 4.5),   # bath ↔ living
            (9.5, 4.5),   # utility ↔ living
        ],
        door_blocks_m=[
            (7.0, 0.0),   # street entry on south into living (INSERT)
        ],
        windows_m=[
            (0.0, 2.0),   # kitchen west
            (5.0, 0.0),   # living south
            (2.0, 8.0),   # bed1 north
            (5.5, 8.0),   # bed2 north
            (10.0, 6.5),  # bath east
        ],
    )


# ---------- Apartment: 2BR, ~80 m² footprint -------------------------------

_APARTMENT_ROOMS: tuple[tuple[str, tuple[float, float, float, float]], ...] = (
    ("living_dining",   (0.0, 0.0, 5.0, 4.0)),  # 20.00 m²
    ("kitchen",         (5.0, 0.0, 8.0, 4.0)),  # 12.00 m²
    ("hall_entry",      (0.0, 4.0, 2.5, 6.0)),  #  5.00 m²
    ("bathroom",        (2.5, 4.0, 5.0, 6.0)),  #  5.00 m²
    ("storage",         (5.0, 4.0, 8.0, 6.0)),  #  6.00 m²
    ("bedroom_primary", (0.0, 6.0, 5.0, 10.0)), # 20.00 m²
    ("bedroom_2",       (5.0, 6.0, 8.0, 10.0)), # 12.00 m²
)

APARTMENT_ROOM_LABELS: tuple[tuple[str, float, float], ...] = _scaled_labels(
    _APARTMENT_ROOMS,
)


def build_apartment_floor(path: Path) -> Path:
    """Two-bedroom urban apartment, ~80 m² footprint.

    South half is living/dining + kitchen with a pass-through; middle
    strip is entry/hall + bath + small storage; north half is two
    bedrooms. Doors open off the hall into each bedroom and the bath;
    the kitchen connects to the living room; front door opens into
    the hall from the exterior.
    """
    return _floor_plan_from_spec(
        path,
        rooms_rects_m=[r[1] for r in _APARTMENT_ROOMS],
        doors_m=[
            (5.0, 2.0),   # living ↔ kitchen
            (1.25, 4.0),  # living ↔ hall
            (3.75, 4.0),  # living ↔ bath  (via shared wall)
            (6.5, 4.0),   # kitchen ↔ storage
            (1.25, 6.0),  # hall ↔ bed1 (primary)
            (6.5, 6.0),   # storage ↔ bed2
        ],
        door_blocks_m=[
            (0.0, 5.0),   # entry on west exterior into hall (INSERT)
        ],
        windows_m=[
            (2.5, 0.0),   # living south
            (6.5, 0.0),   # kitchen south
            (2.5, 10.0),  # bed1 north
            (6.5, 10.0),  # bed2 north
            (8.0, 7.0),   # bed2 east
        ],
    )


# ---------- Small office: ~150 m² tenant fit-out ---------------------------

_OFFICE_ROOMS: tuple[tuple[str, tuple[float, float, float, float]], ...] = (
    ("open_workspace",   (0.0, 0.0,  8.0, 7.0)),   # 56 m²
    ("private_office_1", (8.0, 0.0, 12.0, 4.0)),   # 16 m²
    ("private_office_2", (12.0, 0.0, 15.0, 4.0)),  #  9 m²
    ("conference_room",  (8.0, 4.0, 13.0, 7.0)),   # 15 m²
    ("kitchenette",      (13.0, 4.0, 15.0, 7.0)),  #  6 m²
    ("restroom_1",       (0.0, 7.0,  2.0, 10.0)),  #  6 m²
    ("restroom_2",       (2.0, 7.0,  4.0, 10.0)),  #  6 m²
    ("reception",        (4.0, 7.0,  8.0, 10.0)),  # 12 m²
    ("corridor",         (8.0, 7.0, 15.0, 10.0)),  # 21 m²
)

OFFICE_ROOM_LABELS: tuple[tuple[str, float, float], ...] = _scaled_labels(
    _OFFICE_ROOMS,
)


def build_office_floor(path: Path) -> Path:
    """Small office tenant fit-out, ~150 m² footprint.

    Main floor = open workspace with two private offices + conference
    room + kitchenette along the east. North strip = two restrooms +
    reception at the front + a small east-side corridor. Reception
    entry door sits on the north exterior; each private office and
    the conference room open onto the corridor / open workspace.
    """
    return _floor_plan_from_spec(
        path,
        rooms_rects_m=[r[1] for r in _OFFICE_ROOMS],
        doors_m=[
            (5.0, 7.0),    # reception ↔ open workspace
            (8.0, 2.0),    # open ↔ private office 1
            (12.0, 2.0),   # private office 1 ↔ private office 2
            (8.0, 5.5),    # open ↔ conference room
            (13.0, 5.5),   # conference ↔ kitchenette
            (1.0, 7.0),    # reception hall ↔ restroom 1
            (3.0, 7.0),    # reception hall ↔ restroom 2
            (8.0, 8.5),    # reception ↔ corridor
        ],
        door_blocks_m=[
            (6.0, 10.0),   # exterior entry on north into reception (INSERT)
        ],
        windows_m=[
            (2.0, 0.0),    # open workspace south
            (6.0, 0.0),    # open workspace south
            (10.0, 0.0),   # private office 1 south
            (13.5, 0.0),   # private office 2 south
            (15.0, 2.0),   # private office 2 east
            (15.0, 5.5),   # kitchenette east
        ],
    )


# ---------- Retail: ~150 m² showroom + back of house -----------------------

_RETAIL_ROOMS: tuple[tuple[str, tuple[float, float, float, float]], ...] = (
    ("main_floor",         (0.0, 0.0, 15.0, 7.0)),   # 105 m²
    ("storage",            (0.0, 7.0,  7.0, 10.0)),  #  21 m²
    ("employee_restroom",  (7.0, 7.0,  9.0, 10.0)),  #   6 m²
    ("break_room",         (9.0, 7.0, 13.0, 10.0)),  #  12 m²
    ("back_office",        (13.0, 7.0, 15.0, 10.0)), #   6 m²
)

RETAIL_ROOM_LABELS: tuple[tuple[str, float, float], ...] = _scaled_labels(
    _RETAIL_ROOMS,
)


def build_retail_floor(path: Path) -> Path:
    """Retail showroom with back-of-house strip, ~150 m² footprint.

    One large showroom takes up two-thirds of the depth; the remaining
    north strip holds storage, an employee restroom, a break room, and
    a small back office. Street entry on the south exterior; each
    back-of-house room opens off the main floor via an interior door.
    Two large storefront windows flank the entry.
    """
    return _floor_plan_from_spec(
        path,
        rooms_rects_m=[r[1] for r in _RETAIL_ROOMS],
        doors_m=[
            (3.0, 7.0),    # showroom ↔ storage
            (8.0, 7.0),    # showroom ↔ employee restroom
            (11.0, 7.0),   # showroom ↔ break room
            (14.0, 7.0),   # showroom ↔ back office
        ],
        door_blocks_m=[
            (7.5, 0.0),    # storefront entry on south (INSERT)
        ],
        windows_m=[
            (3.0, 0.0),    # storefront window left of entry
            (12.0, 0.0),   # storefront window right of entry
            (0.0, 3.5),    # side street window (west)
            (15.0, 3.5),   # side street window (east)
        ],
    )
