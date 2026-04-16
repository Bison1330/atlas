"""Database-level tests for the ingest ORM models.

These exercise the actual Postgres CHECK and UNIQUE constraints — i.e.
the behavior that would bite us in production — rather than just the
SQLAlchemy mapper.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Drawing, Sheet, Tile


def _make_drawing(**overrides) -> Drawing:
    defaults = dict(
        source_filename="plans.pdf",
        source_s3_key="drawings/xyz/source.pdf",
        size_bytes=1024,
        content_hash="sha256:deadbeef",
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
