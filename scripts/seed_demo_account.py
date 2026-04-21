#!/usr/bin/env python3
"""Seed the shared demo account and a fixed set of sample drawings.

Idempotent: safe to run repeatedly. Re-runs will not duplicate the
user or any seeded drawing — each drawing is keyed on
``(owner_id, source_filename)`` and skipped if it already exists.

Usage::

    # Run inside the worker container, where DATABASE_URL + the
    # worker extractor are already available:
    docker compose exec -T worker python /opt/atlas/scripts/seed_demo_account.py

    # Or directly on the host, with DATABASE_URL pointing at the
    # running Postgres (the host's .env uses 'postgres' hostname;
    # swap it to 'localhost' if running outside compose):
    DATABASE_URL=postgresql+psycopg://atlas:...@localhost:5432/atlas \\
      /opt/atlas/.venv-eval/bin/python scripts/seed_demo_account.py

The script prints a one-line summary per drawing and a final
report so CI / ops can eyeball the result.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parent.parent
# Order matters: both apps/api and apps/worker expose a top-level
# ``tests`` package, so whichever goes on sys.path last wins. We
# want ``tests.fixtures.dxf_builders`` (worker), so insert it last.
sys.path.insert(0, str(_REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(_REPO_ROOT / "apps" / "worker"))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from atlas_db import Drawing, Element, Sheet, User  # noqa: E402
from tests.fixtures.dxf_builders import (  # noqa: E402
    APARTMENT_ROOM_LABELS,
    BUNGALOW_ROOM_LABELS,
    OFFICE_ROOM_LABELS,
    RETAIL_ROOM_LABELS,
    build_apartment_floor,
    build_bungalow_floor,
    build_office_floor,
    build_retail_floor,
)
from worker.jobs.extract import extract_from_dxf  # noqa: E402

DEMO_EMAIL = "demo@atlas.build"
DEMO_PASSWORD = "AtlasDemo!2026"
DEMO_DISPLAY_NAME = "Atlas Demo"


@dataclass(frozen=True)
class DemoDrawingSpec:
    filename: str
    title: str
    builder: callable  # type: ignore[type-arg]
    # Per-room (name, centroid_x, centroid_y) from the builder. After
    # extraction, each derived ``room`` element is matched to the
    # closest entry by centroid and has ``Element.name`` populated.
    # Without this, the 3D viewer labels every room "Room" — which
    # the external review flagged as synthetic-looking.
    room_labels: tuple[tuple[str, float, float], ...]


DEMO_DRAWINGS: tuple[DemoDrawingSpec, ...] = (
    DemoDrawingSpec(
        filename="demo_bungalow.dxf",
        title="Single-family bungalow",
        builder=build_bungalow_floor,
        room_labels=BUNGALOW_ROOM_LABELS,
    ),
    DemoDrawingSpec(
        filename="demo_apartment.dxf",
        title="2-bedroom apartment",
        builder=build_apartment_floor,
        room_labels=APARTMENT_ROOM_LABELS,
    ),
    DemoDrawingSpec(
        filename="demo_office.dxf",
        title="Small office",
        builder=build_office_floor,
        room_labels=OFFICE_ROOM_LABELS,
    ),
    DemoDrawingSpec(
        filename="demo_retail.dxf",
        title="Retail space",
        builder=build_retail_floor,
        room_labels=RETAIL_ROOM_LABELS,
    ),
)


def _assign_room_names(
    session: Session,
    *,
    drawing_id,
    sheet_id,
    labels: tuple[tuple[str, float, float], ...],
) -> int:
    """Match derived rooms to the builder's named specs by centroid.

    Derived rooms arrive with ``name=NULL``; the builder knows that
    the room centred near (cx, cy) is "kitchen" or "living_room". We
    iterate the rooms, find the closest unmatched label by squared
    distance to the room's bbox centroid, and write ``Element.name``.

    Greedy match: each label is used at most once. If the builder's
    label list is longer than the number of derived rooms (e.g. a
    partition that didn't close into a full polygon), leftover
    labels are silently dropped — there's nothing to attach them
    to, and the viewer falls back to "Room" for any un-named
    element.
    """
    rooms = session.execute(
        select(Element).where(
            Element.sheet_id == sheet_id,
            Element.kind == "room",
        )
    ).scalars().all()

    remaining = list(labels)
    assigned = 0
    for room in rooms:
        bbox = room.bbox or {}
        try:
            cx = (float(bbox["minx"]) + float(bbox["maxx"])) / 2
            cy = (float(bbox["miny"]) + float(bbox["maxy"])) / 2
        except (KeyError, TypeError, ValueError):
            continue
        if not remaining:
            break
        best_idx = min(
            range(len(remaining)),
            key=lambda i: (remaining[i][1] - cx) ** 2 + (remaining[i][2] - cy) ** 2,
        )
        best_name = remaining.pop(best_idx)[0]
        room.name = best_name
        session.add(room)
        assigned += 1
    if assigned:
        session.commit()
    return assigned


def _resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit(
            "DATABASE_URL not set. Point it at Postgres before running.",
        )
    return url


def _ensure_demo_user(session: Session) -> User:
    existing = session.execute(
        select(User).where(User.email == DEMO_EMAIL)
    ).scalar_one_or_none()
    if existing is not None:
        # Make sure the flag is set even if the row predates this change.
        changed = False
        if not existing.is_demo:
            existing.is_demo = True
            changed = True
        if not existing.is_active:
            existing.is_active = True
            changed = True
        if changed:
            session.add(existing)
            session.commit()
            print(f"  ↻ demo user already existed; updated flags")
        else:
            print(f"  · demo user already present ({existing.id})")
        return existing

    # Lazy-import the password hasher so the script works on a venv
    # that has atlas-core + atlas-db but not the argon2 dep (unusual
    # but possible on a minimal orchestrator box). Fail fast if
    # hashing is actually needed.
    from app.core.passwords import hash_password

    user = User(
        email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PASSWORD),
        display_name=DEMO_DISPLAY_NAME,
        is_active=True,
        is_demo=True,
        email_verified=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    print(f"  + demo user created ({user.id})")
    return user


def _drawing_exists(session: Session, *, owner_id, filename: str) -> bool:
    row = session.execute(
        select(Drawing).where(
            Drawing.owner_id == owner_id,
            Drawing.source_filename == filename,
        )
    ).scalar_one_or_none()
    return row is not None


def _seed_one_drawing(
    session: Session, user: User, spec: DemoDrawingSpec, *, tmpdir: Path
) -> None:
    if _drawing_exists(session, owner_id=user.id, filename=spec.filename):
        print(f"  · {spec.filename} already seeded; skipping")
        return

    dxf_path = spec.builder(tmpdir / spec.filename)
    size = dxf_path.stat().st_size

    drawing = Drawing(
        source_filename=spec.filename,
        source_s3_key=f"demo/{uuid4()}.dxf",
        size_bytes=size,
        # Content hash is synthetic — this path doesn't go through
        # the upload pipeline, so we encode the preset name to keep
        # it distinct per drawing and stable for idempotency.
        content_hash=f"sha256:demo-{spec.filename}-v1",
        page_count=1,
        status="completed",
        completed_at=datetime.now(UTC),
        owner_id=user.id,
        project_name=spec.title,
    )
    session.add(drawing)
    session.flush()

    sheet = Sheet(drawing_id=drawing.id, page_number=1, title=spec.title)
    session.add(sheet)
    session.flush()
    session.commit()

    summary = extract_from_dxf(session, drawing.id, dxf_path, sheet_id=sheet.id)
    session.commit()

    named = _assign_room_names(
        session,
        drawing_id=drawing.id,
        sheet_id=sheet.id,
        labels=spec.room_labels,
    )

    by_kind = summary.elements_by_kind
    print(
        f"  + {spec.filename}: "
        f"{by_kind.get('wall', 0)} walls, "
        f"{by_kind.get('door', 0)} doors, "
        f"{by_kind.get('window', 0)} windows, "
        f"{by_kind.get('room', 0)} rooms "
        f"({named} named)"
    )


def main() -> int:
    url = _resolve_database_url()
    engine = create_engine(url)

    tmpdir = Path("/tmp/atlas_demo_seed")
    tmpdir.mkdir(parents=True, exist_ok=True)

    print(f"seeding demo account against {url.split('@')[-1].split('/')[0]}")
    with Session(engine) as session:
        user = _ensure_demo_user(session)
        for spec in DEMO_DRAWINGS:
            _seed_one_drawing(session, user, spec, tmpdir=tmpdir)

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
