#!/usr/bin/env python3
"""One-shot initializer for a pytest test database.

Creates the Atlas schema via SQLAlchemy ``create_all`` and inserts the
test-harness sentinel row. The sentinel is the load-bearing marker
``tests/harness_safety.py`` uses to distinguish "this is a dedicated
test database" from "this is your live database". Without it, pytest
refuses to start.

This script is the **only approved path** to making a database pytest-
ready. There is no ``--skip-sentinel`` flag, no env override — that's
deliberate. The mechanism has to be annoying enough that no one routes
around it by accident.

Idempotent. Re-running against an already-initialized test DB is a
no-op.

Usage::

    TEST_DATABASE_URL=postgresql+psycopg://atlas:pw@localhost:5432/atlas_test \\
      python scripts/init_test_db.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
# atlas_db is the schema; `tests/` is where the sentinel email constant lives.
sys.path.insert(0, str(_REPO_ROOT / "packages" / "atlas-db"))
sys.path.insert(0, str(_REPO_ROOT / "tests"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.engine.url import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from atlas_db import Base, User  # noqa: E402
from harness_safety import SENTINEL_EMAIL  # noqa: E402


def main() -> int:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        print("TEST_DATABASE_URL is not set.", file=sys.stderr)
        return 1

    db_name = (make_url(url).database or "").lower()
    if "test" not in db_name:
        print(
            f"Refusing to initialize {db_name!r}: name does not contain 'test'.\n"
            "Create a dedicated test database (e.g. atlas_test) first.",
            file=sys.stderr,
        )
        return 1

    engine = create_engine(url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        existing = session.execute(
            select(User).where(User.email == SENTINEL_EMAIL)
        ).scalar_one_or_none()
        if existing is not None:
            print(f"ok: sentinel already present ({SENTINEL_EMAIL})")
            return 0

        # Password hash is a fixed non-argon2 string only long enough
        # to satisfy the CHECK constraint. It's not used for auth;
        # the sentinel row is never meant to log in. is_active=False
        # and is_demo=False keep it invisible to both real users and
        # the demo-login path.
        sentinel = User(
            email=SENTINEL_EMAIL,
            password_hash="sentinel:do-not-use-for-auth-0000000000000",
            display_name="test harness sentinel",
            is_active=False,
            is_demo=False,
            email_verified=False,
        )
        session.add(sentinel)
        session.commit()
        print(f"ok: inserted sentinel row ({SENTINEL_EMAIL})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
