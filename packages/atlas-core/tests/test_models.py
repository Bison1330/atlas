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
