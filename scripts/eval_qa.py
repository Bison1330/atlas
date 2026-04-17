#!/usr/bin/env python3
"""Run the M5 Q&A pipeline against ground-truth Q/A manifests.

Usage:
    python scripts/eval_qa.py                           # all manifests
    python scripts/eval_qa.py path/to/manifest.yaml ... # specific ones
    python scripts/eval_qa.py --json                    # machine output

Each manifest names a synthetic DXF fixture (reused from the M4 eval
catalog) and a list of (question, expected) pairs. The harness
materializes the fixture's elements *through the real M2 reader +
M3 connectivity post-pass* so the eval sees what the DB would,
then asks Claude via :class:`ClaudeInterpreter`, runs the resulting
interpretation through the pure service, and asserts on:

- ``bucket`` — the classifier picked the right answer-class.
- ``citation_count`` — the executor grounded on the right number
  of elements (the citation set IS the answer per the M5 contract).
- ``answer_regex`` — the formatted prose contains the expected
  numeric/textual fact.

Exit code 0 iff every non-skipped pair passed. When
``ANTHROPIC_API_KEY`` is unset the whole run is SKIPped (not
failed), matching the extraction-eval pattern for corpora that
aren't on disk.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
QA_EVAL_DIR = REPO_ROOT / "tests" / "fixtures" / "qa-eval"
WORKER_PKG = REPO_ROOT / "apps" / "worker"
API_PKG = REPO_ROOT / "apps" / "api"

sys.path.insert(0, str(WORKER_PKG))
sys.path.insert(0, str(API_PKG))


# ---------------------------------------------------------------------------
# Result records (mirror eval_extraction.py's shape)
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    label: str
    passed: bool
    expected: Any
    actual: Any
    detail: str = ""


@dataclass
class PairResult:
    question: str
    expected: dict[str, Any]
    checks: list[CheckResult] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)


@dataclass
class EvalResult:
    name: str
    manifest: str
    skipped: bool = False
    skip_reason: str = ""
    pairs: list[PairResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.skipped and all(p.passed for p in self.pairs)


# ---------------------------------------------------------------------------
# Fixture → element-list pipeline
# ---------------------------------------------------------------------------


SHEET_ID = UUID("00000000-0000-0000-0000-000000000001")


def materialize_elements(dxf_path: Path) -> list[dict[str, Any]]:
    """Run reader + connectivity and return a flat element list.

    This mirrors what the orchestrator persists (candidates + derived
    rooms, post-G-O1 dedup against explicit A-ROOM polygons), but as
    plain dicts so the Q&A service consumes them directly.
    """
    from atlas_core import ElementKind, connectivity
    from worker.extractors import dxf as dxf_reader

    summary = dxf_reader.read_dxf(dxf_path)

    elements: list[dict[str, Any]] = []
    for c in summary.candidates:
        elements.append(_candidate_to_dict(c))

    walls = [e for e in elements if e["kind"] == ElementKind.WALL.value]
    wall_segments: list[connectivity.Segment] = []
    for w in walls:
        pts = (w["geometry"] or {}).get("points") or []
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            wall_segments.append((
                (float(a["x"]), float(a["y"])),
                (float(b["x"]), float(b["y"])),
            ))

    derived_rooms = connectivity.derive_rooms_from_walls(wall_segments)

    # G-O1 dedup against explicit A-ROOM polygons.
    explicit_rooms = [e for e in elements if e["kind"] == ElementKind.ROOM.value]
    explicit_polys = []
    for er in explicit_rooms:
        ring_raw = (er["geometry"] or {}).get("ring") or []
        ring = [(float(p["x"]), float(p["y"])) for p in ring_raw]
        if ring:
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            bbox = (min(xs), min(ys), max(xs), max(ys))
        else:
            bbox = (0.0, 0.0, 0.0, 0.0)
        explicit_polys.append((ring, bbox))
    matches = connectivity.dedup_derived_against_explicit(
        derived_rooms, explicit_polys,
    )

    for idx, room in enumerate(derived_rooms):
        if matches[idx] is not None:
            continue
        ring = [{"x": p[0], "y": p[1]} for p in room.ring]
        elements.append({
            "id": uuid4(),
            "sheet_id": SHEET_ID,
            "kind": "room",
            "ncs_layer": None,
            "ncs_major_group": None,
            "ncs_minor_group": None,
            "confidence": 0.85,
            "geometry": {"kind": "polygon", "ring": ring},
            "bbox": {
                "minx": room.bbox[0], "miny": room.bbox[1],
                "maxx": room.bbox[2], "maxy": room.bbox[3],
            },
            "attrs": {
                "derived": True, "derivation": "wall_loop",
                "area": round(room.area, 6),
            },
        })
    return elements


def _candidate_to_dict(candidate: Any) -> dict[str, Any]:
    kind = candidate.kind.value if hasattr(candidate.kind, "value") \
        else str(candidate.kind)
    return {
        "id": uuid4(),
        "sheet_id": SHEET_ID,
        "kind": kind,
        "ncs_layer": candidate.ncs_layer,
        "ncs_major_group": candidate.ncs_major_group,
        "ncs_minor_group": candidate.ncs_minor_group,
        "confidence": candidate.confidence,
        "geometry": candidate.geometry,
        "bbox": candidate.bbox,
        "attrs": candidate.attrs,
    }


# ---------------------------------------------------------------------------
# Manifest handling
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def materialize_fixture(manifest: dict[str, Any], workdir: Path) -> Path:
    fixture = manifest["fixture"]
    builder_spec = fixture["builder"]
    module_path, _, fn_name = builder_spec.partition(":")
    module = importlib.import_module(module_path)
    builder = getattr(module, fn_name)
    out = workdir / f"{manifest['name']}.dxf"
    builder(out)
    return out


# ---------------------------------------------------------------------------
# Running one pair
# ---------------------------------------------------------------------------


def run_pair(
    pair: dict[str, Any],
    elements: list[dict[str, Any]],
    interpreter: Any,
) -> PairResult:
    from app.services.qa import ask

    started = time.monotonic()
    payload = ask(pair["question"], elements, interpreter)
    elapsed = round(time.monotonic() - started, 3)

    expected = pair["expected"]
    checks: list[CheckResult] = []

    if "bucket" in expected:
        checks.append(CheckResult(
            label="bucket",
            passed=payload.answer_type == expected["bucket"],
            expected=expected["bucket"],
            actual=payload.answer_type,
        ))

    if "citation_count" in expected:
        checks.append(CheckResult(
            label="citation_count",
            passed=len(payload.citations) == expected["citation_count"],
            expected=expected["citation_count"],
            actual=len(payload.citations),
        ))

    if "citation_kinds" in expected:
        actual_kinds = sorted({c.kind for c in payload.citations})
        exp_kinds = sorted(expected["citation_kinds"])
        checks.append(CheckResult(
            label="citation_kinds",
            passed=actual_kinds == exp_kinds,
            expected=exp_kinds,
            actual=actual_kinds,
        ))

    if "answer_regex" in expected:
        pattern = expected["answer_regex"]
        checks.append(CheckResult(
            label="answer_regex",
            passed=bool(re.search(pattern, payload.answer)),
            expected=pattern,
            actual=payload.answer,
            detail=f"interpretation={payload.interpretation.bucket}",
        ))

    return PairResult(
        question=pair["question"],
        expected=expected,
        checks=checks,
        duration_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# Driver + reporting
# ---------------------------------------------------------------------------


def evaluate(
    manifest_path: Path, workdir: Path, interpreter: Any,
) -> EvalResult:
    manifest = load_manifest(manifest_path)
    name = manifest["name"]
    res = EvalResult(
        name=name,
        manifest=str(manifest_path.relative_to(REPO_ROOT)),
    )
    fixture_path = materialize_fixture(manifest, workdir)
    elements = materialize_elements(fixture_path)
    for pair in manifest.get("pairs", []):
        res.pairs.append(run_pair(pair, elements, interpreter))
    return res


def report_text(results: list[EvalResult]) -> str:
    lines: list[str] = []
    for r in results:
        if r.skipped:
            lines.append(f"⊘ SKIP {r.name}  ({r.skip_reason})")
            continue
        head = "✓ PASS" if r.passed else "✗ FAIL"
        lines.append(f"{head} {r.name}  ({len(r.pairs)} pairs)")
        for p in r.pairs:
            m = "  ✓" if p.passed else "  ✗"
            lines.append(
                f"{m} {p.question!r}  ({p.duration_seconds*1000:.0f} ms)"
            )
            for c in p.checks:
                cm = "    ✓" if c.passed else "    ✗"
                lines.append(
                    f"{cm} {c.label}: expected={c.expected!r}  "
                    f"actual={c.actual!r}"
                    + (f"  [{c.detail}]" if c.detail else "")
                )
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    pair_count = sum(len(r.pairs) for r in results if not r.skipped)
    lines.append("")
    lines.append(
        f"Summary: {passed} manifests passed · {failed} failed · "
        f"{skipped} skipped · {pair_count} Q/A pairs total"
    )
    return "\n".join(lines)


def report_json(results: list[EvalResult]) -> str:
    return json.dumps([asdict(r) for r in results], default=str, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("manifests", nargs="*", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--model",
        default=os.environ.get("ATLAS_QA_MODEL", "claude-haiku-4-5-20251001"),
    )
    args = parser.parse_args()

    manifests: list[Path] = list(args.manifests) or sorted(
        QA_EVAL_DIR.glob("*.yaml")
    )
    if not manifests:
        print("No QA manifests found.", file=sys.stderr)
        return 2

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        skipped = [
            EvalResult(
                name=p.stem, manifest=str(p.relative_to(REPO_ROOT)),
                skipped=True,
                skip_reason="ANTHROPIC_API_KEY not set — real interpreter unavailable",
            )
            for p in manifests
        ]
        print(report_json(skipped) if args.json else report_text(skipped))
        return 0

    from app.services.qa_interpreter import ClaudeInterpreter
    interpreter = ClaudeInterpreter(api_key=api_key, model=args.model)

    results: list[EvalResult] = []
    with tempfile.TemporaryDirectory(prefix="atlas-qa-eval-") as tmp:
        workdir = Path(tmp)
        for p in manifests:
            results.append(evaluate(p, workdir, interpreter))

    print(report_json(results) if args.json else report_text(results))
    return 0 if all(r.passed or r.skipped for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
