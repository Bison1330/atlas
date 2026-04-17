from atlas_core import (
    BoundingBox,
    Door,
    ElementKind,
    Point,
    Polygon,
    Polyline,
    Room,
    SheetDiscipline,
    StructuredDrawing,
    StructuredSheet,
    Units,
    Wall,
)


def _square(size: float = 10.0) -> Polygon:
    return Polygon(
        ring=[Point(x=0, y=0), Point(x=size, y=0), Point(x=size, y=size), Point(x=0, y=size)]
    )


def test_bounding_box_geometry():
    b = BoundingBox(minx=0, miny=0, maxx=5, maxy=3)
    assert b.width == 5
    assert b.height == 3
    assert b.area == 15


def test_structured_drawing_roundtrip():
    room = Room(name="Kitchen", number="101", boundary=_square(12), area=144.0)
    wall = Wall(
        centerline=Polyline(points=[Point(x=0, y=0), Point(x=12, y=0)]),
        thickness=0.5,
        is_exterior=True,
    )
    door = Door(width=3.0, height=7.0)
    sheet = StructuredSheet(
        sheet_number="A-101",
        title="First Floor Plan",
        discipline=SheetDiscipline.ARCHITECTURAL,
        units=Units.FEET,
        elements=[room, wall, door],
    )
    drawing = StructuredDrawing(project_name="Test Project", sheets=[sheet])

    dumped = drawing.model_dump_json()
    restored = StructuredDrawing.model_validate_json(dumped)

    assert restored.project_name == "Test Project"
    assert len(restored.sheets) == 1
    s = restored.sheets[0]
    assert s.sheet_number == "A-101"
    assert len(s.elements_of(ElementKind.ROOM)) == 1
    assert len(s.elements_of(ElementKind.WALL)) == 1
    assert len(s.elements_of(ElementKind.DOOR)) == 1


def test_sheet_by_number_lookup():
    d = StructuredDrawing(sheets=[StructuredSheet(sheet_number="A-101")])
    assert d.sheet_by_number("A-101") is not None
    assert d.sheet_by_number("A-999") is None


def test_element_ifc_and_ncs_fields_roundtrip():
    """IFC psets + NCS layer fields survive serialization."""
    wall = Wall(
        centerline=Polyline(points=[Point(x=0, y=0), Point(x=20, y=0)]),
        thickness=0.5,
        is_exterior=True,
        ncs_layer="A-WALL-EXTR-FULL",
        ncs_major_group="WALL",
        ncs_minor_group="EXTR",
        ifc_type="IfcWallStandardCase",
        ifc_properties={
            "Pset_WallCommon": {
                "IsExternal": True,
                "FireRating": "2HR",
                "LoadBearing": True,
            }
        },
        confidence=0.92,
    )
    door = Door(
        width=3.0,
        height=7.0,
        ncs_layer="A-DOOR",
        ncs_major_group="DOOR",
        ifc_type="IfcDoor",
        ifc_properties={"Pset_DoorCommon": {"FireRating": "1HR"}},
        host_wall_id=wall.id,
        confidence=0.85,
    )

    sheet = StructuredSheet(sheet_number="A-101", elements=[wall, door])

    restored = StructuredSheet.model_validate_json(sheet.model_dump_json())
    rwall, rdoor = restored.elements

    assert rwall.ncs_layer == "A-WALL-EXTR-FULL"
    assert rwall.ncs_major_group == "WALL"
    assert rwall.ifc_type == "IfcWallStandardCase"
    assert rwall.ifc_properties["Pset_WallCommon"]["FireRating"] == "2HR"
    assert rwall.ifc_properties["Pset_WallCommon"]["IsExternal"] is True
    assert rwall.confidence == 0.92

    assert rdoor.ifc_type == "IfcDoor"
    assert rdoor.ifc_properties["Pset_DoorCommon"]["FireRating"] == "1HR"
    assert rdoor.host_wall_id == wall.id


def test_element_confidence_can_be_null():
    """Deterministic / human-authored elements: confidence is None, not 1.0."""
    wall = Wall(
        centerline=Polyline(points=[Point(x=0, y=0), Point(x=10, y=0)]),
        confidence=None,
    )
    assert wall.confidence is None
    restored = Wall.model_validate_json(wall.model_dump_json())
    assert restored.confidence is None


def test_element_defaults_keep_existing_shape():
    """Backward-compat: M0 callers that don't set the new fields still work."""
    wall = Wall(centerline=Polyline(points=[Point(x=0, y=0), Point(x=5, y=0)]))
    assert wall.ncs_layer is None
    assert wall.ifc_type is None
    assert wall.ifc_properties == {}
    assert wall.confidence == 1.0
