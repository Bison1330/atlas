"""Test config — preflight + a Postgres ``db`` fixture.

Connects only to ``TEST_DATABASE_URL``; there is no fallback to the
live database. ``tests/harness_safety.py`` runs a layered preflight in
``pytest_configure`` that refuses the session if the target DB can't
be proven safe — see that module for the invariants.

Each test truncates ``drawings RESTART IDENTITY CASCADE`` at teardown
so M2 extraction tests are isolated. The worker suite does *not*
touch ``users`` (unlike the api suite, which also clears users
between tests while preserving the harness sentinel).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "tests"))
from harness_safety import preflight, print_banner  # noqa: E402

# Run preflight at conftest IMPORT time — worker settings are loaded
# from env at import time by the modules that tests exercise, so the
# safety check has to land first.
_PREFLIGHT_STATE = preflight()
os.environ["DATABASE_URL"] = _PREFLIGHT_STATE["test_url"]
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET", "atlas-test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("ENVIRONMENT", "development")


def pytest_configure(config: pytest.Config) -> None:
    print_banner(_PREFLIGHT_STATE)


@pytest.fixture(scope="session")
def engine() -> Engine:
    url = os.environ["TEST_DATABASE_URL"]
    return create_engine(url, pool_pre_ping=True)


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
