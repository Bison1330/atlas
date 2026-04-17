"""Integration tests for the M6 annotation endpoints.

Exercises POST/GET/PATCH/DELETE against the real DB so FK cascades
and cross-drawing invariants are verified end-to-end, not just at
the Python layer. The service is thin enough that route tests
double as service tests — no separate ``test_annotations_service.py``
until the service grows conditional logic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import Annotation, Drawing, Element, ElementSource, Sheet
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _seed_drawing_with_element(
    db, *, content_hash_suffix: str | None = None,
) -> dict:
    """Seed one drawing + sheet + source + one wall element.

    Returns the IDs so tests can hit endpoints without re-fetching.
    """
    suffix = content_hash_suffix or uuid4().hex[:8]
    d = Drawing(
        source_filename="x.dxf", source_s3_key="k", size_bytes=1,
        content_hash=f"sha256:ann-{suffix}",
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
    el = Element(
        sheet_id=s.id, source_id=src.id, kind="wall",
        ncs_layer="A-WALL-EXTR",
        ncs_major_group="WALL", ncs_minor_group="EXTR",
        confidence=0.92,
        geometry={"kind": "polyline", "points": [
            {"x": 0, "y": 0}, {"x": 10, "y": 0},
        ]},
    )
    db.add(el)
    db.commit()
    return {
        "drawing_id": d.id,
        "sheet_id": s.id,
        "source_id": src.id,
        "element_id": el.id,
    }


# ---------- POST happy path ----------


class TestCreateAnnotation:
    def test_post_valid_returns_201_with_full_payload(self, client, db):
        seeded = _seed_drawing_with_element(db)
        r = client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={
                "element_id": str(seeded["element_id"]),
                "author_name": "Kevin",
                "body": "Confirm with structural.",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()

        assert body["drawing_id"] == str(seeded["drawing_id"])
        assert body["element_id"] == str(seeded["element_id"])
        assert body["author_name"] == "Kevin"
        assert body["body"] == "Confirm with structural."
        assert "created_at" in body
        assert "updated_at" in body
        # M4 Phase 3 gating flag echoes through.
        assert body["element_extraction_meta"]["extraction_status"] \
            == "unvalidated_on_real_drawings"
        assert body["element_extraction_meta"]["confidence"] \
            == pytest.approx(0.92)
        assert body["element_extraction_meta"]["source_producer"] \
            == "dxf_ncs_extractor@0.1.0"

        # Row really landed in the DB.
        assert db.query(Annotation).filter(
            Annotation.drawing_id == seeded["drawing_id"]
        ).count() == 1


# ---------- POST error paths ----------


class TestCreateErrors:
    def test_missing_drawing_returns_404(self, client, db):
        seeded = _seed_drawing_with_element(db)
        r = client.post(
            f"/drawings/{uuid4()}/annotations",
            json={
                "element_id": str(seeded["element_id"]),
                "author_name": "A", "body": "b",
            },
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"

    def test_missing_element_returns_404(self, client, db):
        seeded = _seed_drawing_with_element(db)
        r = client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={
                "element_id": str(uuid4()),
                "author_name": "A", "body": "b",
            },
        )
        assert r.status_code == 404

    def test_cross_drawing_element_returns_400_element_mismatch(
        self, client, db,
    ):
        a = _seed_drawing_with_element(db, content_hash_suffix="a")
        b = _seed_drawing_with_element(db, content_hash_suffix="b")

        # Try to annotate drawing A using drawing B's element.
        r = client.post(
            f"/drawings/{a['drawing_id']}/annotations",
            json={
                "element_id": str(b["element_id"]),
                "author_name": "A", "body": "b",
            },
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "element_mismatch"

    def test_empty_body_rejected_by_validation(self, client, db):
        seeded = _seed_drawing_with_element(db)
        r = client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={
                "element_id": str(seeded["element_id"]),
                "author_name": "A", "body": "",
            },
        )
        assert r.status_code == 422

    def test_body_too_long_rejected(self, client, db):
        seeded = _seed_drawing_with_element(db)
        r = client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={
                "element_id": str(seeded["element_id"]),
                "author_name": "A", "body": "x" * 4001,
            },
        )
        assert r.status_code == 422

    def test_author_name_too_long_rejected(self, client, db):
        seeded = _seed_drawing_with_element(db)
        r = client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={
                "element_id": str(seeded["element_id"]),
                "author_name": "x" * 121, "body": "hi",
            },
        )
        assert r.status_code == 422


# ---------- GET list ----------


class TestListAnnotations:
    def test_list_for_drawing_newest_first(self, client, db):
        seeded = _seed_drawing_with_element(db)
        # Insert three annotations in sequence.
        for text in ("oldest", "middle", "newest"):
            r = client.post(
                f"/drawings/{seeded['drawing_id']}/annotations",
                json={
                    "element_id": str(seeded["element_id"]),
                    "author_name": "A", "body": text,
                },
            )
            assert r.status_code == 201

        r = client.get(f"/drawings/{seeded['drawing_id']}/annotations")
        assert r.status_code == 200
        bodies = [a["body"] for a in r.json()["annotations"]]
        # Newest first
        assert bodies == ["newest", "middle", "oldest"]

    def test_filter_by_element_id(self, client, db):
        seeded = _seed_drawing_with_element(db)

        # Add a second element on the same drawing + sheet.
        other_el = Element(
            sheet_id=seeded["sheet_id"], source_id=seeded["source_id"],
            kind="door", ncs_layer="A-DOOR",
            geometry={"kind": "arc", "center": {"x": 2, "y": 0}, "radius": 1,
                      "start_angle_deg": 0, "end_angle_deg": 90},
        )
        db.add(other_el)
        db.commit()

        client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={"element_id": str(seeded["element_id"]),
                  "author_name": "A", "body": "wall-note"},
        )
        client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={"element_id": str(other_el.id),
                  "author_name": "A", "body": "door-note"},
        )

        r = client.get(
            f"/drawings/{seeded['drawing_id']}/annotations",
            params={"element_id": str(seeded["element_id"])},
        )
        assert r.status_code == 200
        bodies = [a["body"] for a in r.json()["annotations"]]
        assert bodies == ["wall-note"]

    def test_element_convenience_route(self, client, db):
        seeded = _seed_drawing_with_element(db)
        client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={"element_id": str(seeded["element_id"]),
                  "author_name": "A", "body": "ping"},
        )
        r = client.get(f"/elements/{seeded['element_id']}/annotations")
        assert r.status_code == 200
        body = r.json()
        assert body["element_id"] == str(seeded["element_id"])
        assert len(body["annotations"]) == 1
        assert body["annotations"][0]["body"] == "ping"

    def test_no_cross_drawing_leakage(self, client, db):
        a = _seed_drawing_with_element(db, content_hash_suffix="a")
        b = _seed_drawing_with_element(db, content_hash_suffix="b")

        client.post(
            f"/drawings/{a['drawing_id']}/annotations",
            json={"element_id": str(a["element_id"]),
                  "author_name": "X", "body": "A-note"},
        )
        client.post(
            f"/drawings/{b['drawing_id']}/annotations",
            json={"element_id": str(b["element_id"]),
                  "author_name": "X", "body": "B-note"},
        )

        ra = client.get(f"/drawings/{a['drawing_id']}/annotations")
        rb = client.get(f"/drawings/{b['drawing_id']}/annotations")
        a_bodies = [x["body"] for x in ra.json()["annotations"]]
        b_bodies = [x["body"] for x in rb.json()["annotations"]]
        assert a_bodies == ["A-note"]
        assert b_bodies == ["B-note"]


# ---------- PATCH ----------


class TestPatchAnnotation:
    def test_patch_updates_body_and_updated_at(self, client, db):
        seeded = _seed_drawing_with_element(db)
        r = client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={"element_id": str(seeded["element_id"]),
                  "author_name": "A", "body": "original"},
        )
        created = r.json()
        ann_id = created["id"]
        original_created_at = created["created_at"]

        r = client.patch(
            f"/annotations/{ann_id}",
            json={"body": "edited"},
        )
        assert r.status_code == 200
        updated = r.json()
        assert updated["body"] == "edited"
        assert updated["created_at"] == original_created_at
        # updated_at may or may not bump on an identical row — but
        # at minimum it shouldn't regress behind created_at.
        assert updated["updated_at"] >= updated["created_at"]

    def test_patch_missing_returns_404(self, client):
        r = client.patch(
            f"/annotations/{uuid4()}",
            json={"body": "x"},
        )
        assert r.status_code == 404


# ---------- DELETE ----------


class TestDeleteAnnotation:
    def test_delete_returns_204_and_removes_row(self, client, db):
        seeded = _seed_drawing_with_element(db)
        r = client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={"element_id": str(seeded["element_id"]),
                  "author_name": "A", "body": "bye"},
        )
        ann_id = UUID(r.json()["id"])

        r = client.delete(f"/annotations/{ann_id}")
        assert r.status_code == 204

        assert db.get(Annotation, ann_id) is None

    def test_delete_missing_returns_404(self, client):
        r = client.delete(f"/annotations/{uuid4()}")
        assert r.status_code == 404


# ---------- FK cascade ----------


class TestFkCascade:
    def test_drawing_delete_cascades_to_annotations(self, client, db):
        seeded = _seed_drawing_with_element(db)
        client.post(
            f"/drawings/{seeded['drawing_id']}/annotations",
            json={"element_id": str(seeded["element_id"]),
                  "author_name": "A", "body": "x"},
        )

        # Delete the drawing directly via ORM — we don't expose an
        # HTTP delete for drawings yet, but the FK has to do its job
        # so a future DELETE /drawings/{id} doesn't leave orphans.
        drawing = db.get(Drawing, seeded["drawing_id"])
        db.delete(drawing)
        db.commit()

        assert db.query(Annotation).filter(
            Annotation.drawing_id == seeded["drawing_id"]
        ).count() == 0
