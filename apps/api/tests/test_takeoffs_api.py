"""Tests for GET /drawings/{id}/takeoffs.

Real DB interactions — seeds drawings/sheets/sources/elements and
asserts the route resolves the right source, aggregates correctly,
and renders the units caveat.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import Drawing, Element, ElementSource, Sheet
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _seed(db, *, walls: int = 0, rooms: int = 0, doors: int = 0) -> dict:
    """Seed a drawing+sheet+source plus N walls/rooms/doors.

    Walls are 10 units long, rooms are 10×8 (80 area), doors are countless.
    """
    d = Drawing(
        source_filename="x.dxf", source_s3_key="k", size_bytes=1,
        content_hash=f"sha256:takeoff-{uuid4().hex[:8]}",
    )
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.flush()
    src = ElementSource(
        drawing_id=d.id, source_kind="extraction",
        producer_name="dxf_ncs_extractor", producer_version="0.1.0",
        status="completed",
        finished_at=datetime.now(UTC),
    )
    db.add(src)
    db.flush()
    for i in range(walls):
        db.add(Element(
            sheet_id=s.id, source_id=src.id, kind="wall",
            ncs_layer="A-WALL-EXTR", ncs_major_group="WALL", ncs_minor_group="EXTR",
            geometry={
                "kind": "polyline",
                "points": [{"x": 0, "y": i}, {"x": 10, "y": i}],
            },
        ))
    for _ in range(rooms):
        db.add(Element(
            sheet_id=s.id, source_id=src.id, kind="room",
            ncs_major_group="ROOM",
            geometry={
                "kind": "polygon",
                "ring": [
                    {"x": 0, "y": 0}, {"x": 10, "y": 0},
                    {"x": 10, "y": 8}, {"x": 0, "y": 8},
                ],
            },
        ))
    for _ in range(doors):
        db.add(Element(
            sheet_id=s.id, source_id=src.id, kind="door",
            ncs_major_group="DOOR",
        ))
    db.commit()
    return {"drawing_id": d.id, "source_id": src.id, "sheet_id": s.id}


# ---- happy paths ----


class TestTakeoffsApi:
    def test_walls_rooms_doors_aggregate(self, client, db):
        seeded = _seed(db, walls=4, rooms=1, doors=1)
        r = client.get(f"/drawings/{seeded['drawing_id']}/takeoffs")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["drawing_id"] == str(seeded["drawing_id"])
        assert body["source_id"] == str(seeded["source_id"])
        assert body["total_elements"] == 6
        assert sorted(body["kinds_present"]) == ["door", "room", "wall"]

        cats = {c["kind"]: c for c in body["categories"]}
        assert cats["wall"]["count"] == 4
        assert cats["wall"]["total_linear_units"] == pytest.approx(40.0)
        assert cats["room"]["count"] == 1
        assert cats["room"]["total_area_units"] == pytest.approx(80.0)
        assert cats["door"]["count"] == 1
        # Doors don't carry linear/area aggregates.
        assert cats["door"]["total_linear_units"] is None
        assert cats["door"]["total_area_units"] is None

    def test_response_includes_units_caveat(self, client, db):
        seeded = _seed(db, walls=1)
        body = client.get(f"/drawings/{seeded['drawing_id']}/takeoffs").json()
        assert body["units"]["linear"] == "DXF units"
        assert "ft/in/m/mm" in body["units"]["note"]

    def test_no_completed_extraction_returns_empty(self, client, db):
        # Drawing exists but no extraction at all.
        d = Drawing(
            source_filename="x.dxf", source_s3_key="k", size_bytes=1,
            content_hash="sha256:no-extraction",
        )
        db.add(d)
        db.commit()
        r = client.get(f"/drawings/{d.id}/takeoffs")
        assert r.status_code == 200
        body = r.json()
        assert body["source_id"] is None
        assert body["total_elements"] == 0
        assert body["categories"] == []

    def test_unknown_drawing_returns_empty(self, client):
        r = client.get(f"/drawings/{uuid4()}/takeoffs")
        assert r.status_code == 200
        assert r.json()["total_elements"] == 0
        assert r.json()["source_id"] is None

    def test_ignores_running_and_failed_runs(self, client, db):
        d = Drawing(
            source_filename="x.dxf", source_s3_key="k", size_bytes=1,
            content_hash="sha256:status-filter",
        )
        db.add(d)
        db.flush()
        s = Sheet(drawing_id=d.id, page_number=1)
        db.add(s)
        db.flush()
        # A failed and a running source should NOT be the default pick.
        for status in ("failed", "running"):
            src = ElementSource(
                drawing_id=d.id, source_kind="extraction",
                producer_name="x", producer_version="0.1.0",
                status=status,
            )
            db.add(src)
            db.flush()
            db.add(Element(
                sheet_id=s.id, source_id=src.id, kind="wall",
                geometry={"kind": "polyline",
                          "points": [{"x": 0, "y": 0}, {"x": 999, "y": 0}]},
            ))
        db.commit()
        body = client.get(f"/drawings/{d.id}/takeoffs").json()
        assert body["source_id"] is None
        assert body["total_elements"] == 0


# ---- source resolution ----


class TestSourceResolution:
    def test_explicit_source_id_wins(self, client, db):
        # Two completed runs; explicitly request the older one.
        seeded_old = _seed(db, walls=1)
        # Backdate the first source so it's clearly "older".
        from app.db import ElementSource as ES
        old = db.get(ES, seeded_old["source_id"])
        old.finished_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()

        # Add a second run on the SAME drawing with different content.
        s = db.execute(
            __import__("sqlalchemy").select(Sheet).where(
                Sheet.drawing_id == seeded_old["drawing_id"]
            )
        ).scalar_one()
        new_src = ES(
            drawing_id=seeded_old["drawing_id"],
            source_kind="extraction", producer_name="x",
            producer_version="0.2.0", status="completed",
            finished_at=datetime.now(UTC),
        )
        db.add(new_src)
        db.flush()
        db.add(Element(
            sheet_id=s.id, source_id=new_src.id, kind="wall",
            geometry={"kind": "polyline",
                      "points": [{"x": 0, "y": 0}, {"x": 100, "y": 0}]},
        ))
        db.commit()

        # No source_id: latest (new) wins.
        latest = client.get(
            f"/drawings/{seeded_old['drawing_id']}/takeoffs"
        ).json()
        assert latest["source_id"] == str(new_src.id)
        wall = next(c for c in latest["categories"] if c["kind"] == "wall")
        assert wall["total_linear_units"] == pytest.approx(100.0)

        # Explicit old source_id: old run.
        explicit = client.get(
            f"/drawings/{seeded_old['drawing_id']}/takeoffs"
            f"?source_id={seeded_old['source_id']}"
        ).json()
        assert explicit["source_id"] == str(seeded_old["source_id"])
        wall_old = next(c for c in explicit["categories"] if c["kind"] == "wall")
        assert wall_old["total_linear_units"] == pytest.approx(10.0)


# ---- subcategory shape ----


class TestSubcategories:
    def test_wall_subcategories_by_minor_group(self, client, db):
        d = Drawing(
            source_filename="x.dxf", source_s3_key="k", size_bytes=1,
            content_hash="sha256:wall-subs",
        )
        db.add(d)
        db.flush()
        s = Sheet(drawing_id=d.id, page_number=1)
        db.add(s)
        db.flush()
        src = ElementSource(
            drawing_id=d.id, source_kind="extraction",
            producer_name="x", producer_version="0.1.0", status="completed",
            finished_at=datetime.now(UTC),
        )
        db.add(src)
        db.flush()
        # 2 EXTR walls + 1 INTR wall.
        for minor, length in [("EXTR", 10), ("EXTR", 20), ("INTR", 5)]:
            db.add(Element(
                sheet_id=s.id, source_id=src.id, kind="wall",
                ncs_layer=f"A-WALL-{minor}",
                ncs_major_group="WALL", ncs_minor_group=minor,
                geometry={"kind": "polyline",
                          "points": [{"x": 0, "y": 0}, {"x": length, "y": 0}]},
            ))
        db.commit()

        body = client.get(f"/drawings/{d.id}/takeoffs").json()
        wall = next(c for c in body["categories"] if c["kind"] == "wall")
        assert wall["count"] == 3
        assert wall["total_linear_units"] == pytest.approx(35.0)
        subs = {s["label"]: s for s in wall["subcategories"]}
        assert subs["NCS EXTR"]["count"] == 2
        assert subs["NCS EXTR"]["linear_units"] == pytest.approx(30.0)
        assert subs["NCS INTR"]["count"] == 1
        assert subs["NCS INTR"]["linear_units"] == pytest.approx(5.0)
