"""Tests for POST /drawings/{id}/ask.

Wires the real route + real DB to a ``FakeInterpreter`` via the
``_get_interpreter`` dependency override, so these tests prove the
SQL-fetch + service-glue + response-shape *without* touching
Anthropic. The service-layer tests
(``test_qa_service.py``) cover the bucket executors themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import Drawing, Element, ElementSource, Sheet
from app.main import app
from app.routes.qa import _get_interpreter
from app.services.qa import QueryInterpretation
from app.services.qa_interpreter import FakeInterpreter


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def with_interpreter():
    """Install a FakeInterpreter via dependency override.

    Usage::

        def test_x(with_interpreter, client):
            with_interpreter({"how many walls?": QueryInterpretation(...)})
            r = client.post(...)
    """
    def _apply(mapping: dict[str, QueryInterpretation]):
        app.dependency_overrides[_get_interpreter] = lambda: FakeInterpreter(mapping)
    yield _apply
    app.dependency_overrides.pop(_get_interpreter, None)


def _seed_one_room_floor(db) -> dict:
    """Seed the minimal "4 walls + 1 door + 1 explicit room" drawing."""
    d = Drawing(
        source_filename="x.dxf", source_s3_key="k", size_bytes=1,
        content_hash=f"sha256:qa-{uuid4().hex[:8]}",
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
    # 4 perimeter walls
    for i, (a, b) in enumerate([
        ((0, 0), (10, 0)),
        ((10, 0), (10, 8)),
        ((10, 8), (0, 8)),
        ((0, 8), (0, 0)),
    ]):
        db.add(Element(
            sheet_id=s.id, source_id=src.id, kind="wall",
            ncs_layer="A-WALL-EXTR",
            ncs_major_group="WALL", ncs_minor_group="EXTR",
            confidence=0.9 + i * 0.01,
            geometry={
                "kind": "polyline",
                "points": [
                    {"x": a[0], "y": a[1]}, {"x": b[0], "y": b[1]},
                ],
            },
            bbox={"minx": min(a[0], b[0]), "miny": min(a[1], b[1]),
                  "maxx": max(a[0], b[0]), "maxy": max(a[1], b[1])},
        ))
    # 1 room
    db.add(Element(
        sheet_id=s.id, source_id=src.id, kind="room",
        ncs_major_group="ROOM",
        confidence=0.88,
        geometry={
            "kind": "polygon",
            "ring": [
                {"x": 0, "y": 0}, {"x": 10, "y": 0},
                {"x": 10, "y": 8}, {"x": 0, "y": 8},
            ],
        },
        bbox={"minx": 0, "miny": 0, "maxx": 10, "maxy": 8},
        attrs={"area": 80.0},
    ))
    # 1 door
    db.add(Element(
        sheet_id=s.id, source_id=src.id, kind="door",
        ncs_layer="A-DOOR", ncs_major_group="DOOR",
        confidence=0.85,
        geometry={
            "kind": "arc", "center": {"x": 2.5, "y": 0}, "radius": 1,
            "start_angle_deg": 0, "end_angle_deg": 90,
        },
        bbox={"minx": 1.5, "miny": -1, "maxx": 3.5, "maxy": 1},
    ))
    db.commit()
    return {"drawing_id": d.id, "source_id": src.id, "sheet_id": s.id}


# ---------- happy paths ----------


class TestAskEndpoint:
    def test_count_end_to_end(self, client, db, with_interpreter):
        seeded = _seed_one_room_floor(db)
        with_interpreter({
            "how many walls?": QueryInterpretation(
                bucket="count", filter={"kind": "wall"},
            ),
        })

        r = client.post(
            f"/drawings/{seeded['drawing_id']}/ask",
            json={"question": "how many walls?"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["answer_type"] == "count"
        assert body["query_interpretation"]["bucket"] == "count"
        assert body["query_interpretation"]["filter"] == {"kind": "wall"}
        assert len(body["citations"]) == 4
        assert all(c["kind"] == "wall" for c in body["citations"])
        assert "4" in body["answer"]
        assert body["meta"]["source_id"] == str(seeded["source_id"])
        assert body["meta"]["extraction_status"] == "unvalidated_on_real_drawings"
        assert body["confidence"]["extraction_min"] == pytest.approx(0.9)

    def test_quantity_wall_length(self, client, db, with_interpreter):
        seeded = _seed_one_room_floor(db)
        with_interpreter({
            "total wall length?": QueryInterpretation(
                bucket="quantity",
                filter={"kind": "wall", "metric": "length"},
            ),
        })

        r = client.post(
            f"/drawings/{seeded['drawing_id']}/ask",
            json={"question": "total wall length?"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["answer_type"] == "quantity"
        assert "36" in body["answer"]  # 10+8+10+8 perimeter

    def test_lookup_room_area(self, client, db, with_interpreter):
        seeded = _seed_one_room_floor(db)
        with_interpreter({
            "area of room 1": QueryInterpretation(
                bucket="lookup",
                filter={"kind": "room", "identifier": "room 1",
                        "attribute": "area"},
            ),
        })

        r = client.post(
            f"/drawings/{seeded['drawing_id']}/ask",
            json={"question": "area of room 1"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["answer_type"] == "lookup"
        assert len(body["citations"]) == 1
        assert body["citations"][0]["kind"] == "room"
        assert "80" in body["answer"]


# ---------- error paths ----------


class TestAskErrors:
    def test_unknown_drawing_returns_404(self, client, with_interpreter):
        with_interpreter({})
        r = client.post(
            f"/drawings/{uuid4()}/ask",
            json={"question": "anything?"},
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"

    def test_empty_question_rejected_by_validation(
        self, client, db, with_interpreter
    ):
        seeded = _seed_one_room_floor(db)
        with_interpreter({})
        r = client.post(
            f"/drawings/{seeded['drawing_id']}/ask",
            json={"question": ""},
        )
        assert r.status_code == 422  # Pydantic min_length=1

    def test_missing_api_key_returns_503(self, client, db, monkeypatch):
        # No dependency override → real _get_interpreter runs, hits
        # the settings check, and returns 503 when key is absent.
        seeded = _seed_one_room_floor(db)
        from app.core import config

        config.get_settings.cache_clear()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        # Ensure any prior override is gone.
        app.dependency_overrides.pop(_get_interpreter, None)

        r = client.post(
            f"/drawings/{seeded['drawing_id']}/ask",
            json={"question": "how many walls?"},
        )
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "llm_unavailable"

        config.get_settings.cache_clear()

    def test_unsupported_question_is_200_with_unsupported_body(
        self, client, db, with_interpreter
    ):
        # "Unsupported" is still a valid answer shape — the service
        # tells the user honestly rather than 400'ing.
        seeded = _seed_one_room_floor(db)
        with_interpreter({
            "is this up to code?": QueryInterpretation(
                bucket="unsupported",
                unsupported_reason="code compliance is out of scope",
                suggested_phrasing="how many exterior doors?",
            ),
        })

        r = client.post(
            f"/drawings/{seeded['drawing_id']}/ask",
            json={"question": "is this up to code?"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["answer_type"] == "unsupported"
        assert body["citations"] == []
        assert "code compliance" in body["answer"]
        assert body["query_interpretation"]["suggested_phrasing"] \
            == "how many exterior doors?"


# ---------- no-extraction-yet ----------


class TestAskWithoutExtraction:
    def test_drawing_without_source_returns_empty_citations(
        self, client, db, with_interpreter
    ):
        # Drawing exists but no ElementSource — route still 200s
        # with 0 citations + honest "0" answer.
        d = Drawing(
            source_filename="x.dxf", source_s3_key="k", size_bytes=1,
            content_hash=f"sha256:no-src-{uuid4().hex[:8]}",
        )
        db.add(d)
        db.commit()

        with_interpreter({
            "how many walls?": QueryInterpretation(
                bucket="count", filter={"kind": "wall"},
            ),
        })
        r = client.post(
            f"/drawings/{d.id}/ask",
            json={"question": "how many walls?"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["citations"] == []
        assert body["meta"]["source_id"] is None
        assert "0" in body["answer"]
