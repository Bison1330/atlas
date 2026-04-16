"""Shared fixtures for API tests.

The DB fixtures require a live Postgres. When one isn't reachable at
``TEST_DATABASE_URL`` (default: the local dev compose URL on
``localhost:5432``), every DB-dependent test is skipped instead of
failing — so ``pytest`` still works in a barebones CI shard that only
wants to run the smoke tests.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base

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
    # Idempotent — the schema is managed by Alembic. We just make sure
    # the tables exist (create_all is a no-op if Alembic already ran) and
    # truncate between tests.
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def db(engine: Engine) -> Iterator[Session]:
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        # Clean up any rows this test inserted so the table is isolated.
        session.execute(text("TRUNCATE drawings RESTART IDENTITY CASCADE"))
        session.commit()
        session.close()
