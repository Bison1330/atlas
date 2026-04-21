"""Shared fixtures for API tests.

- ``engine`` is a session-scoped real Postgres connection targeting
  ``TEST_DATABASE_URL`` (required; there is no fallback to the live
  ``DATABASE_URL``). The test session refuses to start if the env is
  misconfigured — see :mod:`harness_safety`.
- ``_app_db_override`` is autouse so FastAPI's ``get_db`` dep and the
  WebSocket endpoint's direct session factory both point at the test
  engine. Route tests that don't insert their own rows still get DB
  access via this override.
- ``db`` yields a session for the test to insert/read rows directly
  and clears non-sentinel state after each test for isolation.

**Safety invariant:** the test-harness sentinel row in ``users``
(email ``test-harness-sentinel@atlas.test``, inserted by
``scripts/init_test_db.py``) must never be truncated. The ``db``
fixture's teardown deletes every user *except* the sentinel.

**M7 note:** ``_auto_auth`` autouses the ``current_user`` FastAPI
dependency with a fixed test user (:data:`TEST_USER_ID`). This
keeps the pre-M7 134 tests working without each one having to
log in explicitly. Seed helpers that build ``Drawing`` rows
should pass ``owner_id=TEST_USER_ID`` so the write-path
endpoints (which require owned drawings, not unclaimed) work.
Tests that want to exercise the real auth path (register / login
/ CSRF / session cookies) use the ``anon_client`` fixture and
bypass the override.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "tests"))
from harness_safety import SENTINEL_EMAIL, preflight, print_banner  # noqa: E402

# Run preflight at conftest IMPORT time — before any ``app.*`` module
# loads and potentially reads DATABASE_URL, opens a Redis client, or
# connects to Postgres. pytest_configure is too late; by then the
# module-level imports below have already fired.
_PREFLIGHT_STATE = preflight()
os.environ["DATABASE_URL"] = _PREFLIGHT_STATE["test_url"]
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
if "redis:6379" in os.environ.get("REDIS_URL", ""):  # compose-internal hostname
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ.setdefault("ENVIRONMENT", "development")


def pytest_configure(config: pytest.Config) -> None:
    """Emit the banner once pytest has taken control of stderr."""
    print_banner(_PREFLIGHT_STATE)


# ---------------------------------------------------------------------------
# App-layer imports — safe now that DATABASE_URL points at the test DB.
# ---------------------------------------------------------------------------

from app.core import db as core_db  # noqa: E402
from app.core.auth_dep import current_user, require_csrf  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core import redis as redis_mod  # noqa: E402,F401  (force module load)
from app.db import Base, User  # noqa: E402
from app.main import app  # noqa: E402
from app.routes import websocket as ws_module  # noqa: E402

# Force the Redis client to rebuild against the (now sane) URL.
redis_mod._client = None  # type: ignore[attr-defined]

# Re-read settings so the @lru_cache on get_settings doesn't hand back
# an instance captured before pytest_configure rewrote DATABASE_URL.
from app.core.config import get_settings  # noqa: E402
get_settings.cache_clear()

# Fixed UUIDs the test stack uses. Keeping them constant means
# seed helpers can set ``owner_id=TEST_USER_ID`` without plumbing
# a fixture through, and the _auto_auth override can hand back
# a user with this id without a DB round-trip on every test.
TEST_USER_ID = UUID("99999999-9999-9999-9999-999999999999")
TEST_USER_EMAIL = "test@atlas.test"


@pytest.fixture(scope="session")
def engine() -> Engine:
    url = os.environ["TEST_DATABASE_URL"]
    return create_engine(url, pool_pre_ping=True)


@pytest.fixture(scope="session", autouse=True)
def _schema(engine: Engine) -> Iterator[None]:
    # create_all is idempotent with init_test_db.py's schema; keep it
    # here so adding a new model between inits doesn't fail mysteriously.
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(scope="session")
def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _app_db_override(
    _session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
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
        # Clear per-test state while preserving the harness sentinel.
        # Ordering: drawings + projects first (users.drawings.owner_id
        # and projects.created_by are RESTRICT FKs to users — deleting
        # users before these would fail). TRUNCATE ... CASCADE on
        # drawings + projects sweeps sheets, elements, element_sources,
        # tiles, annotations, project_members along for free. Users
        # then get a DELETE-except-sentinel so the sentinel survives.
        session.execute(
            text(
                "TRUNCATE drawings, projects RESTART IDENTITY CASCADE"
            )
        )
        session.execute(
            text("DELETE FROM users WHERE email <> :sentinel"),
            {"sentinel": SENTINEL_EMAIL},
        )
        session.commit()
        session.close()


# ---------------------------------------------------------------------------
# M7 auth test harness
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_user(db: Session) -> User:
    """Row in ``users`` matching :data:`TEST_USER_ID`.

    Seeded fresh per test (the ``db`` fixture truncates between
    tests). Tests that need the real user row can read its fields
    via this fixture; tests that just want seeded drawings to have
    an owner can pass ``owner_id=TEST_USER_ID`` directly.
    """
    user = User(
        id=TEST_USER_ID,
        email=TEST_USER_EMAIL,
        # Placeholder argon2id hash matching the CHECK length bounds.
        # Not used by tests — the _auto_auth fixture skips the verify
        # path entirely by overriding current_user.
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "B" * 43,
        display_name="Test User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(autouse=True)
def _redis_clean() -> Iterator[None]:
    """Flush Redis between tests so rate-limit counters + sessions
    from a prior test don't cross-contaminate.

    Scoped per test — the cost is negligible against a local dev
    Redis, and isolation beats speed in test land.
    """
    redis_mod._client = None  # type: ignore[attr-defined]
    try:
        redis_mod.get_redis().flushdb()
    except Exception:
        # If Redis isn't reachable, tests that need it will fail
        # loudly on their own. Don't gate the whole suite.
        pass
    yield


@pytest.fixture(autouse=True)
def _auto_auth(test_user: User) -> Iterator[None]:
    """Automatically authenticate every request as :data:`test_user`.

    Lets pre-M7 tests keep working without adding login boilerplate.
    Tests that want to verify the real auth path (registering,
    logging in, CSRF enforcement) should use the ``anon_client``
    fixture, which restores the default ``current_user`` behaviour.
    """
    app.dependency_overrides[current_user] = lambda: test_user
    app.dependency_overrides[require_csrf] = lambda: None
    yield
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(require_csrf, None)


@pytest.fixture()
def anon_client() -> Iterator:
    """TestClient with *no* auth override.

    Hits the real ``current_user`` dependency, so requests to
    protected endpoints return 401 unless the test explicitly
    registers / logs in / sends cookies. Used by the M7 auth test
    module; other tests should use the regular ``client`` fixture.
    """
    from fastapi.testclient import TestClient

    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(require_csrf, None)
    with TestClient(app) as c:
        yield c
