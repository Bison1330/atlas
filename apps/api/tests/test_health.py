"""Smoke tests for the /health endpoints.

`/health/ready` is exercised with monkeypatched pings — the test
doesn't need a real Postgres or Redis.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_liveness_returns_ok():
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "environment" in body


def test_readiness_ok_when_deps_ok(monkeypatch):
    from app.core import db, redis

    monkeypatch.setattr(db, "ping", lambda: True)
    monkeypatch.setattr(redis, "ping", lambda: True)

    with TestClient(app) as client:
        r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["postgres"]["ok"] is True
    assert body["checks"]["redis"]["ok"] is True


def test_readiness_503_when_dep_fails(monkeypatch):
    from app.core import db, redis

    def boom() -> bool:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(db, "ping", boom)
    monkeypatch.setattr(redis, "ping", lambda: True)

    with TestClient(app) as client:
        r = client.get("/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unready"
    assert body["checks"]["postgres"]["ok"] is False
    assert "connection refused" in body["checks"]["postgres"]["error"]


def test_request_id_header_echoed():
    with TestClient(app) as client:
        r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID") == "abc-123"
