"""Tests for the NCS layer-name parser."""

from __future__ import annotations

import pytest
from atlas_core import ElementKind

from worker.extractors import ncs


class TestParseLayer:
    def test_full_layer_with_all_fields(self):
        layer = ncs.parse_layer("A-WALL-EXTR-FULL-N")
        assert layer.discipline == "A"
        assert layer.major_group == "WALL"
        assert layer.minor_group == "EXTR"
        assert layer.modifier == "FULL"
        assert layer.status == "N"
        assert layer.is_well_formed
        assert layer.element_kind == ElementKind.WALL
        assert layer.discipline_name == "Architecture"

    def test_minimum_layer_discipline_plus_major(self):
        layer = ncs.parse_layer("A-WALL")
        assert layer.discipline == "A"
        assert layer.major_group == "WALL"
        assert layer.minor_group is None
        assert layer.modifier is None
        assert layer.status is None
        assert layer.is_well_formed

    def test_three_fields(self):
        layer = ncs.parse_layer("A-DOOR-OVHD")
        assert layer.discipline == "A"
        assert layer.major_group == "DOOR"
        assert layer.minor_group == "OVHD"
        assert layer.element_kind == ElementKind.DOOR

    def test_lowercase_input_normalized(self):
        layer = ncs.parse_layer("s-cols")
        assert layer.discipline == "S"
        assert layer.major_group == "COLS"
        assert layer.element_kind == ElementKind.COLUMN

    def test_whitespace_trimmed(self):
        assert ncs.parse_layer("  A-WALL  ").major_group == "WALL"

    def test_empty_input(self):
        layer = ncs.parse_layer("")
        assert layer.discipline is None
        assert layer.major_group is None
        assert not layer.is_well_formed
        assert layer.element_kind is None

    def test_none_safe(self):
        # parse_layer takes str but we accept the empty / None edge case gracefully.
        assert ncs.parse_layer("").is_well_formed is False


class TestWellFormedness:
    @pytest.mark.parametrize(
        "name",
        [
            "A-WALL",
            "A-WALL-EXTR",
            "S-COLS-CONC-N",
            "M-HVAC-DUCT",
            "I-FURN-FREE",
        ],
    )
    def test_canonical_layers_are_well_formed(self, name: str):
        assert ncs.parse_layer(name).is_well_formed

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "WALL",  # missing discipline
            "ZZZ-WALL",  # 3-letter "discipline"
            "1-WALL",  # numeric discipline
            "A-WALLEXTRA",  # group too long
            "A-W@LL",  # bad chars
            "Q1-WALL",  # discipline must be single letter
        ],
    )
    def test_malformed_layers_rejected(self, name: str):
        assert not ncs.parse_layer(name).is_well_formed

    def test_unknown_discipline_letter_rejected(self):
        # "B" is not in the NCS discipline list; should fail validation.
        assert not ncs.parse_layer("B-WALL").is_well_formed


class TestElementKindMapping:
    @pytest.mark.parametrize(
        ("layer", "kind"),
        [
            ("A-WALL", ElementKind.WALL),
            ("A-DOOR", ElementKind.DOOR),
            ("A-WIND", ElementKind.WINDOW),
            ("A-GLAZ", ElementKind.WINDOW),
            ("S-COLS", ElementKind.COLUMN),
            ("A-COLU", ElementKind.COLUMN),
            ("A-STRS", ElementKind.STAIR),
            ("A-ROOM", ElementKind.ROOM),
            ("A-AREA", ElementKind.ROOM),
            ("A-DIMS", ElementKind.DIMENSION),
            ("A-ANNO", ElementKind.ANNOTATION),
            ("A-SYMB", ElementKind.SYMBOL),
        ],
    )
    def test_known_major_groups_map_correctly(self, layer: str, kind: ElementKind):
        assert ncs.parse_layer(layer).element_kind == kind

    def test_unknown_major_group_falls_through_to_other(self):
        # Well-formed layer, unknown Major → OTHER (not None).
        assert ncs.parse_layer("A-XYZ").element_kind == ElementKind.OTHER

    def test_malformed_layer_returns_none_kind(self):
        # Malformed → None (not OTHER), so callers can distinguish
        # "couldn't parse" from "parsed but unknown classification".
        assert ncs.parse_layer("not-a-layer").element_kind is None


class TestBatch:
    def test_parse_layers_preserves_order(self):
        layers = ncs.parse_layers(["A-WALL", "A-DOOR", "S-COLS"])
        assert [layer.major_group for layer in layers] == ["WALL", "DOOR", "COLS"]
