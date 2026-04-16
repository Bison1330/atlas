"""S3 client for the worker.

Mirrors apps/api/app/core/s3.py so the worker can push PDFs + tiles to
the same bucket without importing from the API.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from worker.config import get_settings

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
            retries={"max_attempts": s.s3_upload_retries + 1, "mode": "standard"},
            connect_timeout=10,
            read_timeout=120,
        ),
    )


def drawing_source_key(drawing_id: str) -> str:
    prefix = get_settings().s3_drawings_prefix.strip("/")
    return f"{prefix}/{drawing_id}/source.pdf"


def sheet_preview_key(drawing_id: str, sheet_id: str) -> str:
    prefix = get_settings().s3_drawings_prefix.strip("/")
    return f"{prefix}/{drawing_id}/sheets/{sheet_id}/preview.webp"


def tile_key(drawing_id: str, sheet_id: str, zoom: int, col: int, row: int) -> str:
    prefix = get_settings().s3_drawings_prefix.strip("/")
    return f"{prefix}/{drawing_id}/sheets/{sheet_id}/tiles/{zoom}/{col}/{row}.webp"
