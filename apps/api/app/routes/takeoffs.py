"""Material takeoffs endpoint.

GET /drawings/{id}/takeoffs aggregates the M2-extracted Element rows
into a structured takeoff report (counts + linear footage + floor
area, broken down by NCS group).

If ``source_id`` is omitted the latest *completed* extraction wins —
that's the most useful default for a quick takeoff. Pre-completion
or failed runs are skipped.

Units. The response includes an explicit ``units`` block so a UI
can label numbers honestly: we don't currently know whether the
source DXF was authored in feet, inches, meters, or millimeters,
so all measurements are reported in raw DXF units.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth_dep import owned_drawing_for_read
from app.core.db import get_db
from app.db import Drawing, Element, ElementSource, Sheet
from app.services.takeoffs import compute_takeoff

router = APIRouter(prefix="/drawings", tags=["takeoffs"])


class SubcategoryOut(BaseModel):
    label: str
    count: int
    linear_units: float | None = None
    area_units: float | None = None


class CategoryOut(BaseModel):
    kind: str
    label: str
    count: int
    total_linear_units: float | None = None
    total_area_units: float | None = None
    subcategories: list[SubcategoryOut] = Field(default_factory=list)


class UnitsOut(BaseModel):
    """Caveat block — see module docstring for why this matters."""

    linear: str = "DXF units"
    area: str = "DXF units squared"
    note: str = (
        "Atlas does not yet detect the source CAD's authoring units. "
        "Multiply by the appropriate factor for ft/in/m/mm before use."
    )


class TakeoffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawing_id: UUID
    source_id: UUID | None
    generated_at: datetime
    total_elements: int
    kinds_present: list[str]
    categories: list[CategoryOut]
    units: UnitsOut = Field(default_factory=UnitsOut)


@router.get(
    "/{drawing_id}/takeoffs",
    response_model=TakeoffResponse,
    summary="Material takeoff aggregated from extracted elements",
)
def get_takeoffs(
    drawing_id: UUID,
    _owned: Annotated[Drawing, Depends(owned_drawing_for_read)],
    source_id: Annotated[
        UUID | None,
        Query(description="Specific extraction run; defaults to latest completed."),
    ] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> TakeoffResponse:
    resolved_source_id = source_id or _latest_completed_source_id(db, drawing_id)

    elements: list[Element] = []
    if resolved_source_id is not None:
        stmt = (
            select(Element)
            .join(Sheet, Element.sheet_id == Sheet.id)
            .where(
                Sheet.drawing_id == drawing_id,
                Element.source_id == resolved_source_id,
            )
        )
        elements = list(db.execute(stmt).scalars().all())

    report = compute_takeoff(elements)

    return TakeoffResponse(
        drawing_id=drawing_id,
        source_id=resolved_source_id,
        generated_at=datetime.now(UTC),
        total_elements=report.total_elements,
        kinds_present=report.kinds_present,
        categories=[
            CategoryOut(
                kind=c.kind,
                label=c.label,
                count=c.count,
                total_linear_units=c.total_linear_units,
                total_area_units=c.total_area_units,
                subcategories=[
                    SubcategoryOut(
                        label=s.label,
                        count=s.count,
                        linear_units=s.linear_units,
                        area_units=s.area_units,
                    )
                    for s in c.subcategories
                ],
            )
            for c in report.categories
        ],
    )


def _latest_completed_source_id(db: Session, drawing_id: UUID) -> UUID | None:
    """Pick the most recent completed extraction; None when there isn't one."""
    return db.execute(
        select(ElementSource.id)
        .where(
            ElementSource.drawing_id == drawing_id,
            ElementSource.status == "completed",
        )
        .order_by(ElementSource.finished_at.desc().nullslast())
        .limit(1)
    ).scalar_one_or_none()
