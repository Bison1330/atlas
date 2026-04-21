"""Tests for GET /drawings/{id}/sheets/{id}/model3d.

Covers: happy path, empty sheet, 404, 403 via cross-user ownership,
ETag 304, Redis cache HIT/MISS, response-stats shape, and a real-data
end-to-end against the apartment-grid fixture run through the actual
DXF extractor.

The real-data test re-runs extraction inside the test because the
``db`` fixture truncates between tests — we can't rely on anything
pre-staged outside the test suite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Drawing, Element, ElementSource, Sheet, User
from app.main import app
from tests.conftest import TEST_USER_ID

# The worker package lives alongside the api in the monorepo but
# isn't on the api's sys.path by default. We need ``worker.jobs.extract``
# (top-level ``worker`` package) for the real-data test; the DXF
# builders live under ``worker/tests/fixtures/`` which would collide
# with the api's own ``tests`` package, so load that one directly via
# importlib in the test body.
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "apps" / "worker"))


def _load_apartment_builder():
    path = _REPO_ROOT / "apps" / "worker" / "tests" / "fixtures" / "dxf_builders.py"
    spec = importlib.util.spec_from_file_location("_worker_dxf_builders", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_apartment_grid_floor


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Synthetic seeding — mirrors the shape real extraction writes, without
# needing to actually run the worker.
# ---------------------------------------------------------------------------


def _seed_minimal_sheet(db: Session) -> dict[str, UUID]:
    """One drawing / one sheet / no elements — for empty-scene + 404 tests."""
    d = Drawing(
        source_filename="empty.dxf",
        source_s3_key="drawings/empty/source.dxf",
        size_bytes=1,
        content_hash="sha256:model3d-empty",
        owner_id=TEST_USER_ID,
    )
    db.add(d)
    db.flush()
    s = Sheet(drawing_id=d.id, page_number=1)
    db.add(s)
    db.commit()
    return {"drawing_id": d.id, "sheet_id": s.id}


def _seed_square_room_sheet(db: Session) -> dict[str, UUID]:
    """A 4-wall square + 1 door + 1 explicit room. Enough to assert
    non-empty scene, stats correctness, and the host/wall bookkeeping."""
    d = Drawing(
        source_filename="square.dxf",
        source_s3_key="drawings/square/source.dxf",
        size_bytes=1,
        content_hash="sha256:model3d-square",
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

    walls_coords = [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 10)),
        ((10, 10), (0, 10)),
        ((0, 10), (0, 0)),
    ]
    wall_ids: list[UUID] = []
    for a, b in walls_coords:
        w = Element(
            sheet_id=s.id, source_id=src.id, kind="wall",
            source_layer="A-WALL-EXTR",
            ncs_major_group="WALL", ncs_minor_group="EXTR",
            geometry={
                "kind": "polyline",
                "points": [{"x": a[0], "y": a[1]}, {"x": b[0], "y": b[1]}],
            },
            bbox={"minx": min(a[0], b[0]), "miny": min(a[1], b[1]),
                  "maxx": max(a[0], b[0]), "maxy": max(a[1], b[1])},
            attrs={"source_entity": "LINE"},
            ifc_properties={},
        )
        db.add(w)
        db.flush()
        wall_ids.append(w.id)

    # ARC-style door on the south wall at x=5.
    door = Element(
        sheet_id=s.id, source_id=src.id, kind="door",
        source_layer="A-DOOR", ncs_major_group="DOOR",
        host_element_id=wall_ids[0],
        geometry={
            "kind": "arc", "center": {"x": 5, "y": 0},
            "radius": 1.0, "start_angle_deg": 0.0, "end_angle_deg": 90.0,
        },
        bbox={"minx": 4, "miny": -1, "maxx": 6, "maxy": 1},
        attrs={"source_entity": "ARC", "swing_angle_deg": 90.0},
        ifc_properties={},
    )
    db.add(door)
    db.flush()

    room = Element(
        sheet_id=s.id, source_id=src.id, kind="room", name="Living",
        source_layer="A-ROOM",
        geometry={
            "kind": "polygon",
            "ring": [
                {"x": 0, "y": 0}, {"x": 10, "y": 0},
                {"x": 10, "y": 10}, {"x": 0, "y": 10},
            ],
        },
        attrs={"area": 100.0, "derived": True},
        ifc_properties={},
    )
    db.add(room)
    db.commit()

    return {
        "drawing_id": d.id, "sheet_id": s.id,
        "door_id": door.id, "wall_ids": wall_ids,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_non_empty_scene_with_stats(self, client, db: Session):
        seeded = _seed_square_room_sheet(db)
        r = client.get(
            f"/drawings/{seeded['drawing_id']}/sheets/{seeded['sheet_id']}/model3d"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["drawing_id"] == str(seeded["drawing_id"])
        assert body["sheet_id"] == str(seeded["sheet_id"])

        scene = body["scene"]
        stats = body["stats"]

        assert len(scene["walls"]) == 4
        assert len(scene["floors"]) == 1
        assert len(scene["openings"]) == 1
        assert scene["openings"][0]["kind"] == "door"

        # Stats match scene array lengths.
        assert stats["wall_count"] == 4
        assert stats["floor_count"] == 1
        assert stats["opening_count"] == 1
        assert stats["failed_opening_count"] == 0
        # Fresh Pydantic-model seed has width on neither attrs — default applies.
        assert stats["missing_door_width"] == 1
        # No insert bbox needed (ARC door came with bbox).
        assert stats["synthesized_insert_bbox"] == 0
        assert stats["dropped_elements"] == 0
        assert stats["generation_ms"] >= 0
        assert stats["vertex_count"] > 0
        assert stats["triangle_count"] > 0

    def test_response_headers_x_cache_miss_then_hit(self, client, db: Session):
        seeded = _seed_square_room_sheet(db)
        url = f"/drawings/{seeded['drawing_id']}/sheets/{seeded['sheet_id']}/model3d"
        r1 = client.get(url)
        assert r1.status_code == 200
        assert r1.headers["X-Cache"] == "MISS"
        assert r1.headers["ETag"].startswith('W/"')

        r2 = client.get(url)
        assert r2.status_code == 200
        assert r2.headers["X-Cache"] == "HIT"
        # ETag stable across requests.
        assert r2.headers["ETag"] == r1.headers["ETag"]
        # Bodies are byte-for-byte equal.
        assert r2.content == r1.content

    def test_etag_if_none_match_returns_304(self, client, db: Session):
        seeded = _seed_square_room_sheet(db)
        url = f"/drawings/{seeded['drawing_id']}/sheets/{seeded['sheet_id']}/model3d"
        r1 = client.get(url)
        etag = r1.headers["ETag"]

        r2 = client.get(url, headers={"If-None-Match": etag})
        assert r2.status_code == 304
        # 304 carries ETag but no body.
        assert r2.headers["ETag"] == etag
        assert r2.content == b""


class TestEmptyAndErrors:
    def test_empty_sheet_returns_empty_scene(self, client, db: Session):
        seeded = _seed_minimal_sheet(db)
        r = client.get(
            f"/drawings/{seeded['drawing_id']}/sheets/{seeded['sheet_id']}/model3d"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["scene"]["walls"] == []
        assert body["scene"]["floors"] == []
        assert body["scene"]["openings"] == []
        assert body["stats"]["wall_count"] == 0

    def test_sheet_unknown_returns_404(self, client, db: Session):
        seeded = _seed_minimal_sheet(db)
        r = client.get(
            f"/drawings/{seeded['drawing_id']}/sheets/{uuid4()}/model3d"
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"

    def test_sheet_belongs_to_other_drawing_returns_404(self, client, db: Session):
        a = _seed_minimal_sheet(db)
        b = _seed_minimal_sheet(db)
        # Cross-drawing lookup — the sheet exists but not on drawing a.
        r = client.get(
            f"/drawings/{a['drawing_id']}/sheets/{b['sheet_id']}/model3d"
        )
        assert r.status_code == 404

    def test_drawing_not_owned_returns_404(self, client, db: Session):
        # Drawing owned by a different user; the read-ownership resolver
        # 404s unknown drawings (M7 convention: don't leak existence).
        other = User(
            id=UUID("88888888-8888-8888-8888-888888888888"),
            email="other@atlas.test",
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "B" * 43,
        )
        db.add(other)
        db.flush()
        d = Drawing(
            source_filename="other.dxf",
            source_s3_key="drawings/other/source.dxf",
            size_bytes=1, content_hash="sha256:other",
            owner_id=other.id,
        )
        db.add(d)
        db.flush()
        s = Sheet(drawing_id=d.id, page_number=1)
        db.add(s)
        db.commit()

        r = client.get(f"/drawings/{d.id}/sheets/{s.id}/model3d")
        assert r.status_code == 404


class TestRealExtraction:
    """End-to-end against the apartment-grid fixture via the real extractor.

    Catches divergences between synthetic-test shape and real
    extraction output that unit-level translator tests would miss —
    specifically the INSERT-door bbox synthesis path and the
    default-width patching across many elements at once.
    """

    def test_apartment_grid_extraction_to_model3d(self, client, db: Session, tmp_path):
        from worker.jobs.extract import extract_from_dxf  # type: ignore

        build_apartment_grid_floor = _load_apartment_builder()
        # Write DXF to tmp, create Drawing+Sheet, run extractor.
        dxf = build_apartment_grid_floor(tmp_path / "apt.dxf")
        d = Drawing(
            source_filename="apt.dxf",
            source_s3_key="drawings/apt/source.dxf",
            size_bytes=dxf.stat().st_size,
            content_hash="sha256:model3d-apt-grid-test",
            owner_id=TEST_USER_ID, page_count=1, status="completed",
        )
        db.add(d)
        db.flush()
        s = Sheet(drawing_id=d.id, page_number=1)
        db.add(s)
        db.commit()

        extract_from_dxf(db, d.id, dxf, sheet_id=s.id)
        db.commit()

        r = client.get(f"/drawings/{d.id}/sheets/{s.id}/model3d")
        assert r.status_code == 200, r.text
        body = r.json()
        scene = body["scene"]
        stats = body["stats"]

        # 13 wall polylines → each becomes 1+ WallMesh segments.
        assert stats["wall_count"] >= 13
        # 3 doors, 2 windows — each placed as a void (with matching opening record).
        assert stats["opening_count"] >= 3
        # 6 derived rooms → 6 floor slabs.
        assert stats["floor_count"] >= 6
        # The INSERT door at (15, 6) and both INSERT windows have no
        # extractor bbox, so synthesis must fire ≥ 1 time (we check >=1
        # rather than ==3 so the test survives a future extractor fix).
        assert stats["synthesized_insert_bbox"] >= 1
        assert stats["dropped_elements"] == 0
        # Boolean cuts all succeeded.
        assert stats["failed_opening_count"] == 0

        # Mesh size sanity — real plans produce non-trivial geometry.
        assert stats["vertex_count"] > 50
        assert stats["triangle_count"] > 30

        # Spot-check the scene shape.
        assert len(scene["walls"]) >= 13
        # Each wall carries parent_wall_id linking back to the DB Wall.
        assert all("parent_wall_id" in w for w in scene["walls"])
