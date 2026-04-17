#!/usr/bin/env python3
"""Run the M2 extractor + M3 connectivity against ground-truth manifests.

Usage:
    python scripts/eval_extraction.py                     # all manifests in tier1/
    python scripts/eval_extraction.py path/to/manifest.yaml [...]
    python scripts/eval_extraction.py --json              # machine-readable output

Each manifest declares either a synthetic fixture (built from a
``builder`` import path) or a physical ``path``. The runner builds
or opens the DXF, runs the reader and connectivity algorithms in
the same shape the worker would, and reports per-fixture:

  - actual vs expected counts per element kind,
  - actual vs expected room areas (with fractional tolerance),
  - actual vs expected connectivity (hosted_doors, derived_rooms,
    adjacencies),
  - extraction wall-clock time,
  - PASS / FAIL.

Tier 2 / Tier 3 manifests with ``path:`` entries pointing at files
that aren't on disk are *skipped* with a clear note — running on a
fresh clone without the licensed corpus shouldn't be a fatal error.

Exit code 0 iff every non-skipped fixture passed.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TIER1_DIR = REPO_ROOT / "tests" / "fixtures" / "corpus" / "tier1"
WORKER_TESTS = REPO_ROOT / "apps" / "worker" / "tests"
WORKER_PKG = REPO_ROOT / "apps" / "worker"

# So `tests.fixtures.dxf_builders:build_three_room_floor` resolves
# without needing the worker installed editable.
sys.path.insert(0, str(WORKER_PKG))


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    label: str
    passed: bool
    expected: Any
    actual: Any
    detail: str = ""


@dataclass
class EvalResult:
    name: str
    manifest: str
    fixture_kind: str
    skipped: bool = False
    skip_reason: str = ""
    duration_seconds: float = 0.0
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.skipped and all(c.passed for c in self.checks)


# ---------------------------------------------------------------------------
# Manifest + fixture resolution
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def materialize_fixture(manifest: dict[str, Any], workdir: Path) -> Path | None:
    fixture = manifest["fixture"]
    kind = fixture.get("kind", "synthetic")
    if kind == "synthetic":
        builder_spec = fixture["builder"]
        module_path, _, fn_name = builder_spec.partition(":")
        module = importlib.import_module(module_path)
        builder = getattr(module, fn_name)
        out = workdir / f"{manifest['name']}.dxf"
        builder(out)
        return out
    if kind in ("dxf-file", "ifc-file"):
        rel = fixture["path"]
        path = REPO_ROOT / "tests" / "fixtures" / "corpus" / rel
        if not path.exists():
            return None
        return path
    raise ValueError(f"Unknown fixture kind: {kind}")


# ---------------------------------------------------------------------------
# Extraction wrapper
# ---------------------------------------------------------------------------


def run_extraction(dxf_path: Path) -> dict[str, Any]:
    """Run the worker reader + connectivity in-process; mirror what the
    orchestrator persists, but as plain dicts (no DB)."""
    from atlas_core import ElementKind, connectivity
    from worker.extractors import dxf as dxf_reader

    summary = dxf_reader.read_dxf(dxf_path)

    candidates = summary.candidates
    walls = [c for c in candidates if c.kind == ElementKind.WALL]
    doors = [c for c in candidates if c.kind == ElementKind.DOOR]
    explicit_rooms = [c for c in candidates if c.kind == ElementKind.ROOM]

    wall_segments = []
    for w in walls:
        pts = w.geometry.get("points") or []
        if len(pts) >= 2:
            wall_segments.append((
                (float(pts[0]["x"]), float(pts[0]["y"])),
                (float(pts[-1]["x"]), float(pts[-1]["y"])),
            ))

    door_centers = []
    for d in doors:
        c = d.geometry.get("center")
        if c:
            door_centers.append((float(c["x"]), float(c["y"])))

    derived_rooms = connectivity.derive_rooms_from_walls(wall_segments)
    hosting = connectivity.host_walls_for_doors(door_centers, wall_segments)
    adjacencies = connectivity.room_adjacency_via_doors(derived_rooms, door_centers)

    hosted_doors = sum(1 for h in hosting if h.wall_index is not None)

    return {
        "candidate_counts": _counts_by_kind(candidates),
        "explicit_rooms": len(explicit_rooms),
        "derived_rooms": [
            {"area": r.area, "bbox": r.bbox} for r in derived_rooms
        ],
        "hosted_doors": hosted_doors,
        "adjacencies": len(adjacencies),
    }


def _counts_by_kind(candidates: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in candidates:
        k = c.kind.value if hasattr(c.kind, "value") else str(c.kind)
        out[k] = out.get(k, 0) + 1
    return out


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def compare(expected: dict[str, Any], actual: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []

    el_expected = expected.get("elements") or {}

    # Per-kind counts. Walls / doors / windows / columns are count-only.
    for kind in ("wall", "door", "window", "column"):
        if kind not in el_expected:
            continue
        exp_n = el_expected[kind]["count"]
        act_n = actual["candidate_counts"].get(kind, 0)
        results.append(CheckResult(
            label=f"elements.{kind}.count",
            passed=act_n == exp_n,
            expected=exp_n,
            actual=act_n,
        ))

    # Rooms: counted as derived (the M3 post-pass output), not explicit
    # A-ROOM polygons (which the synthetic fixtures don't draw).
    if "room" in el_expected:
        exp_r = el_expected["room"]
        derived = actual["derived_rooms"]
        results.append(CheckResult(
            label="elements.room.count",
            passed=len(derived) == exp_r["count"],
            expected=exp_r["count"],
            actual=len(derived),
        ))
        if "areas" in exp_r:
            tol = exp_r.get("area_tolerance", 0.01)
            actual_areas = sorted([r["area"] for r in derived], reverse=True)
            expected_areas = sorted(exp_r["areas"], reverse=True)
            ok = (
                len(actual_areas) == len(expected_areas)
                and all(
                    abs(a - e) <= tol * max(abs(e), 1e-9)
                    for a, e in zip(actual_areas, expected_areas, strict=False)
                )
            )
            results.append(CheckResult(
                label="elements.room.areas",
                passed=ok,
                expected=expected_areas,
                actual=actual_areas,
                detail=f"tolerance={tol:g}",
            ))

    conn_expected = expected.get("connectivity") or {}
    for key in ("hosted_doors", "derived_rooms", "adjacencies"):
        if key not in conn_expected:
            continue
        exp_v = conn_expected[key]
        if key == "derived_rooms":
            act_v = len(actual["derived_rooms"])
        else:
            act_v = actual[key]
        results.append(CheckResult(
            label=f"connectivity.{key}",
            passed=act_v == exp_v,
            expected=exp_v,
            actual=act_v,
        ))

    return results


# ---------------------------------------------------------------------------
# Driver + reporting
# ---------------------------------------------------------------------------


def evaluate(manifest_path: Path, workdir: Path) -> EvalResult:
    manifest = load_manifest(manifest_path)
    name = manifest["name"]
    kind = manifest["fixture"].get("kind", "synthetic")
    res = EvalResult(
        name=name,
        manifest=str(manifest_path.relative_to(REPO_ROOT)),
        fixture_kind=kind,
    )

    fixture_path = materialize_fixture(manifest, workdir)
    if fixture_path is None:
        res.skipped = True
        res.skip_reason = (
            f"fixture path not present: {manifest['fixture'].get('path')}"
        )
        return res

    started = time.monotonic()
    actual = run_extraction(fixture_path)
    res.duration_seconds = round(time.monotonic() - started, 4)
    res.checks = compare(manifest.get("expected", {}), actual)
    return res


def report_text(results: list[EvalResult]) -> str:
    lines: list[str] = []
    for r in results:
        if r.skipped:
            lines.append(f"⊘ SKIP {r.name}  ({r.skip_reason})")
            continue
        head = "✓ PASS" if r.passed else "✗ FAIL"
        lines.append(
            f"{head} {r.name}  ({r.duration_seconds*1000:.1f} ms)"
        )
        for c in r.checks:
            mark = "  ✓" if c.passed else "  ✗"
            lines.append(
                f"{mark} {c.label}: expected={c.expected!r} actual={c.actual!r}"
                + (f"  [{c.detail}]" if c.detail else "")
            )
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    lines.append("")
    lines.append(
        f"Summary: {passed} passed · {failed} failed · {skipped} skipped"
    )
    return "\n".join(lines)


def report_json(results: list[EvalResult]) -> str:
    return json.dumps([asdict(r) for r in results], default=str, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("manifests", nargs="*", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    manifests: list[Path] = list(args.manifests)
    if not manifests:
        manifests = sorted(TIER1_DIR.glob("*.manifest.yaml"))

    if not manifests:
        print("No manifests found.", file=sys.stderr)
        return 2

    results: list[EvalResult] = []
    with tempfile.TemporaryDirectory(prefix="atlas-eval-") as tmp:
        workdir = Path(tmp)
        for path in manifests:
            results.append(evaluate(path, workdir))

    print(report_json(results) if args.json else report_text(results))

    return 0 if all(r.passed or r.skipped for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
