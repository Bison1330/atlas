"""GET /drawings/{id}/sheets/{id}/model3d — Three.js-ready 3D scene.

Pipeline on the hot path (cache miss)::

    Element rows ──▶ reconstruct_translator ──▶ StructuredSheet
                                                      │
                                                      ▼
                                            reconstruct3d.reconstruct_sheet
                                                      │
                                                      ▼
                                          Scene3D + TranslatorStats
                                                      │
                                                      ▼
                                             Model3DResponse

Redis caches the fully-assembled response body for 24h. The cache
key is a SHA-256 of ``sheet_id : latest_source_updated_at :
element_count`` so any re-extraction invalidates it automatically
without us needing a busting step. ETag mirrors the cache key so
browsers can skip the response body on a re-visit.

Redis unavailable → log + fall through to uncached. Reconstruction
crash → 500 with ``model3d_reconstruction_failed`` via the standard
``ServiceError`` envelope; the original exception is reported to
Sentry by the existing request-scoped integration.
"""

from __future__ import annotations

import hashlib
import time
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth_dep import owned_drawing_for_read
from app.core.db import get_db
from app.core.redis import get_redis
from app.db import Drawing, Element, ElementSource, Sheet
from app.schemas.errors import NotFoundError, ServiceError
from app.services.reconstruct_translator import (
    elements_to_structured_sheet,
)

from atlas_core.reconstruct3d import Scene3D, reconstruct_sheet

router = APIRouter(prefix="/drawings", tags=["model3d"])
log = structlog.get_logger("atlas.api.routes.model3d")

_CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE_KEY_PREFIX = "atlas:model3d:"
_STRUCTURAL_KINDS = ("wall", "door", "window", "room")


class Model3DStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wall_count: int
    floor_count: int
    opening_count: int
    failed_opening_count: int
    vertex_count: int
    triangle_count: int
    generation_ms: int
    missing_door_width: int = 0
    missing_window_width: int = 0
    missing_wall_thickness: int = 0
    synthesized_insert_bbox: int = 0
    dropped_elements: int = 0


class Model3DResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawing_id: UUID
    sheet_id: UUID
    scene: Scene3D
    stats: Model3DStats


