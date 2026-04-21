#!/usr/bin/env python3
"""Generate a sample DXF for 3D reconstruction acceptance or demo seeding.

Named presets map to the builders in
``apps/worker/tests/fixtures/dxf_builders.py``. Used by both the
session-2 prep (apartment-grid) and the demo-seed script (all four
presets, one per demo drawing).

Usage::

    python scripts/generate_sample_dxf.py                       # apartment_grid
    python scripts/generate_sample_dxf.py --preset bungalow
    python scripts/generate_sample_dxf.py --preset office --output /tmp/o.dxf
    python scripts/generate_sample_dxf.py --list
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "worker"))

from tests.fixtures.dxf_builders import (  # noqa: E402
    build_apartment_grid_floor,
    build_bungalow_floor,
    build_office_floor,
    build_retail_floor,
)

PRESETS: dict[str, Callable[[Path], Path]] = {
    "apartment_grid": build_apartment_grid_floor,
    "bungalow":       build_bungalow_floor,
    "office":         build_office_floor,
    "retail":         build_retail_floor,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default="apartment_grid",
        help="Named floor-plan fixture (default: apartment_grid).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="DXF output path (default: /tmp/atlas_sample_<preset>.dxf).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the preset names and exit.",
    )
    args = parser.parse_args()

    if args.list:
        for name in sorted(PRESETS):
            print(name)
        return 0

    output = args.output or Path(f"/tmp/atlas_sample_{args.preset}.dxf")
    path = PRESETS[args.preset](output)
    print(f"wrote {path} ({path.stat().st_size} bytes) [preset={args.preset}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
