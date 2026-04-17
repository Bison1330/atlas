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


def build_spline_wall_floor(path: Path) -> Path:
    """10×8 floor whose north wall is a SPLINE bowing upward.

    Three LINE walls (south, east, west) plus one SPLINE wall along
    the north, with endpoints at (10, 8) and (0, 8) and a control
    point bulging outward at (5, 9). Since ``_wall_segment`` in the
    orchestrator uses first/last point of the flattened polyline for
    face-finding, the derived room sees a straight-chord rectangle
    (area 80) — the spline's curvature is preserved in the element
    geometry for future use. Exercises G-R1.
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
