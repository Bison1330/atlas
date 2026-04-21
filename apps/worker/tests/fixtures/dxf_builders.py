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
