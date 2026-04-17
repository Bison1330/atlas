"""Extraction trigger + status endpoints.

POST /drawings/{id}/extract — accept a DXF, validate, queue an
extraction run, return the new ``ElementSource`` row.

GET /drawings/{id}/extractions — list extraction runs for a drawing,
newest first. Used by the UI to show "this drawing has been
extracted N times" + each run's status / counts / errors.

The progress event stream is the existing M1 WS at
``/ws/drawings/{id}`` — extractions emit their own
``extraction.queued / .started / .progress / .completed / .failed``
event types onto the same Redis channel so the same WS connection
can carry both ingest and extraction updates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth_dep import (
    owned_drawing_for_read,
    owned_drawing_for_write,
    require_csrf,
)
from app.core.db import get_db
from app.db import Drawing
from app.services.extractions import create_extraction_from_upload, list_extractions

router = APIRouter(prefix="/drawings", tags=["extractions"])


class ExtractionRunSummary(BaseModel):
    """Public shape of an ``element_sources`` row.

    ``params`` and ``summary`` are echoed back as opaque dicts so the
    UI can render whatever the producer chose to record without us
    having to schema-validate every key.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    drawing_id: UUID
    source_kind: str
    producer_name: str
    producer_version: str
    status: str
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    params: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


class ExtractionListResponse(BaseModel):
    drawing_id: UUID
    count: int
    extractions: list[ExtractionRunSummary]


@router.post(
    "/{drawing_id}/extract",
    response_model=ExtractionRunSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a DXF and queue an extraction run",
)
async def trigger_extraction(
    drawing_id: UUID,
    file: Annotated[UploadFile, File(description="DXF file to extract from.")],
    _owned: Annotated[Drawing, Depends(owned_drawing_for_write)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> ExtractionRunSummary:
    source = await create_extraction_from_upload(db, drawing_id, file)
    return ExtractionRunSummary.model_validate(source)


@router.get(
    "/{drawing_id}/extractions",
    response_model=ExtractionListResponse,
    summary="List extraction runs for a drawing",
)
def get_extractions(
    drawing_id: UUID,
    _owned: Annotated[Drawing, Depends(owned_drawing_for_read)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> ExtractionListResponse:
    rows = list_extractions(db, drawing_id)
    return ExtractionListResponse(
        drawing_id=drawing_id,
        count=len(rows),
        extractions=[ExtractionRunSummary.model_validate(r) for r in rows],
    )
