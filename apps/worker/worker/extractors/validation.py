"""Per-element confidence scoring.

Combine evidence from multiple extractors (NCS layer match,
geometric validators, etc.) into a single ``confidence`` value that
gets persisted on ``Element.confidence``. Strict ``[0, 1]`` range
matches the DB CHECK constraint and the Pydantic field.

Aggregation modes:

- ``"product"`` — each piece of evidence is independent; combined
  confidence is the product. Conservative — one weak signal pulls
  the whole element down. Default for "all of these must hold".
- ``"min"`` — pessimistic worst-case. Useful when any single failure
  should be disqualifying.
- ``"mean"`` — arithmetic mean. For roughly equal-weight signals
  where one weak observation shouldn't be disqualifying.

Helpers per signal type:

- :func:`score_ncs_match` — NCS layer → claimed kind. Strong when
  the layer is well-formed *and* the major group maps to the same
  kind we're claiming; weak when the layer is malformed; zero when
  the major group disagrees with the claim outright.
- :func:`score_geometric_validation` — wraps the boolean+slack
  output of a geometric validator into a confidence value.
- :func:`score_from_validators` — convenience: takes a sequence of
  ``(name, confidence)`` and runs them through the chosen aggregator.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal

from atlas_core import ElementKind

from worker.extractors.ncs import NcsLayer

AggregationMethod = Literal["product", "min", "mean"]


def aggregate_confidence(
    scores: Iterable[float],
    method: AggregationMethod = "product",
) -> float:
    """Combine multiple ``[0, 1]`` evidence scores into one.

    Empty input returns 0.0 — "no evidence" is a stronger signal
    than "weak evidence", and we'd rather under-claim than over-claim
    on something we have nothing to say about.
    """
    values = [_clamp(s) for s in scores]
    if not values:
        return 0.0
    if method == "product":
        out = 1.0
        for v in values:
            out *= v
        return out
    if method == "min":
        return min(values)
    if method == "mean":
        return sum(values) / len(values)
    raise ValueError(f"Unknown aggregation method: {method}")


def score_ncs_match(layer: NcsLayer, expected_kind: ElementKind) -> float:
    """How strongly does this NCS layer support claiming ``expected_kind``?

    Decision table:

    ============================  =====
    Condition                     Score
    ============================  =====
    Malformed layer               0.0
    Layer maps to expected kind   1.0
    Layer maps to OTHER           0.5
    Layer maps to a different
        first-class kind          0.0
    ============================  =====
    """
    if not layer.is_well_formed:
        return 0.0
    kind = layer.element_kind
    if kind is None:
        return 0.0
    if kind == expected_kind:
        return 1.0
    if kind == ElementKind.OTHER:
        # Layer is structural NCS but the Major group isn't in our
        # mapping table — could still be a real X, just one we
        # haven't catalogued. Don't disqualify, but don't endorse.
        return 0.5
    # Layer claims a different first-class kind — direct disagreement.
    return 0.0


def score_geometric_validation(
    passed: bool,
    *,
    slack: float = 0.0,
) -> float:
    """Wrap a validator's pass/fail into a confidence number.

    ``slack`` in ``[0, 1]`` is "how close to the tolerance edge
    were we?" — 0.0 means "comfortably inside", 1.0 means "right at
    the cliff". A passing validator with high slack is less
    confidence-reinforcing than a passing validator with no slack.
    Failing validators always score 0.0 regardless of slack.
    """
    if not passed:
        return 0.0
    s = _clamp(slack)
    return 1.0 - 0.5 * s


def score_from_validators(
    evidence: Iterable[tuple[str, float]],
    *,
    method: AggregationMethod = "product",
) -> float:
    """Aggregate named evidence; ignores names but useful at call sites
    so the caller can document what each score means."""
    return aggregate_confidence((c for _, c in evidence), method=method)


def _clamp(v: float) -> float:
    """Clamp to [0, 1] and treat NaN as 0."""
    if math.isnan(v):
        return 0.0
    return max(0.0, min(1.0, v))