@router.get(
    "/{drawing_id}/sheets/{sheet_id}/model3d",
    response_model=Model3DResponse,
    summary="Three.js-ready 3D scene reconstructed from a sheet's elements",
)
def get_model3d(
    drawing_id: UUID,
    sheet_id: UUID,
    request: Request,
    response: Response,
    _owned: Annotated[Drawing, Depends(owned_drawing_for_read)],
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> Response:
    sheet = _resolve_sheet(db, drawing_id, sheet_id)
    cache_key, element_count = _compute_cache_key(db, drawing_id, sheet)
    etag = f'W/"{cache_key}"'

    # Short-circuit on client ETag match — zero bytes on the wire.
    if_none_match = request.headers.get("If-None-Match")
    if if_none_match and if_none_match == etag:
        return _etag_304(etag)

    cached_body = _try_cache_get(cache_key)
    if cached_body is not None:
        return _json_response(cached_body, etag=etag, cache="HIT")

    # --- cold path -----------------------------------------------------------
    rows = _load_structural_elements(db, sheet.id)
    t0 = time.monotonic()
    try:
        structured, translator_stats = elements_to_structured_sheet(sheet, rows)
        scene = reconstruct_sheet(structured)
    except Exception as exc:
        log.exception(
            "model3d.reconstruction_failed",
            drawing_id=str(drawing_id),
            sheet_id=str(sheet_id),
            element_count=element_count,
        )
        raise ServiceError(
            code="model3d_reconstruction_failed",
            message="3D reconstruction failed for this sheet.",
            status_code=500,
            details={"sheet_id": str(sheet_id)},
        ) from exc
    generation_ms = int((time.monotonic() - t0) * 1000)

    failed_opening_count = sum(1 for o in scene.openings if o.failed)
    vertex_count = sum(len(w.vertices) // 3 for w in scene.walls) + sum(
        len(f.vertices) // 3 for f in scene.floors
    )
    triangle_count = sum(len(w.indices) // 3 for w in scene.walls) + sum(
        len(f.indices) // 3 for f in scene.floors
    )

    payload = Model3DResponse(
        drawing_id=drawing_id,
        sheet_id=sheet.id,
        scene=scene,
        stats=Model3DStats(
            wall_count=len(scene.walls),
            floor_count=len(scene.floors),
            opening_count=len(scene.openings),
            failed_opening_count=failed_opening_count,
            vertex_count=vertex_count,
            triangle_count=triangle_count,
            generation_ms=generation_ms,
            missing_door_width=translator_stats.missing_door_width,
            missing_window_width=translator_stats.missing_window_width,
            missing_wall_thickness=translator_stats.missing_wall_thickness,
            synthesized_insert_bbox=translator_stats.synthesized_insert_bbox,
            dropped_elements=translator_stats.dropped_elements,
        ),
    )
    body = payload.model_dump_json()
    _try_cache_set(cache_key, body)
    return _json_response(body, etag=etag, cache="MISS")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_sheet(db: Session, drawing_id: UUID, sheet_id: UUID) -> Sheet:
    sheet = db.execute(
        select(Sheet).where(Sheet.id == sheet_id, Sheet.drawing_id == drawing_id)
    ).scalar_one_or_none()
    if sheet is None:
        raise NotFoundError("sheet", str(sheet_id))
    return sheet


def _load_structural_elements(db: Session, sheet_id: UUID) -> list[Element]:
    return list(
        db.execute(
            select(Element)
            .where(
                Element.sheet_id == sheet_id,
                Element.kind.in_(_STRUCTURAL_KINDS),
            )
            .order_by(Element.kind.asc(), Element.id.asc())
        ).scalars()
    )


def _compute_cache_key(
    db: Session, drawing_id: UUID, sheet: Sheet
) -> tuple[str, int]:
    """Return ``(sha256_hexdigest, structural_element_count)``.

    Key includes anything that can change the 3D output: the sheet
    itself, the latest extraction run on the drawing (its
    ``updated_at`` bumps on re-extract), and the count of structural
    elements on the sheet.
    """
    latest_updated = db.execute(
        select(func.max(ElementSource.updated_at)).where(
            ElementSource.drawing_id == drawing_id
        )
    ).scalar_one_or_none()
    count = db.execute(
        select(func.count())
        .select_from(Element)
        .where(Element.sheet_id == sheet.id, Element.kind.in_(_STRUCTURAL_KINDS))
    ).scalar_one()
    ts = latest_updated.isoformat() if latest_updated is not None else "none"
    raw = f"{sheet.id}:{ts}:{count}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest, int(count)


def _json_response(body: str, *, etag: str, cache: str) -> Response:
    return Response(
        content=body,
        media_type="application/json",
        headers={"ETag": etag, "X-Cache": cache},
    )


def _etag_304(etag: str) -> Response:
    return Response(status_code=304, headers={"ETag": etag})


# --- Redis degradation ------------------------------------------------------


def _try_cache_get(cache_key: str) -> str | None:
    try:
        raw = get_redis().get(_CACHE_KEY_PREFIX + cache_key)
    except Exception as exc:  # pragma: no cover - exercised via Redis-down test
        log.warning("model3d.cache_get_failed", error=str(exc))
        return None
    if raw is None:
        return None
    # Decoded responses from our redis client — it's already str.
    return raw if isinstance(raw, str) else raw.decode("utf-8")


def _try_cache_set(cache_key: str, body: str) -> None:
    try:
        get_redis().set(
            _CACHE_KEY_PREFIX + cache_key,
            body,
            ex=_CACHE_TTL_SECONDS,
        )
    except Exception as exc:  # pragma: no cover - exercised via Redis-down test
        log.warning("model3d.cache_set_failed", error=str(exc))


