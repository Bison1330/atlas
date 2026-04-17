"""Database-level tests for the ingest ORM models.

These exercise the actual Postgres CHECK and UNIQUE constraints — i.e.
the behavior that would bite us in production — rather than just the
SQLAlchemy mapper.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Drawing, Element, ElementSource, Sheet, Tile
from tests.conftest import TEST_USER_ID


def _make_drawing(**overrides) -> Drawing:
    defaults = dict(
        source_filename="plans.pdf",
        source_s3_key="drawings/xyz/source.pdf",
        size_bytes=1024,
        content_hash="sha256:deadbeef",
        owner_id=TEST_USER_ID,
    )
    defaults.update(overrides)
    return Drawing(**defaults)


def test_drawing_defaults(db: Session) -> None:
    d = _make_drawing()
    db.add(d)
    db.commit()
    db.refresh(d)

    assert d.status == "queued"
    assert d.progress_percent == 0
    assert d.extra == {}
    assert d.created_at is not None
    assert d.updated_at is not None


def test_drawing_status_check_constraint(db: Session) -> None:
    d = _make_drawing()
    d.status = "not-a-real-status"
    db.add(d)
    with pytest.raises(IntegrityError):
        db.commit()


def test_drawing_progress_range_constraint(db: Session) -> None:
    d = _make_drawing()
    d.progress_percent = 150
    db.add(d)
    with pytest.raises(IntegrityError):
        db.commit()


def test_sheet_uniqueness_on_page_number(db: Session) -> None:
    d = _make_drawing()
    db.add(d)
    db.flush()

    db.add(Sheet(drawing_id=d.id, page_number=1))
    db.add(Sheet(drawing_id=d.id, page_number=1))
    with pytest.raises(IntegrityError):
        db.commit()


def test_tile_coordinate_uniqueness(db: Session) -> None:
    d = _make_drawing()
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.flush()

    db.add(
        Tile(
            sheet_id=s.id,
            zoom_level=2,
            col=3,
            row=4,
            s3_key="drawings/xyz/tiles/2/3/4.webp",
        )
    )
    db.add(
        Tile(
            sheet_id=s.id,
            zoom_level=2,
            col=3,
            row=4,
            s3_key="another-key.webp",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_cascade_delete_drawing_removes_sheets_and_tiles(db: Session) -> None:
    d = _make_drawing()
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.flush()
    db.add(
        Tile(
            sheet_id=s.id,
            zoom_level=0,
            col=0,
            row=0,
            s3_key="drawings/xyz/tiles/0/0/0.webp",
        )
    )
    db.commit()

    drawing_id = d.id
    sheet_id = s.id

    db.delete(d)
    db.commit()
    db.expire_all()

    assert db.get(Drawing, drawing_id) is None
    assert db.get(Sheet, sheet_id) is None
    assert db.query(Tile).filter(Tile.sheet_id == sheet_id).count() == 0


def test_sheets_ordered_by_page_number(db: Session) -> None:
    d = _make_drawing()
    db.add(d)
    db.flush()
    db.add_all(
        [
            Sheet(drawing_id=d.id, page_number=3),
            Sheet(drawing_id=d.id, page_number=1),
            Sheet(drawing_id=d.id, page_number=2),
        ]
    )
    db.commit()
    db.refresh(d)

    assert [s.page_number for s in d.sheets] == [1, 2, 3]


# ---------- M2: element_sources + elements ----------


def _seed_drawing_and_sheet(db: Session) -> tuple[Drawing, Sheet]:
    d = _make_drawing()
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.flush()
    return d, s


def _make_source(drawing: Drawing, **overrides) -> ElementSource:
    defaults = dict(
        drawing_id=drawing.id,
        source_kind="extraction",
        producer_name="ncs_layer_parser",
        producer_version="0.1.0",
    )
    defaults.update(overrides)
    return ElementSource(**defaults)


def test_element_source_defaults(db: Session) -> None:
    d, _ = _seed_drawing_and_sheet(db)
    src = _make_source(d)
    db.add(src)
    db.commit()
    db.refresh(src)

    assert src.status == "queued"
    assert src.params == {}
    assert src.summary == {}
    assert src.created_at is not None


def test_element_source_kind_check(db: Session) -> None:
    d, _ = _seed_drawing_and_sheet(db)
    src = _make_source(d, source_kind="bogus")
    db.add(src)
    with pytest.raises(IntegrityError):
        db.commit()


def test_element_source_status_check(db: Session) -> None:
    d, _ = _seed_drawing_and_sheet(db)
    src = _make_source(d)
    src.status = "exploded"
    db.add(src)
    with pytest.raises(IntegrityError):
        db.commit()


def test_element_polymorphic_roundtrip(db: Session) -> None:
    """Wall + door + room with full IFC + NCS metadata roundtrip cleanly."""
    d, sh = _seed_drawing_and_sheet(db)
    src = _make_source(d)
    db.add(src)
    db.flush()

    wall = Element(
        sheet_id=sh.id,
        source_id=src.id,
        kind="wall",
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
        geometry={
            "kind": "polyline",
            "points": [{"x": 0, "y": 0}, {"x": 20, "y": 0}],
        },
        attrs={"thickness": 0.5, "is_exterior": True},
        bbox={"minx": 0, "miny": -0.25, "maxx": 20, "maxy": 0.25},
        confidence=0.92,
    )
    db.add(wall)
    db.flush()

    door = Element(
        sheet_id=sh.id,
        source_id=src.id,
        kind="door",
        host_element_id=wall.id,
        ncs_layer="A-DOOR",
        ncs_major_group="DOOR",
        ifc_type="IfcDoor",
        ifc_properties={"Pset_DoorCommon": {"FireRating": "1HR"}},
        attrs={"width": 3.0, "height": 7.0, "swing_angle_deg": 90.0},
        confidence=0.85,
    )
    room = Element(
        sheet_id=sh.id,
        source_id=src.id,
        kind="room",
        name="Kitchen",
        number="101",
        ifc_type="IfcSpace",
        geometry={
            "kind": "polygon",
            "ring": [
                {"x": 0, "y": 0},
                {"x": 12, "y": 0},
                {"x": 12, "y": 12},
                {"x": 0, "y": 12},
            ],
        },
        attrs={"area": 144.0},
        confidence=None,  # deterministic — not probabilistic
    )
    db.add_all([door, room])
    db.commit()

    db.expire_all()
    fetched = (
        db.query(Element)
        .filter(Element.sheet_id == sh.id)
        .order_by(Element.kind)
        .all()
    )
    assert [e.kind for e in fetched] == ["door", "room", "wall"]

    fdoor = next(e for e in fetched if e.kind == "door")
    assert fdoor.host_element_id == wall.id
    assert fdoor.ifc_properties["Pset_DoorCommon"]["FireRating"] == "1HR"
    assert fdoor.attrs["swing_angle_deg"] == 90.0

    froom = next(e for e in fetched if e.kind == "room")
    assert froom.confidence is None
    assert froom.geometry["kind"] == "polygon"
    assert len(froom.geometry["ring"]) == 4

    fwall = next(e for e in fetched if e.kind == "wall")
    assert fwall.ncs_major_group == "WALL"
    assert fwall.ifc_properties["Pset_WallCommon"]["IsExternal"] is True


def test_element_kind_check_constraint(db: Session) -> None:
    d, sh = _seed_drawing_and_sheet(db)
    src = _make_source(d)
    db.add(src)
    db.flush()
    db.add(Element(sheet_id=sh.id, source_id=src.id, kind="not-a-kind"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_element_confidence_range_check(db: Session) -> None:
    d, sh = _seed_drawing_and_sheet(db)
    src = _make_source(d)
    db.add(src)
    db.flush()
    db.add(
        Element(sheet_id=sh.id, source_id=src.id, kind="wall", confidence=1.5)
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_element_confidence_null_is_allowed(db: Session) -> None:
    """confidence=None means deterministic / human-authored — must not trip the CHECK."""
    d, sh = _seed_drawing_and_sheet(db)
    src = _make_source(d, source_kind="manual_override", producer_name="human")
    db.add(src)
    db.flush()
    e = Element(sheet_id=sh.id, source_id=src.id, kind="wall", confidence=None)
    db.add(e)
    db.commit()
    db.refresh(e)
    assert e.confidence is None


def test_element_host_set_null_on_wall_delete(db: Session) -> None:
    """Deleting a host wall leaves its hosted door alive with host_element_id NULL."""
    d, sh = _seed_drawing_and_sheet(db)
    src = _make_source(d)
    db.add(src)
    db.flush()
    wall = Element(sheet_id=sh.id, source_id=src.id, kind="wall")
    db.add(wall)
    db.flush()
    door = Element(
        sheet_id=sh.id, source_id=src.id, kind="door", host_element_id=wall.id
    )
    db.add(door)
    db.commit()

    door_id = door.id
    db.delete(wall)
    db.commit()
    db.expire_all()

    fdoor = db.get(Element, door_id)
    assert fdoor is not None
    assert fdoor.host_element_id is None


def test_drawing_delete_cascades_to_sources_and_elements(db: Session) -> None:
    d, sh = _seed_drawing_and_sheet(db)
    src = _make_source(d)
    db.add(src)
    db.flush()
    db.add_all(
        [
            Element(sheet_id=sh.id, source_id=src.id, kind="wall"),
            Element(sheet_id=sh.id, source_id=src.id, kind="door"),
        ]
    )
    db.commit()

    src_id = src.id
    db.delete(d)
    db.commit()
    db.expire_all()

    assert db.get(ElementSource, src_id) is None
    assert db.query(Element).count() == 0


def test_re_extraction_keeps_old_elements(db: Session) -> None:
    """A second extraction run produces a parallel set of elements; old ones stay."""
    d, sh = _seed_drawing_and_sheet(db)
    src1 = _make_source(d, producer_version="0.1.0")
    db.add(src1)
    db.flush()
    db.add(Element(sheet_id=sh.id, source_id=src1.id, kind="wall"))
    db.commit()

    src2 = _make_source(d, producer_version="0.2.0")
    db.add(src2)
    db.flush()
    db.add_all(
        [
            Element(sheet_id=sh.id, source_id=src2.id, kind="wall"),
            Element(sheet_id=sh.id, source_id=src2.id, kind="door"),
        ]
    )
    db.commit()

    by_source = {
        sid: db.query(Element).filter(Element.source_id == sid).count()
        for sid in (src1.id, src2.id)
    }
    assert by_source == {src1.id: 1, src2.id: 2}
