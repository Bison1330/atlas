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

from app.core.db import get_db
from app.db import Annotation
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
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> AnnotationsListResponse:
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
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> AnnotationOut:
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
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> None:
    svc.delete_annotation(db, annotation_id)
