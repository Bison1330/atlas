"""Tile + preview proxy endpoints.

The frontend doesn't talk to S3/MinIO directly — every tile and
preview is fetched through the API so we keep one origin (no CORS
config to maintain) and so the bucket can stay private. The cache
header is ``immutable`` because tile content is content-addressable
by ``(drawing_id, sheet_id, zoom, col, row)`` — once written for a
given coord it never changes.

The path uses UUIDs all the way down, so we don't bother round-
tripping the DB to validate the (drawing, sheet) link before each
tile fetch — a forged path that doesn't exist in S3 simply 404s.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.auth_dep import owned_drawing_for_read
from app.core.config import get_settings
from app.core.s3 import get_s3_client, sheet_preview_key, tile_key
from app.db import Drawing

router = APIRouter(prefix="/drawings", tags=["tiles"])
log = structlog.get_logger("atlas.api.tiles")

_TILE_CACHE = "public, max-age=31536000, immutable"
_PREVIEW_CACHE = "public, max-age=300"


def _stream_object(key: str, *, content_type: str, cache_control: str) -> Response:
    bucket = get_settings().s3_bucket
    try:
        obj = get_s3_client().get_object(Bucket=bucket, Key=key)
    except get_s3_client().exceptions.NoSuchKey as exc:
        raise HTTPException(status_code=404, detail="Object not found") from exc
    except Exception as exc:
        # botocore wraps 404s as ClientError with a 404 in the response;
        # check for that before flagging a true upstream failure.
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            raise HTTPException(status_code=404, detail="Object not found") from exc
        log.exception("tiles.upstream_failed", key=key)
        raise HTTPException(status_code=502, detail="Object store unavailable") from exc

    body = obj["Body"].read()
    return Response(
        content=body,
        media_type=obj.get("ContentType", content_type),
        headers={
            "Cache-Control": cache_control,
            "Content-Length": str(len(body)),
        },
    )


@router.get(
    "/{drawing_id}/sheets/{sheet_id}/preview.webp",
    summary="WebP thumbnail for a sheet",
    responses={404: {"description": "Preview not generated yet."}},
)
def get_sheet_preview(
    drawing_id: UUID,
    sheet_id: UUID,
    _owned: Annotated[Drawing, Depends(owned_drawing_for_read)],
) -> Response:
    return _stream_object(
        sheet_preview_key(str(drawing_id), str(sheet_id)),
        content_type="image/webp",
        cache_control=_PREVIEW_CACHE,
    )


@router.get(
    "/{drawing_id}/sheets/{sheet_id}/tiles/{zoom}/{col}/{row}.webp",
    summary="WebP tile at (zoom, col, row)",
    responses={404: {"description": "Tile does not exist."}},
)
def get_tile(
    drawing_id: UUID,
    sheet_id: UUID,
    zoom: int,
    col: int,
    row: int,
    _owned: Annotated[Drawing, Depends(owned_drawing_for_read)],
) -> Response:
    if zoom < 0 or col < 0 or row < 0:
        raise HTTPException(status_code=400, detail="Negative coordinate")
    return _stream_object(
        tile_key(str(drawing_id), str(sheet_id), zoom, col, row),
        content_type="image/webp",
        cache_control=_TILE_CACHE,
    )
