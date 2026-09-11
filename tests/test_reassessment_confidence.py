"""Confidence must survive projection as the thing the source actually recorded.

A reader distinguishes three states that earlier projections collapsed into one
optimistic number: a measured low confidence, a reported zero, and no recorded
confidence at all. An opportunity or strength score answers a different question
and must never be presented as confidence.
"""

from __future__ import annotations

from typing import Any

from anaxigraph.reassessment_advice import reassessment_advice
from anaxigraph.reassessment_semantic_advice import (
    pattern_effect_spec,
    reported_confidence,
    semantic_effect_specs,
)


def _pattern(scores: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommendation": "adopt",
        "target": {"path": "src/example.py"},
        "pattern": {"name": "Strategy", "key": "strategy"},
        "summary": "Reviewed Strategy fit.",
        "rationale": "Two branches select behavior by type.",
        "details": {"counter_evidence": ["Only two variants exist today."]},
        "scores": scores,
    }


def test_a_large_opportunity_never_raises_a_low_recorded_confidence():
    spec = pattern_effect_spec(_pattern({"opportunity": 95, "confidence": 20}))

    assert spec is not None
    assert spec["confidence"] == 0.2
    assert spec["classification"] == "opportunity"


def test_reported_zero_and_absent_confidence_stay_distinct():
    zero = pattern_effect_spec(_pattern({"opportunity": 95, "confidence": 0}))
    absent = pattern_effect_spec(_pattern({"opportunity": 95}))

    assert zero is not None and absent is not None
    assert zero["confidence"] == 0.0
    assert absent["confidence"] is None


def test_confidence_is_independent_of_opportunity():
    low_opportunity = pattern_effect_spec(_pattern({"opportunity": 10, "confidence": 90}))

    assert low_opportunity is not None
    assert low_opportunity["confidence"] == 0.9


def test_reported_confidence_preserves_zero_and_refuses_to_invent_a_value():
    assert reported_confidence(0) == 0.0
    assert reported_confidence(None) is None
    assert reported_confidence("") is None
    assert reported_confidence(True) is None
    assert reported_confidence(20, scale=100) == 0.2


def _module_change(semantic: dict[str, Any]) -> dict[str, Any]:
    return {
        "module_changes": [{"path": "src/example.py", "after": {"semantic": semantic}}],
    }


def test_a_consolidation_strength_score_is_not_presented_as_confidence():
    evidence = _module_change(
        {
            "confidence": 0.9,
            "consolidation_assessment": {
                "recommendation": "merge",
                "score": 76,
                "rationale": "Two adapters repeat one routing rule.",
                "candidates": ["src/other.py"],
                "evidence": ["shared routing"],
                "counter_evidence": [],
            },
        }
    )

    spec = next(
        item for item in semantic_effect_specs(evidence) if item["category"] == "duplication"
    )

    assert spec["confidence"] is None
    assert "76 of 100" in spec["observation"]
    assert "not a confidence" in spec["basis"]


def test_unused_code_uses_the_candidate_confidence_not_the_whole_dossier():
    evidence = _module_change(
        {
            "confidence": 0.95,
            "dead_code_candidates": [
                {
                    "path_or_symbol": "src/example.py::unused",
                    "confidence": 0.3,
                    "rationale": "No caller was found.",
                    "reachability_evidence": [],
                    "counter_evidence": ["Plugins can register it at runtime."],
                    "verification": "Search runtime registration.",
                }
            ],
        }
    )

    spec = next(
        item
        for item in semantic_effect_specs(evidence)
        if item["category"] == "possible_unused_code"
    )

    assert spec["confidence"] == 0.3


def _advice(effects_source: dict[str, Any]) -> list[dict[str, Any]]:
    advice = reassessment_advice(effects_source, patterns=[], change_coupling={})
    return advice["effects"]


def test_user_facing_labels_separate_unknown_from_limited_confidence():
    absent = _advice(
        _module_change(
            {
                "confidence": 0.9,
                "dead_code_candidates": [
                    {
                        "path_or_symbol": "src/example.py::unused",
                        "rationale": "No caller was found.",
                        "reachability_evidence": [],
                        "counter_evidence": [],
                        "verification": "Search runtime registration.",
                    }
                ],
            }
        )
    )
    reported_low = _advice(
        _module_change(
            {
                "confidence": 0.9,
                "dead_code_candidates": [
                    {
                        "path_or_symbol": "src/example.py::unused",
                        "confidence": 0.0,
                        "rationale": "No caller was found.",
                        "reachability_evidence": [],
                        "counter_evidence": [],
                        "verification": "Search runtime registration.",
                    }
                ],
            }
        )
    )

    unknown = next(item for item in absent if item["category"] == "possible_unused_code")
    zero = next(item for item in reported_low if item["category"] == "possible_unused_code")

    assert unknown["confidence"]["label"] == "unknown"
    assert unknown["confidence"]["score"] is None
    assert zero["confidence"]["label"] == "none"
    assert zero["confidence"]["score"] == 0.0
