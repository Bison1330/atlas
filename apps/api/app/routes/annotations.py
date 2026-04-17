"""HTTP surface for element annotations (M6).

Endpoints (see ``docs/research/m6-annotations.md`` for rationale):

- ``POST /drawings/{drawing_id}/annotations`` — create a note
  attached to a specific element on this drawing. Rejects
  cross-drawing references up front (400 element_mismatch).
- ``GET /drawings/{drawing_id}/annotations`` — list every
  annotation on this drawing, newest first. Optional
  ``?element_id=`` narrows to a single target.
- ``GET /elements/{element_id}/annotations`` — convenience route
  for UIs wired off M5 citations; same service call, element scope.
- ``PATCH /annotations/{annotation_id}`` — update body / author_name.
- ``DELETE /annotations/{annotation_id}`` — 204 on success.

Every response that carries an annotation body also carries
``element_extraction_meta`` — the cited element's current
``extraction_status``, ``confidence``, and source producer — so the
UI can surface the M4 Phase 3 caveat inline without a second
request.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth_dep import (
    current_user,
    owned_drawing_for_read,
    owned_drawing_for_write,
    require_csrf,
)
from app.core.db import get_db
from app.db import Annotation, Drawing, Element, Sheet, User
from app.schemas.errors import APIError, NotFoundError
from app.services import annotations as svc

drawing_router = APIRouter(prefix="/drawings", tags=["annotations"])
element_router = APIRouter(prefix="/elements", tags=["annotations"])
annotation_router = APIRouter(prefix="/annotations", tags=["annotations"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AnnotationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: UUID
    author_name: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)


class AnnotationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author_name: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, min_length=1, max_length=4000)


class ElementExtractionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extraction_status: str
    confidence: float | None = None
    source_status: str | None = None
    source_producer: str | None = None


class AnnotationOut(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    drawing_id: UUID
    element_id: UUID
    author_name: str
    body: str
    created_at: Annotated[str, Field(description="ISO-8601 UTC timestamp")]
    updated_at: Annotated[str, Field(description="ISO-8601 UTC timestamp")]
    element_extraction_meta: ElementExtractionMeta


class AnnotationsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawing_id: UUID | None = None
    element_id: UUID | None = None
    annotations: list[AnnotationOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _drawing_for_element(
    session: Session, element_id: UUID,
) -> Drawing:
    """Resolve an element → its sheet → its drawing.

    Shared helper for endpoints that key off ``element_id`` or
    ``annotation_id`` rather than ``drawing_id`` — used for the
    auth check (caller must own the drawing that the element
    belongs to). Raises 404 when the chain is broken at any link.
    """
    element = session.get(Element, element_id)
    if element is None:
        raise NotFoundError("Element", str(element_id))
    sheet = session.get(Sheet, element.sheet_id)
    if sheet is None:
        raise NotFoundError("Sheet", str(element.sheet_id))
    drawing = session.get(Drawing, sheet.drawing_id)
    if drawing is None:
        raise NotFoundError("Drawing", str(sheet.drawing_id))
    return drawing


def _require_drawing_owner(drawing: Drawing, user: User) -> None:
    """Owner-only write gate; 404 if the drawing belongs to someone else."""
    if drawing.owner_id is None:
        raise APIError(
            code="drawing_unclaimed",
            message=(
                f"Drawing {drawing.id} is unclaimed. Claim it first via "
                f"POST /drawings/{drawing.id}/claim."
            ),
            status_code=409,
        )
    if drawing.owner_id != user.id:
        raise NotFoundError("Drawing", str(drawing.id))


def _to_out(session: Session, ann: Annotation) -> AnnotationOut:
    meta = svc.element_extraction_meta(session, ann.element_id)
    return AnnotationOut(
        id=ann.id,
        drawing_id=ann.drawing_id,
        element_id=ann.element_id,
        author_name=ann.author_name,
        body=ann.body,
        created_at=ann.created_at.isoformat(),
        updated_at=ann.updated_at.isoformat(),
        element_extraction_meta=ElementExtractionMeta(**meta),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@drawing_router.post(
    "/{drawing_id}/annotations",
    response_model=AnnotationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an annotation attached to an element on this drawing.",
)
def create_annotation(
    drawing_id: UUID,
    body: AnnotationIn,
    _owned: Annotated[Drawing, Depends(owned_drawing_for_write)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> AnnotationOut:
    ann = svc.create_annotation(
        db,
        drawing_id=drawing_id,
        element_id=body.element_id,
        author_name=body.author_name,
        body=body.body,
    )
    return _to_out(db, ann)


@drawing_router.get(
    "/{drawing_id}/annotations",
    response_model=AnnotationsListResponse,
    summary="List annotations on a drawing (optionally filtered by element).",
)
def list_drawing_annotations(
    drawing_id: UUID,
    _owned: Annotated[Drawing, Depends(owned_drawing_for_read)],
    element_id: Annotated[
        UUID | None,
        Query(description="Filter to a single element."),
    ] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> AnnotationsListResponse:
    rows = svc.list_for_drawing(db, drawing_id, element_id=element_id)
    return AnnotationsListResponse(
        drawing_id=drawing_id,
        element_id=element_id,
        annotations=[_to_out(db, a) for a in rows],
    )


@element_router.get(
    "/{element_id}/annotations",
    response_model=AnnotationsListResponse,
    summary="List annotations attached to a specific element.",
)
def list_element_annotations(
    element_id: UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> AnnotationsListResponse:
    # Resolve the element's drawing and enforce read access (owner
    # or unclaimed). Unclaimed is OK for reads since the caller
    # could go on to claim the drawing if they wanted to annotate.
    drawing = _drawing_for_element(db, element_id)
    if drawing.owner_id is not None and drawing.owner_id != user.id:
        raise NotFoundError("Element", str(element_id))
    rows = svc.list_for_element(db, element_id)
    return AnnotationsListResponse(
        element_id=element_id,
        annotations=[_to_out(db, a) for a in rows],
    )


@annotation_router.patch(
    "/{annotation_id}",
    response_model=AnnotationOut,
    summary="Update an annotation's body and/or author name.",
)
def patch_annotation(
    annotation_id: UUID,
    body: AnnotationUpdate,
    user: Annotated[User, Depends(current_user)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> AnnotationOut:
    existing = svc.get_annotation(db, annotation_id)
    drawing = db.get(Drawing, existing.drawing_id)
    if drawing is None:
        raise NotFoundError("Annotation", str(annotation_id))
    _require_drawing_owner(drawing, user)
    ann = svc.update_annotation(
        db,
        annotation_id,
        body=body.body,
        author_name=body.author_name,
    )
    return _to_out(db, ann)


@annotation_router.delete(
    "/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an annotation.",
)
def delete_annotation(
    annotation_id: UUID,
    user: Annotated[User, Depends(current_user)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> None:
    existing = svc.get_annotation(db, annotation_id)
    drawing = db.get(Drawing, existing.drawing_id)
    if drawing is None:
        raise NotFoundError("Annotation", str(annotation_id))
    _require_drawing_owner(drawing, user)
    svc.delete_annotation(db, annotation_id)
