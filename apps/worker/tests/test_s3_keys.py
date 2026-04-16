"""Unit tests for S3 key formatting helpers."""

from __future__ import annotations

from worker import s3


def test_drawing_source_key_format():
    key = s3.drawing_source_key("abc-123")
    assert key == "drawings/abc-123/source.pdf"


def test_sheet_preview_key_format():
    key = s3.sheet_preview_key("d1", "s1")
    assert key == "drawings/d1/sheets/s1/preview.webp"


def test_tile_key_format():
    key = s3.tile_key("d1", "s1", zoom=3, col=4, row=5)
    assert key == "drawings/d1/sheets/s1/tiles/3/4/5.webp"


def test_tile_keys_unique_across_coords():
    a = s3.tile_key("d", "s", zoom=0, col=0, row=0)
    b = s3.tile_key("d", "s", zoom=0, col=0, row=1)
    c = s3.tile_key("d", "s", zoom=1, col=0, row=0)
    assert len({a, b, c}) == 3
