"""Tests for confidence aggregation + per-signal scorers."""

from __future__ import annotations

import math

import pytest
from atlas_core import ElementKind

from worker.extractors import ncs
from worker.extractors import validation as v

# --------------------------------------------------------------------------
# aggregate_confidence
# --------------------------------------------------------------------------


class TestAggregateConfidence:
    def test_product_default(self):
        assert v.aggregate_confidence([0.8, 0.5]) == pytest.approx(0.4)

    def test_product_explicit(self):
        assert v.aggregate_confidence([1.0, 1.0, 1.0], method="product") == 1.0
        assert v.aggregate_confidence([0.5, 0.5], method="product") == 0.25

    def test_min(self):
        assert v.aggregate_confidence([0.9, 0.3, 0.7], method="min") == pytest.approx(0.3)

    def test_mean(self):
        assert v.aggregate_confidence([0.4, 0.6, 0.8], method="mean") == pytest.approx(0.6)

    def test_empty_returns_zero(self):
        # No evidence is a stronger signal than weak evidence — don't claim what we don't know.
        assert v.aggregate_confidence([]) == 0.0
        assert v.aggregate_confidence([], method="min") == 0.0
        assert v.aggregate_confidence([], method="mean") == 0.0

    def test_clamping_handles_out_of_range(self):
        # Inputs outside [0, 1] are clamped before aggregation.
        assert v.aggregate_confidence([1.5, 0.5], method="product") == pytest.approx(0.5)
        assert v.aggregate_confidence([-0.2, 0.5], method="product") == 0.0

    def test_nan_treated_as_zero(self):
        assert v.aggregate_confidence([float("nan"), 0.9], method="product") == 0.0

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError):
            v.aggregate_confidence([1.0], method="bogus")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# score_ncs_match
# --------------------------------------------------------------------------


class TestScoreNcsMatch:
    def test_exact_match_scores_one(self):
        layer = ncs.parse_layer("A-WALL")
        assert v.score_ncs_match(layer, ElementKind.WALL) == 1.0

    def test_other_falls_through_to_half(self):
        # A-XYZ parses cleanly but isn't in the mapping table.
        layer = ncs.parse_layer("A-XYZ")
        assert layer.element_kind == ElementKind.OTHER
        assert v.score_ncs_match(layer, ElementKind.WALL) == 0.5

    def test_disagreement_scores_zero(self):
        # Layer says door, but caller is asking about wall.
        layer = ncs.parse_layer("A-DOOR")
        assert v.score_ncs_match(layer, ElementKind.WALL) == 0.0

    def test_malformed_layer_scores_zero(self):
        layer = ncs.parse_layer("not-a-real-layer")
        assert not layer.is_well_formed
        assert v.score_ncs_match(layer, ElementKind.WALL) == 0.0

    def test_empty_layer_scores_zero(self):
        assert v.score_ncs_match(ncs.parse_layer(""), ElementKind.WALL) == 0.0


# --------------------------------------------------------------------------
# score_geometric_validation
# --------------------------------------------------------------------------


class TestScoreGeometricValidation:
    def test_passed_no_slack_scores_one(self):
        assert v.score_geometric_validation(True, slack=0.0) == 1.0

    def test_passed_max_slack_scores_half(self):
        assert v.score_geometric_validation(True, slack=1.0) == 0.5

    def test_passed_mid_slack(self):
        assert v.score_geometric_validation(True, slack=0.5) == pytest.approx(0.75)

    def test_failed_always_zero(self):
        assert v.score_geometric_validation(False, slack=0.0) == 0.0
        assert v.score_geometric_validation(False, slack=1.0) == 0.0

    def test_slack_clamped(self):
        # Out-of-range slack is clamped (not raised).
        assert v.score_geometric_validation(True, slack=2.0) == 0.5
        assert v.score_geometric_validation(True, slack=-1.0) == 1.0


# --------------------------------------------------------------------------
# score_from_validators (named evidence)
# --------------------------------------------------------------------------


class TestScoreFromValidators:
    def test_named_evidence_aggregates(self):
        evidence = [
            ("ncs_match", 1.0),
            ("parallel", 0.8),
            ("thickness_in_range", 0.9),
        ]
        # Default product: 1.0 * 0.8 * 0.9 = 0.72
        assert v.score_from_validators(evidence) == pytest.approx(0.72)

    def test_min_strategy_picks_weakest(self):
        evidence = [("a", 0.9), ("b", 0.3), ("c", 0.95)]
        assert v.score_from_validators(evidence, method="min") == pytest.approx(0.3)


# --------------------------------------------------------------------------
# integration sketch — wall confidence from realistic evidence
# --------------------------------------------------------------------------


class TestRealisticWallScoring:
    def test_strong_wall_evidence(self):
        """A wall on A-WALL with a parallel double-line scores high."""
        ncs_score = v.score_ncs_match(
            ncs.parse_layer("A-WALL-EXTR"), ElementKind.WALL
        )
        parallel_score = v.score_geometric_validation(True, slack=0.1)
        confidence = v.aggregate_confidence(
            [ncs_score, parallel_score], method="product"
        )
        # NCS exact match (1.0) × geometric pass with low slack (~0.95) ≈ 0.95
        assert confidence > 0.9

    def test_layer_disagreement_destroys_confidence(self):
        """A layer that says 'door' shouldn't count as a wall regardless of geometry."""
        ncs_score = v.score_ncs_match(
            ncs.parse_layer("A-DOOR"), ElementKind.WALL
        )
        parallel_score = v.score_geometric_validation(True, slack=0.0)
        # Product: 0 × anything = 0
        assert v.aggregate_confidence([ncs_score, parallel_score]) == 0.0

    def test_weak_geometry_with_strong_ncs(self):
        """Solid NCS match but borderline geometry — confidence reflects both."""
        ncs_score = v.score_ncs_match(
            ncs.parse_layer("A-WALL"), ElementKind.WALL
        )
        parallel_score = v.score_geometric_validation(True, slack=0.95)
        c = v.aggregate_confidence([ncs_score, parallel_score])
        # 1.0 * (1 - 0.5 * 0.95) ≈ 0.525
        assert 0.45 < c < 0.6


def test_no_nan_in_outputs():
    """Sanity: no aggregator path can produce NaN."""
    inputs = [0.0, 0.5, 1.0, float("nan"), float("inf")]
    for method in ("product", "min", "mean"):
        out = v.aggregate_confidence(inputs, method=method)  # type: ignore[arg-type]
        assert not math.isnan(out)
        assert 0.0 <= out <= 1.0
