"""Shared fixtures for API tests.

- ``engine`` is a session-scoped real Postgres connection. If unreachable,
  every DB-dependent test is skipped (not failed).
- ``_app_db_override`` is autouse so FastAPI's ``get_db`` dep and the
  WebSocket endpoint's direct session factory both point at the test
  engine. Route tests that don't insert their own rows still get DB
  access via this override.
- ``db`` yields a session for the test to insert/read rows directly
  and truncates after each test for isolation.

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
from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import db as core_db
from app.core.auth_dep import current_user, require_csrf
from app.core.db import get_db
from app.core import redis as redis_mod  # noqa: F401  (side-effect: force module load before tests)
from app.db import Base, User
from app.main import app
from app.routes import websocket as ws_module

# Force Redis client to use the refreshed URL.
redis_mod._client = None  # type: ignore[attr-defined]

DEFAULT_TEST_DB = (
    "postgresql+psycopg://atlas:d85f54872734dfd0bba0c77f074dcaf0"
    "@localhost:5432/atlas"
)

# When tests run on the host (outside the docker-compose network),
# the service aliases ("redis", "postgres", "minio") don't resolve.
# Default to localhost bindings so the M7 auth tests — which actually
# hit Redis for sessions + rate limits — can function.
# Setdefault over overwrite so env-var overrides from the shell still win.
os.environ["REDIS_URL"] = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
if "redis:6379" in os.environ["REDIS_URL"]:  # compose-internal hostname
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ.setdefault("DATABASE_URL", DEFAULT_TEST_DB)

# Ensure settings re-read the env we just set; the @lru_cache on
# get_settings means a stale instance would hold the wrong URLs.
from app.core.config import get_settings  # noqa: E402
get_settings.cache_clear()

# Fixed UUIDs the test stack uses. Keeping them constant means
# seed helpers can set ``owner_id=TEST_USER_ID`` without plumbing
# a fixture through, and the _auto_auth override can hand back
# a user with this id without a DB round-trip on every test.
TEST_USER_ID = UUID("99999999-9999-9999-9999-999999999999")
TEST_USER_EMAIL = "test@atlas.test"


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
        # CASCADE handles sheets / elements / annotations / element_sources.
        # Users live on a separate cleanup because drawings.owner_id is a
        # RESTRICT FK to users — truncating drawings first lets us truncate
        # users without tripping the constraint.
        session.execute(
            text("TRUNCATE drawings, users RESTART IDENTITY CASCADE")
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
