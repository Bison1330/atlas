"""Preflight safeguards for the pytest harness.

Shared between ``apps/api/tests/conftest.py`` and
``apps/worker/tests/conftest.py``. Each conftest imports :func:`preflight`
and :func:`print_banner` and invokes them from ``pytest_configure``.

Why this module exists: an earlier test run with the default
``TEST_DATABASE_URL`` silently pointing at the *live* database
``TRUNCATE``-d every row in ``drawings`` + ``users``. Never again. The
goal of these checks is to make that specific mistake impossible,
even if a new developer doesn't notice the env var, even if someone
copies the prod URL by accident, even if the DB is named identically.

Layered checks, any failure aborts::

    1. TEST_DATABASE_URL must be set (no default).
    2. ENVIRONMENT != "production".
    3. TEST_DATABASE_URL and DATABASE_URL must not resolve to the
       same physical database (host/port/name canonicalized).
    4. TEST_DATABASE_URL's database name must contain "test".
    5. The target DB must carry the sentinel row — inserted only
       by ``scripts/init_test_db.py``, never truncated by tests.

Rationale for the sentinel row: every other check is about what's in
the environment. The sentinel is about what's in the database itself.
Even if a malicious actor (or careless operator) names a prod DB
``atlas_test`` and sets ``TEST_DATABASE_URL`` to point at it, they
still have to *also* insert a row that no real user would. One more
hoop to clear before tests can truncate.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

SENTINEL_EMAIL = "test-harness-sentinel@atlas.test"


def _canonical_db(url_str: str) -> tuple[str, str, int, str]:
    """Reduce a DB URL to (drivername, host, port, database) for equality.

    Normalizes ``postgres://`` vs ``postgresql+psycopg://``, casing on
    the host, and a trailing slash on the path. We deliberately do
    *not* compare credentials — two URLs that differ only in username
    still point at the same DB, and that's the match we care about.
    """
    u = make_url(url_str)
    drivername = (u.drivername or "").split("+", 1)[0].lower()
    # Normalize the two common PostgreSQL scheme aliases together.
    if drivername in {"postgres", "postgresql"}:
        drivername = "postgresql"
    host = (u.host or "").lower()
    port = u.port or (5432 if drivername == "postgresql" else 0)
    database = (u.database or "").rstrip("/").lower()
    return (drivername, host, port, database)


def _fail(message: str) -> None:
    """Abort the pytest session with a clean, banner-less usage error."""
    import pytest
    raise pytest.UsageError("\n" + message)


def preflight() -> dict[str, Any]:
    """Run every safeguard in order; return state for the banner.

    Raises :class:`pytest.UsageError` on any failure. Returning a dict
    keeps the banner printer separate from the checks — tests can
    call :func:`preflight` in isolation to verify a refusal path.
    """
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        _fail(
            "pytest session start failed: TEST_DATABASE_URL is not set.\n"
            "Tests must never run against the live database. Set TEST_DATABASE_URL\n"
            "to a dedicated test database (e.g. postgres://.../atlas_test) and\n"
            "re-run."
        )

    environment = os.environ.get("ENVIRONMENT", "development").strip().lower()
    if environment == "production":
        _fail(
            "pytest session start failed: ENVIRONMENT=production.\n"
            "Tests running in a production environment is never correct."
        )

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        if _canonical_db(test_url) == _canonical_db(db_url):
            _fail(
                "TEST_DATABASE_URL and DATABASE_URL resolve to the same database.\n"
                "Tests would truncate live data. Refusing to run."
            )

    db_name = make_url(test_url).database or ""
    if "test" not in db_name.lower():
        _fail(
            f"Refusing to run tests against database {db_name!r}: name does not contain\n"
            "'test'. Create a dedicated test database (e.g. atlas_test) and point\n"
            "TEST_DATABASE_URL at it."
        )

    # Sentinel check — requires a live connection + the users table.
    try:
        engine = create_engine(test_url, pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id FROM users "
                    "WHERE email = :e AND is_demo = false"
                ),
                {"e": SENTINEL_EMAIL},
            ).scalar_one_or_none()
    except Exception as exc:
        _fail(
            "pytest session start failed: could not reach TEST_DATABASE_URL to "
            "verify the sentinel row.\n"
            f"  url:   {test_url}\n"
            f"  error: {exc}\n"
            "Run `python scripts/init_test_db.py` against the target database "
            "first."
        )

    if row is None:
        _fail(
            "Test database is missing the sentinel row\n"
            f"({SENTINEL_EMAIL}). This looks like a non-test database.\n"
            "To initialize a legitimate test database, run:\n"
            "    python scripts/init_test_db.py\n"
            "which creates the sentinel row and any other required harness state."
        )

    return {
        "test_url": test_url,
        "environment": environment,
        "sentinel_present": True,
        "checks": [
            ("db-not-live", True),
            ("db-named-test", True),
            ("env-not-prod", True),
            ("sentinel-present", True),
        ],
    }


def _redact(url_str: str) -> str:
    """Render a DB URL with the password masked — safe for logs."""
    u = make_url(url_str)
    if u.password:
        u = u.set(password="***")
    return str(u)


def print_banner(state: dict[str, Any]) -> None:
    """Write the target-DB banner to stderr so every run makes the target obvious."""
    import sys

    bar = "━" * 60
    checks_line = "  ".join(f"{name} ✓" for name, _ in state["checks"])
    lines = [
        "",
        bar,
        "atlas test harness",
        f"  TEST_DATABASE_URL: {_redact(state['test_url'])}",
        f"  sentinel row:      present",
        f"  checks:            {checks_line}",
        bar,
        "",
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    sys.stderr.flush()
