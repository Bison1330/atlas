"""Shared fixtures for API tests.

- ``engine`` is a session-scoped real Postgres connection. If unreachable,
  every DB-dependent test is skipped (not failed).
- ``_app_db_override`` is autouse so FastAPI's ``get_db`` dep and the
  WebSocket endpoint's direct session factory both point at the test
  engine. Route tests that don't insert their own rows still get DB
  access via this override.
- ``db`` yields a session for the test to insert/read rows directly
  and truncates after each test for isolation.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import db as core_db
from app.core.db import get_db
from app.db import Base
from app.main import app
from app.routes import websocket as ws_module

DEFAULT_TEST_DB = (
    "postgresql+psycopg://atlas:d85f54872734dfd0bba0c77f074dcaf0"
    "@localhost:5432/atlas"
)


def _engine_or_skip() -> Engine:
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception as exc:
        pytest.skip(f"Postgres not reachable at {url}: {exc}")


@pytest.fixture(scope="session")
def engine() -> Engine:
    return _engine_or_skip()


@pytest.fixture(scope="session", autouse=True)
def _schema(engine: Engine) -> Iterator[None]:
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(scope="session")
def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _app_db_override(
    _session_factory: sessionmaker[Session], monkeypatch
) -> Iterator[None]:
    """Wire the app's DB plumbing to the test engine for every test."""

    def _get_db_override() -> Iterator[Session]:
        s = _session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db_override
    monkeypatch.setattr(core_db, "get_session_factory", lambda: _session_factory)
    monkeypatch.setattr(ws_module, "get_session_factory", lambda: _session_factory)

    yield

    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def db(_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = _session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(text("TRUNCATE drawings RESTART IDENTITY CASCADE"))
        session.commit()
        session.close()
