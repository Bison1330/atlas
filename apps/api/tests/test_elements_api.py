"""Tests for GET /drawings/{id}/elements.

Direct DB-fixture tests — we insert Drawing + Sheet + ElementSource
+ Element rows by hand and verify the API response shape, filters,
and the progressive-disclosure ``include=geometry`` behavior.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Drawing, Element, ElementSource, Sheet
from app.main import app
from tests.conftest import TEST_USER_ID


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _seed(db: Session, *, n_walls: int = 2, n_doors: int = 1) -> dict:
    d = Drawing(
        source_filename="x.dxf",
        source_s3_key="drawings/x/source.dxf",
        size_bytes=1,
        content_hash="sha256:elements-api",
            owner_id=TEST_USER_ID,
        )
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.flush()
    src = ElementSource(
        drawing_id=d.id,
        source_kind="extraction",
        producer_name="dxf_ncs_extractor",
        producer_version="0.1.0",
        status="completed",
    )
    db.add(src)
    db.flush()

    for i in range(n_walls):
        db.add(Element(
            sheet_id=s.id, source_id=src.id, kind="wall",
            ncs_layer="A-WALL-EXTR", ncs_major_group="WALL", ncs_minor_group="EXTR",
            ifc_type="IfcWallStandardCase",
            ifc_properties={"Pset_WallCommon": {"IsExternal": True}},
            geometry={
                "kind": "polyline",
                "points": [{"x": 0, "y": i}, {"x": 10, "y": i}],
            },
            attrs={"thickness": 0.5},
            bbox={"minx": 0, "miny": i, "maxx": 10, "maxy": i},
            confidence=0.95,
        ))
    for i in range(n_doors):
        db.add(Element(
            sheet_id=s.id, source_id=src.id, kind="door",
            ncs_layer="A-DOOR", ncs_major_group="DOOR",
            ifc_type="IfcDoor",
            geometry={"kind": "arc", "center": {"x": 0, "y": 0}, "radius": 3,
                      "start_angle_deg": 0, "end_angle_deg": 90},
            attrs={"swing_angle_deg": 90.0 + i},
            bbox={"minx": -3, "miny": -3, "maxx": 3, "maxy": 3},
            confidence=0.85,
        ))
    db.commit()
    return {"drawing_id": d.id, "sheet_id": s.id, "source_id": src.id}


# -------- core listing --------


class TestListElements:
    def test_returns_all_elements_for_drawing(self, client, db: Session):
        seeded = _seed(db, n_walls=3, n_doors=2)
        r = client.get(f"/drawings/{seeded['drawing_id']}/elements")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 5
        assert body["drawing_id"] == str(seeded["drawing_id"])
        kinds = sorted(e["kind"] for e in body["elements"])
        assert kinds == ["door", "door", "wall", "wall", "wall"]

    def test_unknown_drawing_returns_404(self, client):
        # M7: ownership-resolution 404s unknown drawings so callers
        # can't enumerate drawing ids owned by other users.
        r = client.get(f"/drawings/{uuid4()}/elements")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"

    def test_summary_default_omits_geometry_and_attrs(self, client, db: Session):
        seeded = _seed(db, n_walls=1, n_doors=0)
        r = client.get(f"/drawings/{seeded['drawing_id']}/elements")
        assert r.status_code == 200
        e = r.json()["elements"][0]
        # Summary fields present.
        assert "kind" in e and "confidence" in e and "bbox" in e
        assert e["ifc_type"] == "IfcWallStandardCase"
        assert e["ncs_major_group"] == "WALL"
        # Heavy fields absent.
        assert "geometry" not in e
        assert "attrs" not in e
        assert "ifc_properties" not in e

    def test_include_geometry_returns_full_payload(self, client, db: Session):
        seeded = _seed(db, n_walls=1, n_doors=0)
        r = client.get(
            f"/drawings/{seeded['drawing_id']}/elements?include=geometry"
        )
        assert r.status_code == 200
        e = r.json()["elements"][0]
        assert e["geometry"]["kind"] == "polyline"
        assert len(e["geometry"]["points"]) == 2
        assert e["attrs"]["thickness"] == 0.5
        assert e["ifc_properties"]["Pset_WallCommon"]["IsExternal"] is True


# -------- filters --------


class TestFilters:
    def test_kind_filter_single(self, client, db: Session):
        seeded = _seed(db, n_walls=2, n_doors=3)
        r = client.get(f"/drawings/{seeded['drawing_id']}/elements?kind=door")
        body = r.json()
        assert body["count"] == 3
        assert all(e["kind"] == "door" for e in body["elements"])

    def test_kind_filter_repeated(self, client, db: Session):
        seeded = _seed(db, n_walls=2, n_doors=1)
        r = client.get(
            f"/drawings/{seeded['drawing_id']}/elements?kind=wall&kind=door"
        )
        assert r.json()["count"] == 3

    def test_source_id_filter(self, client, db: Session):
        seeded = _seed(db, n_walls=2, n_doors=1)
        r = client.get(
            f"/drawings/{seeded['drawing_id']}/elements"
            f"?source_id={seeded['source_id']}"
        )
        assert r.json()["count"] == 3

        r2 = client.get(
            f"/drawings/{seeded['drawing_id']}/elements?source_id={uuid4()}"
        )
        assert r2.json()["count"] == 0

    def test_ncs_major_group_filter(self, client, db: Session):
        seeded = _seed(db, n_walls=2, n_doors=2)
        r = client.get(
            f"/drawings/{seeded['drawing_id']}/elements?ncs_major_group=WALL"
        )
        body = r.json()
        assert body["count"] == 2
        assert {e["ncs_major_group"] for e in body["elements"]} == {"WALL"}

    def test_combined_filters(self, client, db: Session):
        seeded = _seed(db, n_walls=2, n_doors=2)
        r = client.get(
            f"/drawings/{seeded['drawing_id']}/elements"
            f"?kind=door&ncs_major_group=DOOR"
        )
        assert r.json()["count"] == 2

    def test_limit_param(self, client, db: Session):
        seeded = _seed(db, n_walls=5, n_doors=0)
        r = client.get(f"/drawings/{seeded['drawing_id']}/elements?limit=2")
        assert r.json()["count"] == 2
