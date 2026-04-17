"""WebSocket endpoint tests.

The subscribe path talks to real Redis, so the event-forwarding test is
gated on Redis being reachable at the configured URL. The snapshot and
"not found" tests work purely against the DB and the TestClient.
"""

from __future__ import annotations

import os
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import Drawing
from app.main import app
from tests.conftest import TEST_USER_ID


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _insert(db, **overrides) -> Drawing:
    defaults = dict(
        source_filename="plans.pdf",
        source_s3_key="drawings/xyz/source.pdf",
        size_bytes=1024,
        content_hash="sha256:abc",
        owner_id=TEST_USER_ID,
    )
    defaults.update(overrides)
    d = Drawing(**defaults)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def test_ws_sends_snapshot_on_connect(db, client):
    d = _insert(db, status="rasterizing", progress_percent=25, progress_message="rendering")
    with client.websocket_connect(f"/ws/drawings/{d.id}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        ev = msg["event"]
        assert ev["status"] == "rasterizing"
        assert ev["progress_percent"] == 25
        assert ev["message"] == "rendering"


def test_ws_closes_with_4004_when_not_found(client):
    from starlette.websockets import WebSocketDisconnect

    fake_id = uuid4()
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"/ws/drawings/{fake_id}") as ws:
            ws.receive_text()

    assert excinfo.value.code == 4004


def _redis_reachable() -> bool:
    try:
        import redis

        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        redis.Redis.from_url(url, socket_timeout=1.0).ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _redis_reachable(), reason="Redis not reachable")
def test_ws_forwards_published_events(db, client, monkeypatch):
    from app.core import config, events

    # Point both publish() and subscribe() at the locally-reachable Redis.
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("REDIS_URL", url)
    config.get_settings.cache_clear()

    d = _insert(db, status="queued", progress_percent=0)

    with client.websocket_connect(f"/ws/drawings/{d.id}") as ws:
        # Drain the initial snapshot.
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"

        # Give the subscriber a beat to attach before we publish.
        time.sleep(0.5)

        payload = {
            "drawing_id": str(d.id),
            "status": "rasterizing",
            "progress_percent": 10,
            "message": "starting page 1",
            "at": "2026-04-16T00:00:00+00:00",
        }
        delivered = events.publish(d.id, payload)
        assert delivered >= 1

        msg = ws.receive_json(mode="text")
        assert msg["type"] == "event"
        assert msg["event"]["status"] == "rasterizing"
        assert msg["event"]["progress_percent"] == 10
