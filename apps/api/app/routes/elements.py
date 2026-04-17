"""Element listing endpoint.

Exposes the elements extracted by the M2 worker pipeline. Designed
for progressive disclosure: the default response is summary-only
(kind, layer/IFC classification, confidence, bbox) so a UI can list
hundreds of elements cheaply; ``?include=geometry`` adds the full
geometry/attrs/ifc_properties JSONB payload for the cases that
actually need it (the viewer overlay, an IFC export).

Filters:

- ``?source_id=`` — pin the response to a single ``ElementSource``;
  default returns elements from every source on the drawing.
- ``?kind=`` — repeatable; only return elements of these kinds.
- ``?ncs_major_group=`` — repeatable; e.g. ``WALL``.
- ``?include=geometry`` — return the geometry/attrs/ifc_properties.

Response shape mirrors the SheetSummary pattern: a top-level
``elements`` list plus a ``count`` for cheap pagination later.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.db import Element, Sheet

router = APIRouter(prefix="/drawings", tags=["elements"])


class ElementSummary(BaseModel):
    """Lightweight per-element record for the default list response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sheet_id: UUID
    source_id: UUID
    kind: str
    name: str | None = None
    number: str | None = None
    confidence: float | None = None
    ifc_type: str | None = None
    ncs_layer: str | None = None
    ncs_major_group: str | None = None
    ncs_minor_group: str | None = None
    bbox: dict[str, float] | None = None
    host_element_id: UUID | None = None


class ElementDetail(ElementSummary):
    """Full element shape for ``?include=geometry``."""

    geometry: dict[str, Any] = Field(default_factory=dict)
    attrs: dict[str, Any] = Field(default_factory=dict)
    ifc_properties: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ElementListResponse(BaseModel):
    drawing_id: UUID
    count: int
    elements: list[ElementSummary | ElementDetail]


IncludeOption = Literal["geometry"]


@router.get(
    "/{drawing_id}/elements",
    response_model=ElementListResponse,
    summary="List elements extracted from a drawing",
)
def list_elements(
    drawing_id: UUID,
    source_id: Annotated[
        UUID | None,
        Query(description="Filter to a single extraction run."),
    ] = None,
    kind: Annotated[
        list[str] | None, Query(description="Repeatable element kind filter.")
    ] = None,
    ncs_major_group: Annotated[
        list[str] | None,
        Query(description="Repeatable NCS Major group filter (e.g. 'WALL').")
    ] = None,
    include: Annotated[
        list[IncludeOption] | None,
        Query(
            description="Additional fields to include. "
            "'geometry' returns geometry + attrs + ifc_properties.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> ElementListResponse:
    want_geometry = bool(include and "geometry" in include)

    stmt = (
        select(Element)
        .join(Sheet, Element.sheet_id == Sheet.id)
        .where(Sheet.drawing_id == drawing_id)
        .order_by(Element.kind.asc(), Element.id.asc())
        .limit(limit)
    )
    if source_id is not None:
        stmt = stmt.where(Element.source_id == source_id)
    if kind:
        stmt = stmt.where(Element.kind.in_(kind))
    if ncs_major_group:
        stmt = stmt.where(Element.ncs_major_group.in_(ncs_major_group))

    rows = db.execute(stmt).scalars().all()
    model_cls = ElementDetail if want_geometry else ElementSummary
    elements = [model_cls.model_validate(row) for row in rows]

    return ElementListResponse(
        drawing_id=drawing_id, count=len(elements), elements=elements
    )
