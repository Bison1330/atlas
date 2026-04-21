#!/usr/bin/env python3
"""Generate a rich sample DXF for 3D reconstruction acceptance tests.

Writes an apartment-grid floor plan (13 walls, 3 doors, 2 windows,
6 derivable rooms) to a configurable output path — by default
``/tmp/atlas_sample.dxf``. Used to prime a prod/staging DB with
real extracted elements before session 2 of the 3D walkthrough
feature series runs its acceptance step.

Usage::

    python scripts/generate_sample_dxf.py
    python scripts/generate_sample_dxf.py --output /some/path.dxf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "apps" / "worker"))

from tests.fixtures.dxf_builders import build_apartment_grid_floor


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("/tmp/atlas_sample.dxf"),
        help="Where to write the DXF (default: /tmp/atlas_sample.dxf)",
    )
    args = parser.parse_args()

    out = build_apartment_grid_floor(args.output)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
