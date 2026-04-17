"""REST endpoints for the ingest pipeline.

Routes mount under ``/drawings`` (the Caddyfile fronts them as
``/api/drawings``). The two read endpoints have distinct purposes:

- ``GET /drawings/{id}/status`` is a polling-friendly endpoint. Tiny
  payload, weak ETag for conditional requests, always 200 or 304
  (or 404 if the drawing doesn't exist).
- ``GET /drawings/{id}`` is the detail view. Returns 202 while the
  drawing is still mid-pipeline with a ``Retry-After`` hint, 200 with
  the full body (including sheets) once the drawing is in a terminal
  state (``completed`` or ``failed``).
"""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

from datetime import datetime

import structlog
from atlas_core import DrawingSummary, IngestStatus
from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth_dep import current_user, owned_drawing_for_read, require_csrf
from app.core.db import get_db
from app.db import Drawing, User
from app.services.drawings import (
    create_drawing_from_upload,
    drawing_to_summary,
    get_drawing,
    list_readable_drawings,
)

router = APIRouter(prefix="/drawings", tags=["drawings"])
log = structlog.get_logger("atlas.routes.drawings")


class DrawingStatus(BaseModel):
    """Minimal status payload optimized for polling."""

    id: UUID
    status: IngestStatus
    progress_percent: int = Field(ge=0, le=100)
    progress_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    page_count: int | None = None


class DrawingListItem(BaseModel):
    """One row of the drawings list (GET /drawings).

    Shape tuned for the UI's dense-list layout — enough metadata
    to render a row without a second fetch. Per-drawing sheets
    and full detail come from ``GET /drawings/{id}``.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_filename: str
    project_name: str | None = None
    project_id: UUID | None = None
    # True when the caller owns this drawing. False when they're
    # seeing it via project membership or because it's unclaimed.
    is_owner: bool
    status: IngestStatus
    progress_percent: int = Field(ge=0, le=100)
    page_count: int | None = None
    size_bytes: int
    created_at: datetime
    updated_at: datetime


class DrawingListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    drawings: list[DrawingListItem] = Field(default_factory=list)


def _status_etag(drawing) -> str:
    """Weak ETag derived from fields that change on any state transition."""
    payload = (
        f"{drawing.id}|{drawing.updated_at.isoformat()}|"
        f"{drawing.status}|{drawing.progress_percent}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f'W/"{digest}"'


@router.get(
    "",
    response_model=DrawingListResponse,
    summary="List drawings readable by the caller (owned, project-shared, or unclaimed).",
)
def list_drawings(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> DrawingListResponse:
    rows = list_readable_drawings(db, user.id)
    items = [
        DrawingListItem(
            id=d.id,
            source_filename=d.source_filename,
            project_name=d.project_name,
            project_id=d.project_id,
            is_owner=(d.owner_id == user.id),
            status=IngestStatus(d.status),
            progress_percent=d.progress_percent,
            page_count=d.page_count,
            size_bytes=d.size_bytes,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in rows
    ]
    return DrawingListResponse(count=len(items), drawings=items)


@router.post(
    "/upload",
    response_model=DrawingSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF to start the ingest pipeline",
)
async def upload_drawing(
    file: Annotated[UploadFile, File(description="PDF file to ingest.")],
    user: Annotated[User, Depends(current_user)],
    _csrf: Annotated[None, Depends(require_csrf)] = None,
    project_name: Annotated[str | None, Form()] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> DrawingSummary:
    drawing = await create_drawing_from_upload(
        db, file, project_name=project_name, owner_id=user.id,
    )
    return drawing_to_summary(drawing)


@router.get(
    "/{drawing_id}/status",
    response_model=DrawingStatus,
    responses={
        304: {"description": "Not modified — client ETag is still current."},
        404: {"description": "Drawing not found."},
    },
    summary="Lightweight status for polling",
)
def drawing_status(
    drawing: Annotated[Drawing, Depends(owned_drawing_for_read)],
    request: Request,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    etag = _status_etag(drawing)

    if if_none_match is not None and if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})

    body = DrawingStatus(
        id=drawing.id,
        status=IngestStatus(drawing.status),
        progress_percent=drawing.progress_percent,
        progress_message=drawing.progress_message,
        error_code=drawing.error_code,
        error_message=drawing.error_message,
        page_count=drawing.page_count,
    )
    return JSONResponse(
        status_code=200,
        content=body.model_dump(mode="json"),
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


@router.get(
    "/{drawing_id}",
    response_model=DrawingSummary,
    responses={
        202: {"description": "Drawing exists but is still being processed."},
        404: {"description": "Drawing not found."},
    },
    summary="Full drawing detail (202 while processing)",
)
def drawing_detail(
    drawing_id: UUID,
    _owned: Annotated[Drawing, Depends(owned_drawing_for_read)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> Response:
    drawing = get_drawing(db, drawing_id, with_sheets=True)
    current = IngestStatus(drawing.status)

    summary = drawing_to_summary(drawing, include_sheets=current.is_terminal)
    payload = summary.model_dump(mode="json")

    if current.is_terminal:
        return JSONResponse(status_code=200, content=payload)

    return JSONResponse(
        status_code=202,
        content=payload,
        headers={
            "Retry-After": "2",
            "Location": f"/drawings/{drawing_id}/status",
        },
    )
