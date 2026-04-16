"""Unit tests for the tile-pyramid generator."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from worker.pipeline import tiles


def _solid_image(w: int, h: int, color=(200, 50, 50)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


class TestComputeMaxZoom:
    def test_image_smaller_than_tile_returns_zero(self):
        assert tiles.compute_max_zoom(100, 80, tile_size=512, cap=7) == 0

    def test_image_equal_to_tile_returns_zero(self):
        assert tiles.compute_max_zoom(512, 512, tile_size=512, cap=7) == 0

    def test_image_4x_tile_returns_two(self):
        # log2(2048/512) = 2
        assert tiles.compute_max_zoom(2048, 1000, tile_size=512, cap=7) == 2

    def test_caps_at_cap_minus_one(self):
        # Huge image — should clamp at cap - 1
        assert tiles.compute_max_zoom(1_000_000, 1_000_000, tile_size=256, cap=5) == 4

    def test_zero_dimension_raises(self):
        with pytest.raises(ValueError):
            tiles.compute_max_zoom(0, 100, tile_size=256, cap=5)

    def test_negative_tile_size_raises(self):
        with pytest.raises(ValueError):
            tiles.compute_max_zoom(100, 100, tile_size=-1, cap=5)


class TestLevelDimensions:
    def test_max_zoom_is_full_resolution(self):
        assert tiles.level_dimensions(2000, 1500, zoom=3, max_zoom=3) == (2000, 1500)

    def test_each_step_down_halves(self):
        # zoom 2, max 3 → half size
        w, h = tiles.level_dimensions(2000, 1500, zoom=2, max_zoom=3)
        assert (w, h) == (1000, 750)

    def test_zero_zoom_smallest(self):
        # zoom 0, max 3 → 1/8 size
        w, h = tiles.level_dimensions(2048, 1024, zoom=0, max_zoom=3)
        assert (w, h) == (256, 128)

    def test_minimum_one_pixel(self):
        # Aggressive scaling that would round to 0 must clamp at 1.
        w, h = tiles.level_dimensions(3, 3, zoom=0, max_zoom=10)
        assert w >= 1 and h >= 1

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            tiles.level_dimensions(100, 100, zoom=5, max_zoom=3)


class TestTileBounds:
    def test_top_left_tile_no_overlap_on_outside(self):
        # col=0, row=0 means left/upper edge — no overlap toward negatives.
        box = tiles.tile_bounds(0, 0, tile_size=512, overlap=2, level_w=1024, level_h=1024)
        assert box == (0, 0, 514, 514)

    def test_interior_tile_has_overlap_both_sides(self):
        box = tiles.tile_bounds(1, 1, tile_size=256, overlap=4, level_w=1024, level_h=1024)
        assert box == (252, 252, 516, 516)

    def test_right_edge_clamps_to_level_width(self):
        # Last column on a 1000-wide image with 512 tile size.
        box = tiles.tile_bounds(1, 0, tile_size=512, overlap=2, level_w=1000, level_h=512)
        assert box[2] == 1000

    def test_degenerate_bounds_raise(self):
        # col entirely outside the level → would produce empty crop.
        with pytest.raises(tiles.TilingError):
            tiles.tile_bounds(5, 0, tile_size=256, overlap=0, level_w=256, level_h=256)


class TestGenerateTiles:
    def test_small_image_yields_one_tile_at_zoom_zero(self):
        img = _solid_image(100, 100)
        out = list(tiles.generate_tiles(
            img, tile_size=512, overlap=2, max_zoom_cap=7, webp_quality=80
        ))
        assert len(out) == 1
        tile = out[0]
        assert tile.zoom == 0 and tile.col == 0 and tile.row == 0
        assert tile.content_type == "image/webp"
        # Decode and verify it's a real WebP
        decoded = Image.open(io.BytesIO(tile.content))
        assert decoded.format == "WEBP"

    def test_pyramid_shape_for_2x_image(self):
        # 1024×1024 with tile_size 512 → max_zoom=1 → zoom 0 (1 tile) + zoom 1 (4 tiles) = 5
        img = _solid_image(1024, 1024)
        out = list(tiles.generate_tiles(
            img, tile_size=512, overlap=0, max_zoom_cap=7, webp_quality=80
        ))
        assert len(out) == 5
        zooms = [t.zoom for t in out]
        # Lowest zoom emitted first
        assert zooms[0] == 0
        assert zooms.count(0) == 1
        assert zooms.count(1) == 4

    def test_rgba_input_is_converted(self):
        # Ensures generate_tiles tolerates an RGBA source (raster outputs vary).
        img = Image.new("RGBA", (256, 256), (10, 10, 10, 255))
        out = list(tiles.generate_tiles(
            img, tile_size=256, overlap=0, max_zoom_cap=4, webp_quality=80
        ))
        assert out and len(out) >= 1


class TestGeneratePreview:
    def test_returns_webp_bytes(self):
        img = _solid_image(2000, 1500)
        data = tiles.generate_preview(img, max_dim=512)
        decoded = Image.open(io.BytesIO(data))
        assert decoded.format == "WEBP"
        assert max(decoded.size) <= 512

    def test_small_image_passes_through(self):
        img = _solid_image(300, 200)
        data = tiles.generate_preview(img, max_dim=1024)
        decoded = Image.open(io.BytesIO(data))
        assert decoded.size == (300, 200)
