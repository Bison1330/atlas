"""Tile-pyramid generation.

Turns a rasterized sheet image into a pyramid of WebP tiles.

Coordinate conventions (OpenSeadragon / DeepZoom compatible):

- Zoom 0 is the smallest level where the entire image fits inside a
  single ``tile_size × tile_size`` square.
- Each subsequent zoom level is 2× the previous.
- Zoom ``max_zoom`` is the full-resolution image.
- Tiles are addressed as ``(zoom, col, row)`` with 0-indexed col/row
  and row 0 at the top.
- Tiles include an ``overlap`` border on the non-boundary sides so
  panning between tiles in the viewer is seamless.

The public entrypoint is :func:`generate_tiles` which yields
``GeneratedTile`` records one at a time — keeping at most a single
scaled image + the current tile in memory.
"""

from __future__ import annotations

import io
import math
from collections.abc import Iterator
from dataclasses import dataclass

from PIL import Image

from worker.pipeline.errors import TilingError


@dataclass(slots=True)
class GeneratedTile:
    zoom: int
    col: int
    row: int
    width: int
    height: int
    content: bytes
    content_type: str = "image/webp"


def compute_max_zoom(width: int, height: int, *, tile_size: int, cap: int) -> int:
    """Smallest ``max_zoom`` such that the full image fits in a grid.

    Returns a value in ``[0, cap]``. ``cap`` is exclusive of the count
    (e.g. ``cap=7`` → zoom levels ``0..6``).
    """
    if width <= 0 or height <= 0 or tile_size <= 0:
        raise ValueError("width, height, and tile_size must all be positive")
    longest = max(width, height)
    if longest <= tile_size:
        return 0
    needed = math.ceil(math.log2(longest / tile_size))
    return max(0, min(cap - 1, needed))


def level_dimensions(
    full_width: int, full_height: int, *, zoom: int, max_zoom: int
) -> tuple[int, int]:
    """Pixel dimensions of the image at the given zoom level."""
    if not 0 <= zoom <= max_zoom:
        raise ValueError(f"zoom {zoom} out of range [0, {max_zoom}]")
    scale = 2 ** (zoom - max_zoom)  # fraction <= 1
    w = max(1, math.ceil(full_width * scale))
    h = max(1, math.ceil(full_height * scale))
    return w, h


def tile_grid_size(level_w: int, level_h: int, *, tile_size: int) -> tuple[int, int]:
    """Number of (cols, rows) at a given level."""
    return (
        max(1, math.ceil(level_w / tile_size)),
        max(1, math.ceil(level_h / tile_size)),
    )


def tile_bounds(
    col: int,
    row: int,
    *,
    tile_size: int,
    overlap: int,
    level_w: int,
    level_h: int,
) -> tuple[int, int, int, int]:
    """Pixel crop box ``(left, upper, right, lower)`` for tile ``(col, row)``.

    Non-boundary edges are expanded by ``overlap`` so adjacent tiles
    share a few pixels for smooth panning.
    """
    left = max(0, col * tile_size - overlap)
    upper = max(0, row * tile_size - overlap)
    right = min(level_w, (col + 1) * tile_size + overlap)
    lower = min(level_h, (row + 1) * tile_size + overlap)
    if right <= left or lower <= upper:
        raise TilingError(
            f"Degenerate tile bounds at ({col}, {row}): "
            f"level {level_w}x{level_h}"
        )
    return left, upper, right, lower


def generate_tiles(
    image: Image.Image,
    *,
    tile_size: int,
    overlap: int,
    max_zoom_cap: int,
    webp_quality: int,
) -> Iterator[GeneratedTile]:
    """Yield every tile in the pyramid, lowest-zoom first.

    Working from zoom 0 upward (smallest → largest) lets clients start
    rendering the low-res overview almost immediately while the
    higher-zoom tiles are still being uploaded.
    """
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")

    full_w, full_h = image.size
    max_zoom = compute_max_zoom(
        full_w, full_h, tile_size=tile_size, cap=max_zoom_cap
    )

    for zoom in range(0, max_zoom + 1):
        level_w, level_h = level_dimensions(
            full_w, full_h, zoom=zoom, max_zoom=max_zoom
        )
        if zoom == max_zoom:
            level_image = image
        else:
            level_image = image.resize((level_w, level_h), Image.Resampling.LANCZOS)

        cols, rows = tile_grid_size(level_w, level_h, tile_size=tile_size)
        for row in range(rows):
            for col in range(cols):
                box = tile_bounds(
                    col, row,
                    tile_size=tile_size, overlap=overlap,
                    level_w=level_w, level_h=level_h,
                )
                tile_img = level_image.crop(box)
                buf = io.BytesIO()
                tile_img.save(buf, format="WEBP", quality=webp_quality, method=4)
                yield GeneratedTile(
                    zoom=zoom,
                    col=col,
                    row=row,
                    width=tile_img.width,
                    height=tile_img.height,
                    content=buf.getvalue(),
                )
                tile_img.close()

        if level_image is not image:
            level_image.close()


def generate_preview(
    image: Image.Image, *, max_dim: int = 1024, webp_quality: int = 75
) -> bytes:
    """A single low-res WebP used as the sheet's preview thumbnail."""
    w, h = image.size
    scale = min(1.0, max_dim / max(w, h))
    if scale < 1.0:
        preview = image.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )
    else:
        preview = image
    if preview.mode not in ("RGB", "RGBA"):
        preview = preview.convert("RGB")
    buf = io.BytesIO()
    preview.save(buf, format="WEBP", quality=webp_quality, method=4)
    if preview is not image:
        preview.close()
    return buf.getvalue()
