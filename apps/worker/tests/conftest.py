"""Test config — env defaults for WorkerSettings + a Postgres ``db`` fixture.

The ``db`` fixture connects to the same dev Postgres the docker stack
uses (override via ``TEST_DATABASE_URL``). If unreachable, tests that
ask for it are *skipped* rather than failed — keeps pure-function
test runs in CI environments without Postgres painless. Each test
truncates ``drawings RESTART IDENTITY CASCADE`` after itself so M2
extraction tests are isolated.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://atlas:d85f54872734dfd0bba0c77f074dcaf0"
    "@localhost:5432/atlas",
)
os.environ.setdefault("S3_BUCKET", "atlas-test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9000")


def _engine_or_skip() -> Engine:
    url = os.environ.get(
        "TEST_DATABASE_URL", os.environ["DATABASE_URL"]
    )
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


@pytest.fixture(scope="session")
def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


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
