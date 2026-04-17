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
        # as a wall (we want LINE / LWPOLYLINE there).
        msp.add_circle(center=(0, 0), radius=1, dxfattribs={"layer": "A-WALL"})
        path = _write(doc, tmp_path / "circle-on-wall.dxf")
        summary = dxf.read_dxf(path)
        assert summary.candidates == []
        assert summary.skipped_entity_types.get("CIRCLE") == 1
