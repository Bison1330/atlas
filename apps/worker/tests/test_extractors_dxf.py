"""Tests for the DXF reader.

Uses ezdxf to generate synthetic DXF files in tmp_path so each test
controls exactly which entities and layers are present. No real-
world CAD fixtures yet — those land in Phase 4 once the upload flow
accepts non-PDF formats.
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from atlas_core import ElementKind

from worker.extractors import dxf

# -------- synthetic DXF builders --------


def _new_doc():
    doc = ezdxf.new(dxfversion="R2018")
    return doc


def _ensure_layer(doc, name: str) -> None:
    if name not in doc.layers:
        doc.layers.add(name)


def _write(doc, path: Path) -> Path:
    doc.saveas(str(path))
    return path


def _dxf_with_one_wall(path: Path) -> Path:
    doc = _new_doc()
    _ensure_layer(doc, "A-WALL-EXTR")
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A-WALL-EXTR"})
    return _write(doc, path)


def _dxf_with_a_room(path: Path) -> Path:
    doc = _new_doc()
    _ensure_layer(doc, "A-ROOM")
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (10, 0), (10, 8), (0, 8)],
        close=True,
        dxfattribs={"layer": "A-ROOM"},
    )
    return _write(doc, path)


def _dxf_with_a_door(path: Path) -> Path:
    doc = _new_doc()
    _ensure_layer(doc, "A-DOOR")
    msp = doc.modelspace()
    # 90-degree door swing, 3 ft wide, hinged at origin.
    msp.add_arc(
        center=(0, 0),
        radius=3,
        start_angle=0,
        end_angle=90,
        dxfattribs={"layer": "A-DOOR"},
    )
    return _write(doc, path)


# -------- tests --------


class TestSingleEntityClassification:
    def test_line_on_wall_layer_becomes_wall_candidate(self, tmp_path):
        path = _dxf_with_one_wall(tmp_path / "wall.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        c = summary.candidates[0]
        assert c.kind == ElementKind.WALL
        assert c.geometry["kind"] == "polyline"
        assert c.geometry["points"] == [
            {"x": 0.0, "y": 0.0},
            {"x": 10.0, "y": 0.0},
        ]
        assert c.ncs_layer == "A-WALL-EXTR"
        assert c.ncs_major_group == "WALL"
        assert c.ncs_minor_group == "EXTR"
        assert c.ifc_type == "IfcWallStandardCase"
        assert c.attrs["source_entity"] == "LINE"
        # NCS exact match × geometric pass with slack=0 → 1.0
        assert c.confidence == pytest.approx(1.0)
        assert c.bbox == {"minx": 0.0, "miny": 0.0, "maxx": 10.0, "maxy": 0.0}

    def test_closed_polyline_on_room_layer_becomes_room_candidate(self, tmp_path):
        path = _dxf_with_a_room(tmp_path / "room.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        c = summary.candidates[0]
        assert c.kind == ElementKind.ROOM
        assert c.geometry["kind"] == "polygon"
        assert len(c.geometry["ring"]) == 4
        assert c.ifc_type == "IfcSpace"
        assert c.bbox == {"minx": 0.0, "miny": 0.0, "maxx": 10.0, "maxy": 8.0}

    def test_arc_on_door_layer_becomes_door_candidate(self, tmp_path):
        path = _dxf_with_a_door(tmp_path / "door.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        c = summary.candidates[0]
        assert c.kind == ElementKind.DOOR
        assert c.geometry["kind"] == "arc"
        assert c.geometry["radius"] == 3.0
        assert c.attrs["swing_angle_deg"] == pytest.approx(90.0)
        assert c.ifc_type == "IfcDoor"


class TestLayerHandling:
    def test_open_polyline_on_wall_layer_still_a_wall(self, tmp_path):
        doc = _new_doc()
        _ensure_layer(doc, "A-WALL")
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (10, 0), (10, 5)],
            close=False,
            dxfattribs={"layer": "A-WALL"},
        )
        path = _write(doc, tmp_path / "open.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        c = summary.candidates[0]
        assert c.kind == ElementKind.WALL
        assert c.attrs["closed"] is False

    def test_unknown_layer_produces_nothing(self, tmp_path):
        doc = _new_doc()
        _ensure_layer(doc, "RANDOMSTUFF")
        msp = doc.modelspace()
        msp.add_line((0, 0), (1, 1), dxfattribs={"layer": "RANDOMSTUFF"})
        path = _write(doc, tmp_path / "unknown.dxf")
        summary = dxf.read_dxf(path)

        assert summary.candidates == []
        assert summary.skipped_unknown_layers >= 1

    def test_well_formed_but_unmapped_layer_emits_other_candidate(self, tmp_path):
        # A-XYZ parses cleanly under NCS; the XYZ Major group falls
        # through to ElementKind.OTHER. The reader captures it so
        # nothing on a real layer goes silently missing.
        doc = _new_doc()
        _ensure_layer(doc, "A-XYZ")
        msp = doc.modelspace()
        msp.add_line((0, 0), (1, 1), dxfattribs={"layer": "A-XYZ"})
        path = _write(doc, tmp_path / "other.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        assert summary.candidates[0].kind == ElementKind.OTHER

    def test_wrong_geometry_for_kind_skipped(self, tmp_path):
        # Open LWPOLYLINE on A-ROOM is not a closed loop → not a room.
        doc = _new_doc()
        _ensure_layer(doc, "A-ROOM")
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (5, 0), (5, 5)],
            close=False,
            dxfattribs={"layer": "A-ROOM"},
        )
        path = _write(doc, tmp_path / "open-room.dxf")
        summary = dxf.read_dxf(path)

        assert summary.candidates == []
        # And the entity type was tracked as skipped.
        assert "LWPOLYLINE" in summary.skipped_entity_types


class TestMixedDocument:
    def test_full_floor_with_walls_room_door(self, tmp_path):
        doc = _new_doc()
        for name in ("A-WALL-EXTR", "A-ROOM", "A-DOOR"):
            _ensure_layer(doc, name)
        msp = doc.modelspace()
        # 4 walls forming a 10x8 box
        for a, b in [
            ((0, 0), (10, 0)),
            ((10, 0), (10, 8)),
            ((10, 8), (0, 8)),
            ((0, 8), (0, 0)),
        ]:
            msp.add_line(a, b, dxfattribs={"layer": "A-WALL-EXTR"})
        # A room polygon overlapping the box
        msp.add_lwpolyline(
            [(0, 0), (10, 0), (10, 8), (0, 8)],
            close=True,
            dxfattribs={"layer": "A-ROOM"},
        )
        # A door swing in one corner
        msp.add_arc(
            center=(0, 0),
            radius=3,
            start_angle=0,
            end_angle=90,
            dxfattribs={"layer": "A-DOOR"},
        )
        path = _write(doc, tmp_path / "floor.dxf")
        summary = dxf.read_dxf(path)

        kinds = [c.kind for c in summary.candidates]
        assert kinds.count(ElementKind.WALL) == 4
        assert kinds.count(ElementKind.ROOM) == 1
        assert kinds.count(ElementKind.DOOR) == 1

    def test_summary_layer_counts_match_input(self, tmp_path):
        doc = _new_doc()
        _ensure_layer(doc, "A-WALL")
        _ensure_layer(doc, "A-DOOR")
        msp = doc.modelspace()
        for _ in range(3):
            msp.add_line((0, 0), (1, 0), dxfattribs={"layer": "A-WALL"})
        msp.add_arc(
            center=(0, 0),
            radius=1,
            start_angle=0,
            end_angle=90,
            dxfattribs={"layer": "A-DOOR"},
        )
        path = _write(doc, tmp_path / "counts.dxf")
        summary = dxf.read_dxf(path)
        assert summary.layer_counts == {"A-WALL": 3, "A-DOOR": 1}


class TestEmptyAndEdgeCases:
    def test_empty_modelspace(self, tmp_path):
        doc = _new_doc()
        path = _write(doc, tmp_path / "empty.dxf")
        summary = dxf.read_dxf(path)
        assert summary.candidates == []

    def test_unsupported_entity_on_real_layer_tracked_as_skipped(self, tmp_path):
        doc = _new_doc()
        _ensure_layer(doc, "A-WALL")
        msp = doc.modelspace()
        # CIRCLE on A-WALL — wall layer but not the geometry shape we treat
        # as a wall (we want LINE / LWPOLYLINE / SPLINE there).
        msp.add_circle(center=(0, 0), radius=1, dxfattribs={"layer": "A-WALL"})
        path = _write(doc, tmp_path / "circle-on-wall.dxf")
        summary = dxf.read_dxf(path)
        assert summary.candidates == []
        assert summary.skipped_entity_types.get("CIRCLE") == 1


class TestBlockReferences:
    """INSERT-entity handling (G-R3).

    Real Revit / Archicad exports deliver doors, windows, and columns
    as block references rather than raw geometry. Option (b) of G-R3:
    treat the INSERT itself as the element using its insertion point
    + scale as the implied geometry.
    """

    def _define_block(self, doc, name: str):
        if name not in doc.blocks:
            block = doc.blocks.new(name=name)
            block.add_line((0, 0), (1, 0))
        return name

    def test_insert_on_door_layer_becomes_door_candidate(self, tmp_path):
        doc = _new_doc()
        _ensure_layer(doc, "A-DOOR")
        name = self._define_block(doc, "M_Door-Single")
        msp = doc.modelspace()
        msp.add_blockref(
            name,
            insert=(3, 0),
            dxfattribs={"layer": "A-DOOR", "rotation": 90},
        )
        path = _write(doc, tmp_path / "insert-door.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        c = summary.candidates[0]
        assert c.kind == ElementKind.DOOR
        assert c.geometry["kind"] == "insert"
        assert c.geometry["center"] == {"x": 3.0, "y": 0.0}
        assert c.geometry["rotation_deg"] == pytest.approx(90.0)
        assert c.attrs["source_entity"] == "INSERT"
        assert c.attrs["block_name"] == "M_Door-Single"
        assert c.ifc_type == "IfcDoor"

    def test_insert_on_window_layer_becomes_window_candidate(self, tmp_path):
        doc = _new_doc()
        _ensure_layer(doc, "A-WIND")
        name = self._define_block(doc, "M_Window")
        msp = doc.modelspace()
        msp.add_blockref(name, insert=(7, 8), dxfattribs={"layer": "A-WIND"})
        path = _write(doc, tmp_path / "insert-window.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        c = summary.candidates[0]
        assert c.kind == ElementKind.WINDOW
        assert c.geometry["kind"] == "insert"
        assert c.geometry["center"] == {"x": 7.0, "y": 8.0}
        assert c.ifc_type == "IfcWindow"

    def test_insert_on_column_layer_becomes_column_candidate(self, tmp_path):
        doc = _new_doc()
        _ensure_layer(doc, "A-COLS")
        name = self._define_block(doc, "W10x49")
        msp = doc.modelspace()
        msp.add_blockref(name, insert=(5, 4), dxfattribs={"layer": "A-COLS"})
        path = _write(doc, tmp_path / "insert-column.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        c = summary.candidates[0]
        assert c.kind == ElementKind.COLUMN
        assert c.geometry["kind"] == "insert"
        assert c.ifc_type == "IfcColumn"

    def test_insert_on_wall_layer_is_skipped(self, tmp_path):
        # Walls are lines, not blocks — an INSERT on a wall layer is
        # non-typical and we don't guess at its geometry. Skip it
        # rather than produce a misleading point-element.
        doc = _new_doc()
        _ensure_layer(doc, "A-WALL")
        name = self._define_block(doc, "RANDOM_BLOCK")
        msp = doc.modelspace()
        msp.add_blockref(name, insert=(0, 0), dxfattribs={"layer": "A-WALL"})
        path = _write(doc, tmp_path / "insert-on-wall.dxf")
        summary = dxf.read_dxf(path)

        assert summary.candidates == []
        assert summary.skipped_entity_types.get("INSERT") == 1


class TestWindowClassification:
    """Window detection (G-C1): LWPOLYLINE path.

    The INSERT path is covered by :class:`TestBlockReferences`.
    """

    def test_open_polyline_on_window_layer_becomes_window(self, tmp_path):
        doc = _new_doc()
        _ensure_layer(doc, "A-WIND")
        msp = doc.modelspace()
        # Sill line — open polyline along a wall.
        msp.add_lwpolyline(
            [(6, 8), (9, 8)],
            close=False,
            dxfattribs={"layer": "A-WIND"},
        )
        path = _write(doc, tmp_path / "polyline-window.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        c = summary.candidates[0]
        assert c.kind == ElementKind.WINDOW
        assert c.geometry["kind"] == "polyline"
        assert c.attrs["closed"] is False
        assert c.ifc_type == "IfcWindow"

    def test_closed_polyline_on_glaz_layer_becomes_window_polygon(self, tmp_path):
        # A-GLAZ is the glazing variant NCS codes — also maps to WINDOW.
        doc = _new_doc()
        _ensure_layer(doc, "A-GLAZ")
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (2, 0), (2, 0.2), (0, 0.2)],
            close=True,
            dxfattribs={"layer": "A-GLAZ"},
        )
        path = _write(doc, tmp_path / "glaz.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        c = summary.candidates[0]
        assert c.kind == ElementKind.WINDOW
        assert c.geometry["kind"] == "polygon"


class TestSplineWalls:
    """SPLINE walls (G-R1): flattened into polyline geometry."""

    def test_spline_on_wall_layer_becomes_wall_candidate(self, tmp_path):
        doc = _new_doc()
        _ensure_layer(doc, "A-WALL-EXTR")
        msp = doc.modelspace()
        msp.add_spline(
            fit_points=[(0, 0), (5, 1), (10, 0)],
            dxfattribs={"layer": "A-WALL-EXTR"},
        )
        path = _write(doc, tmp_path / "spline-wall.dxf")
        summary = dxf.read_dxf(path)

        assert len(summary.candidates) == 1
        c = summary.candidates[0]
        assert c.kind == ElementKind.WALL
        assert c.geometry["kind"] == "polyline"
        # ezdxf's flattening should give us many more points than the
        # 3 fit points for a decent approximation of a curve.
        assert len(c.geometry["points"]) >= 3
        assert c.attrs["source_entity"] == "SPLINE"
        assert c.attrs["flatten_distance"] == dxf.SPLINE_FLATTEN_DISTANCE
        # Endpoints should match the input fit points within flatten tolerance.
        first = c.geometry["points"][0]
        last = c.geometry["points"][-1]
        assert first["x"] == pytest.approx(0.0, abs=dxf.SPLINE_FLATTEN_DISTANCE)
        assert last["x"] == pytest.approx(10.0, abs=dxf.SPLINE_FLATTEN_DISTANCE)
