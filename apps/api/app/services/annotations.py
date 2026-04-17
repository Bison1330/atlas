"""Annotation CRUD + invariants (M6).

Pure-ish service layer — routes own the DB session and pass it in,
matching the pattern established by ``takeoffs``/``qa``. The one
non-trivial invariant enforced here is cross-drawing leakage:
a POST against ``/drawings/{A}/annotations`` may not reference an
element whose sheet belongs to drawing B. We check it explicitly
rather than rely on clients.

No auth, no row-ownership checks. Any caller can mutate any
annotation; the research doc (docs/research/m6-annotations.md §8.3)
is explicit that public deployment waits on the auth milestone.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Annotation, Drawing, Element, ElementSource, Sheet
from app.schemas.errors import APIError, NotFoundError


def create_annotation(
    session: Session,
    *,
    drawing_id: UUID,
    element_id: UUID,
    author_name: str,
    body: str,
    author_user_id: UUID | None = None,
) -> Annotation:
    """Persist a new annotation after verifying the element → drawing link.

    ``author_user_id`` (M8) records who wrote the note when the
    caller is authenticated. Nullable to preserve the pre-M8 data
    shape — existing rows stay unattributed, no backfill.

    Raises:
        NotFoundError: the drawing doesn't exist, or the element
            doesn't exist.
        APIError(400, "element_mismatch"): the element exists but
            belongs to a different drawing. Caught separately from
            "element missing" so the UI can distinguish.
    """
    drawing = session.get(Drawing, drawing_id)
    if drawing is None:
        raise NotFoundError("Drawing", str(drawing_id))

    element = session.get(Element, element_id)
    if element is None:
        raise NotFoundError("Element", str(element_id))

    sheet = session.get(Sheet, element.sheet_id)
    if sheet is None or sheet.drawing_id != drawing_id:
        raise APIError(
            code="element_mismatch",
            message=(
                f"Element {element_id} does not belong to drawing "
                f"{drawing_id}."
            ),
            status_code=400,
            details={
                "drawing_id": str(drawing_id),
                "element_id": str(element_id),
            },
        )

    ann = Annotation(
        drawing_id=drawing_id,
        element_id=element_id,
        author_name=author_name,
        body=body,
        author_user_id=author_user_id,
    )
    session.add(ann)
    session.commit()
    session.refresh(ann)
    return ann


def list_for_drawing(
    session: Session,
    drawing_id: UUID,
    *,
    element_id: UUID | None = None,
) -> list[Annotation]:
    """All annotations on a drawing, newest first.

    Optional ``element_id`` filter narrows to a single target —
    same as ``/elements/{id}/annotations`` but scoped to this
    drawing (which matters once a future milestone allows elements
    to be re-keyed across drawings).
    """
    stmt = (
        select(Annotation)
        .where(Annotation.drawing_id == drawing_id)
        .order_by(Annotation.created_at.desc())
    )
    if element_id is not None:
        stmt = stmt.where(Annotation.element_id == element_id)
    return list(session.execute(stmt).scalars().all())


def list_for_element(
    session: Session, element_id: UUID,
) -> list[Annotation]:
    """All annotations on a single element, newest first."""
    return list(session.execute(
        select(Annotation)
        .where(Annotation.element_id == element_id)
        .order_by(Annotation.created_at.desc())
    ).scalars().all())


def get_annotation(session: Session, annotation_id: UUID) -> Annotation:
    ann = session.get(Annotation, annotation_id)
    if ann is None:
        raise NotFoundError("Annotation", str(annotation_id))
    return ann


def update_annotation(
    session: Session,
    annotation_id: UUID,
    *,
    body: str | None = None,
    author_name: str | None = None,
) -> Annotation:
    ann = get_annotation(session, annotation_id)
    if body is not None:
        ann.body = body
    if author_name is not None:
        ann.author_name = author_name
    session.add(ann)
    session.commit()
    session.refresh(ann)
    return ann


def delete_annotation(session: Session, annotation_id: UUID) -> None:
    ann = get_annotation(session, annotation_id)
    session.delete(ann)
    session.commit()


# ---------------------------------------------------------------------------
# Extraction-status echo — M4 gate awareness
# ---------------------------------------------------------------------------


def element_extraction_meta(
    session: Session, element_id: UUID,
) -> dict[str, Any]:
    """Summary of the extraction state for an annotation's target.

    Returned alongside the annotation payload so clients can show
    the M4 Phase 3 caveat inline ("this annotation is attached to an
    element that hasn't been validated on real CAD files") without
    joining three tables themselves.
    """
    element = session.get(Element, element_id)
    if element is None:
        return {"extraction_status": "unknown", "confidence": None}

    src = session.get(ElementSource, element.source_id)
    return {
        # Phase-3 gating flag — flips to "validated" once a Tier 2
        # extraction eval passes. See m4-phase3-procurement.md.
        "extraction_status": "unvalidated_on_real_drawings",
        "confidence": element.confidence,
        "source_status": src.status if src is not None else None,
        "source_producer": (
            f"{src.producer_name}@{src.producer_version}"
            if src is not None else None
        ),
    }
