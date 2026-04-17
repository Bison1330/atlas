"""S3 client singleton.

Configured from settings — works with AWS S3, MinIO, DO Spaces, or any
S3-compatible endpoint via ``s3_endpoint_url``.

The client object is thread-safe; a single module-level instance is
cached. Endpoint and credentials are resolved lazily so tests can
monkey-patch ``settings`` before the first call.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from app.core.config import get_settings

if TYPE_CHECKING:
    from botocore.client import BaseClient


@lru_cache(maxsize=1)
def get_s3_client() -> BaseClient:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 5, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
        ),
    )


def ensure_bucket() -> None:
    """Create the configured bucket if it doesn't exist.

    Safe to call on every API startup. Most MinIO/S3 setups already have
    the bucket; this is a fast no-op when it does.
    """
    s = get_settings()
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=s.s3_bucket)
    except client.exceptions.ClientError:
        client.create_bucket(Bucket=s.s3_bucket)


def drawing_source_key(drawing_id: str) -> str:
    prefix = get_settings().s3_drawings_prefix.strip("/")
    return f"{prefix}/{drawing_id}/source.pdf"


def sheet_preview_key(drawing_id: str, sheet_id: str) -> str:
    prefix = get_settings().s3_drawings_prefix.strip("/")
    return f"{prefix}/{drawing_id}/sheets/{sheet_id}/preview.webp"


def tile_key(drawing_id: str, sheet_id: str, zoom: int, col: int, row: int) -> str:
    prefix = get_settings().s3_drawings_prefix.strip("/")
    return f"{prefix}/{drawing_id}/sheets/{sheet_id}/tiles/{zoom}/{col}/{row}.webp"


def extraction_source_key(drawing_id: str, source_id: str, *, ext: str = "dxf") -> str:
    """Where the uploaded source file (DXF, later IFC) lives in S3."""
    prefix = get_settings().s3_drawings_prefix.strip("/")
    return f"{prefix}/{drawing_id}/extractions/{source_id}/source.{ext}"
