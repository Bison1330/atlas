"""Idempotency test for ``scripts/seed_demo_account.py``.

Runs the seed twice against the real dev Postgres and asserts the
second run is a no-op: same user row, same four drawings, same
element count. Guards against regressions that would let the seed
double-insert a drawing or recreate the user row with a fresh
password hash.

Redis events are monkeypatched out — the seed calls through to
``worker.jobs.extract``, which publishes progress events to Redis.
The test runs outside the compose network, so we no-op the publish
to keep the test hermetic (and fast).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from atlas_db import Drawing, Element, Sheet, User
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SEED_PATH = _REPO_ROOT / "scripts" / "seed_demo_account.py"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location(
        "seed_demo_account", _SEED_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register the module under its name before exec — dataclasses'
    # annotation resolver looks up ``sys.modules[cls.__module__]`` and
    # AttributeErrors on the frozen=True specs otherwise.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _delete_demo_rows(db: Session, email: str) -> None:
    db.execute(
        text("DELETE FROM drawings WHERE owner_id IN ("
             "SELECT id FROM users WHERE email = :e)"),
        {"e": email},
    )
    db.execute(
        text("DELETE FROM users WHERE email = :e"),
        {"e": email},
    )
    db.commit()


def _counts(db: Session, email: str) -> tuple[int, int, int]:
    user_count = db.execute(
        select(func.count(User.id)).where(User.email == email)
    ).scalar_one()
    drawing_count = db.execute(
        select(func.count(Drawing.id))
        .join(User, User.id == Drawing.owner_id)
        .where(User.email == email)
    ).scalar_one()
    element_count = db.execute(
        select(func.count(Element.id))
        .join(Sheet, Sheet.id == Element.sheet_id)
        .join(Drawing, Drawing.id == Sheet.drawing_id)
        .join(User, User.id == Drawing.owner_id)
        .where(User.email == email)
    ).scalar_one()
    return user_count, drawing_count, element_count


def test_seed_demo_idempotent(db: Session, monkeypatch) -> None:
    # No Redis in the test harness: the extractor publishes progress
    # events to ``worker.events.publish``; stub both entry points.
    monkeypatch.setattr(
        "worker.jobs.extract.events.publish", lambda *a, **kw: 1,
    )
    monkeypatch.setattr("worker.events.publish", lambda *a, **kw: 1)

    # Seed resolves its own engine via DATABASE_URL (already set by
    # conftest.py for this test suite).
    assert os.environ.get("DATABASE_URL"), "conftest should set DATABASE_URL"

    seed = _load_seed_module()

    # Start from a clean slate even if a prior seed run left rows behind,
    # so the first main() call actually exercises the insert path.
    _delete_demo_rows(db, seed.DEMO_EMAIL)

    try:
        # First run — should populate user + 4 drawings + extracted elements.
        assert seed.main() == 0
        users_1, drawings_1, elements_1 = _counts(db, seed.DEMO_EMAIL)
        assert users_1 == 1
        assert drawings_1 == 4
        assert elements_1 > 0  # extractor wrote at least some elements

        # Second run — idempotent, nothing new.
        assert seed.main() == 0
        users_2, drawings_2, elements_2 = _counts(db, seed.DEMO_EMAIL)
        assert users_2 == users_1 == 1
        assert drawings_2 == drawings_1 == 4
        assert elements_2 == elements_1

        # And each of the four seeded drawings is named as expected.
        names = {
            r[0]
            for r in db.execute(
                select(Drawing.source_filename)
                .join(User, User.id == Drawing.owner_id)
                .where(User.email == seed.DEMO_EMAIL)
            ).all()
        }
        assert names == {s.filename for s in seed.DEMO_DRAWINGS}
    finally:
        # The ``db`` fixture truncates drawings (cascading to sheets /
        # elements / sources) but leaves ``users`` alone — clean up the
        # demo user so the next test sees a fresh schema.
        db.rollback()
        _delete_demo_rows(db, seed.DEMO_EMAIL)
