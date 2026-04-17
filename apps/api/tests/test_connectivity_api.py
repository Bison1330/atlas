"""Tests for GET /drawings/{id}/connectivity.

Seeds rooms + doors directly so we exercise the route + adjacency
recomputation without depending on the full M2 worker pipeline. The
worker-side post-pass (which actually populates host_element_id
from a real DXF) is covered by the orchestrator tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import Drawing, Element, ElementSource, Sheet
from app.main import app
from tests.conftest import TEST_USER_ID


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _seed_two_room_plan(db) -> dict:
    """Two adjacent 5x10 rooms separated by a wall at x=5, with a door at (5, 5)."""
    d = Drawing(
        source_filename="x.dxf", source_s3_key="k", size_bytes=1,
        content_hash=f"sha256:conn-{uuid4().hex[:8]}",
        owner_id=TEST_USER_ID,
    )
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.flush()
    src = ElementSource(
        drawing_id=d.id, source_kind="extraction",
        producer_name="dxf_ncs_extractor", producer_version="0.1.0",
        status="completed", finished_at=datetime.now(UTC),
    )
    db.add(src)
    db.flush()

    # The two derived rooms.
    r1 = Element(
        sheet_id=s.id, source_id=src.id, kind="room",
        ifc_type="IfcSpace",
        geometry={"kind": "polygon", "ring": [
            {"x": 0, "y": 0}, {"x": 5, "y": 0},
            {"x": 5, "y": 10}, {"x": 0, "y": 10},
        ]},
        bbox={"minx": 0, "miny": 0, "maxx": 5, "maxy": 10},
        attrs={"derived": True, "derivation": "wall_loop", "area": 50.0},
    )
    r2 = Element(
        sheet_id=s.id, source_id=src.id, kind="room",
        ifc_type="IfcSpace",
        geometry={"kind": "polygon", "ring": [
            {"x": 5, "y": 0}, {"x": 10, "y": 0},
            {"x": 10, "y": 10}, {"x": 5, "y": 10},
        ]},
        bbox={"minx": 5, "miny": 0, "maxx": 10, "maxy": 10},
        attrs={"derived": True, "derivation": "wall_loop", "area": 50.0},
    )
    db.add_all([r1, r2])
    db.flush()

    # The door on the partition between R1 and R2.
    door = Element(
        sheet_id=s.id, source_id=src.id, kind="door",
        ifc_type="IfcDoor",
        geometry={
            "kind": "arc",
            "center": {"x": 5.0, "y": 5.0},
            "radius": 1.0,
            "start_angle_deg": 0.0,
            "end_angle_deg": 90.0,
        },
        attrs={"swing_angle_deg": 90.0},
    )
    db.add(door)
    db.commit()
    return {
        "drawing_id": d.id, "source_id": src.id,
        "room_ids": [r1.id, r2.id], "door_id": door.id,
    }


class TestConnectivityApi:
    def test_returns_rooms_doors_and_one_adjacency(self, client, db):
        seeded = _seed_two_room_plan(db)
        r = client.get(f"/drawings/{seeded['drawing_id']}/connectivity")
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["drawing_id"] == str(seeded["drawing_id"])
        assert body["source_id"] == str(seeded["source_id"])
        assert len(body["rooms"]) == 2
        assert len(body["doors"]) == 1
        assert len(body["adjacencies"]) == 1

        edge = body["adjacencies"][0]
        room_ids = {str(rid) for rid in seeded["room_ids"]}
        assert {edge["room_a_id"], edge["room_b_id"]} == room_ids
        assert edge["door_id"] == str(seeded["door_id"])

    def test_rooms_carry_derived_flag(self, client, db):
        seeded = _seed_two_room_plan(db)
        body = client.get(f"/drawings/{seeded['drawing_id']}/connectivity").json()
        for room in body["rooms"]:
            assert room["derived"] is True
            assert room["area"] == pytest.approx(50.0)
            assert room["bbox"] is not None
            assert len(room["ring"]) == 4

    def test_door_includes_center_and_swing(self, client, db):
        seeded = _seed_two_room_plan(db)
        body = client.get(f"/drawings/{seeded['drawing_id']}/connectivity").json()
        door = body["doors"][0]
        assert door["center"] == {"x": 5.0, "y": 5.0}
        assert door["swing_angle_deg"] == 90.0

    def test_no_extraction_returns_empty(self, client, db):
        d = Drawing(
            source_filename="x.dxf", source_s3_key="k", size_bytes=1,
            content_hash="sha256:conn-empty",
                    owner_id=TEST_USER_ID,
        )
        db.add(d)
        db.commit()
        body = client.get(f"/drawings/{d.id}/connectivity").json()
        assert body["source_id"] is None
        assert body["rooms"] == []
        assert body["doors"] == []
        assert body["adjacencies"] == []

    def test_unknown_drawing_returns_404(self, client):
        # M7: auth + ownership treat unknown drawings as 404 so callers
        # can't enumerate drawing ids owned by other users.
        r = client.get(f"/drawings/{uuid4()}/connectivity")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"

    def test_explicit_source_id_filters_correctly(self, client, db):
        seeded = _seed_two_room_plan(db)
        # Explicit pin to the only source.
        body = client.get(
            f"/drawings/{seeded['drawing_id']}/connectivity"
            f"?source_id={seeded['source_id']}"
        ).json()
        assert body["source_id"] == str(seeded["source_id"])
        assert len(body["rooms"]) == 2

        # Unknown source_id → empty.
        body2 = client.get(
            f"/drawings/{seeded['drawing_id']}/connectivity?source_id={uuid4()}"
        ).json()
        # source_id we requested gets echoed; rooms/doors are empty.
        assert body2["rooms"] == []
        assert body2["doors"] == []

    def test_door_on_exterior_wall_no_edge(self, client, db):
        """A door touching only one room should not create an adjacency edge."""
        d = Drawing(
            source_filename="x.dxf", source_s3_key="k", size_bytes=1,
            content_hash="sha256:conn-ext",
                    owner_id=TEST_USER_ID,
        )
        db.add(d)
        db.flush()
        s = Sheet(drawing_id=d.id, page_number=1)
        db.add(s)
        db.flush()
        src = ElementSource(
            drawing_id=d.id, source_kind="extraction",
            producer_name="x", producer_version="0.1.0",
            status="completed", finished_at=datetime.now(UTC),
        )
        db.add(src)
        db.flush()
        # One room.
        db.add(Element(
            sheet_id=s.id, source_id=src.id, kind="room",
            geometry={"kind": "polygon", "ring": [
                {"x": 0, "y": 0}, {"x": 10, "y": 0},
                {"x": 10, "y": 10}, {"x": 0, "y": 10},
            ]},
            attrs={"derived": True, "area": 100.0},
        ))
        # Door on the south exterior wall.
        db.add(Element(
            sheet_id=s.id, source_id=src.id, kind="door",
            geometry={
                "kind": "arc", "center": {"x": 5, "y": 0},
                "radius": 1, "start_angle_deg": 0, "end_angle_deg": 90,
            },
        ))
        db.commit()
        body = client.get(f"/drawings/{d.id}/connectivity").json()
        assert len(body["rooms"]) == 1
        assert len(body["doors"]) == 1
        assert body["adjacencies"] == []
