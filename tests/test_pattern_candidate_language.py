from __future__ import annotations

import pytest

from anaxigraph.pattern_candidate_language import (
    PATTERN_CANDIDATE_LANGUAGE_VERSION,
    candidate_capability_explanation,
    candidate_explanation,
    candidate_signal_explanation,
)


def _item(reason: str = "selected", *, selected: bool = True) -> dict:
    return {
        "target": {"path": "src/anaxigraph/provider.py", "level": "module"},
        "selected_for_evaluation": selected,
        "reason": reason,
        "priority": 76,
        "selection_reasons": ["problem_signal", "supporting_evidence"],
        "missing_evidence": [],
        "capability_gaps": [],
        "matched_signal_count": 3,
        "counter_signal_count": 1,
    }


def test_selected_candidate_explains_the_limited_ai_workflow():
    result = candidate_explanation(
        _item(),
        "Strategy",
        [
            {"role": "problem", "feature": "code.complexity", "actual": 14},
            {"role": "supporting", "feature": "semantic.provider_boundary", "actual": True},
            {"role": "counter", "feature": "syntax.single_implementation", "actual": False},
        ],
    )

    assert result["version"] == PATTERN_CANDIDATE_LANGUAGE_VERSION
    assert result["conclusion"] == (
        "AnaxiGraph selected Strategy for src/anaxigraph/provider.py for a full AI pattern check."
    )
    assert result["why_this_pair_was_considered"] == [
        "The code shows a problem that this pattern is designed to address.",
        "Other repository evidence also supports checking this pattern here.",
    ]
    assert result["what_anaxigraph_found"] == [
        "AnaxiGraph recorded the code's decision-branch count as 14. This shows a problem that the pattern may address.",
        "AnaxiGraph recorded the AI description's shared caller-facing interface for providers as yes. This supports checking the pattern here.",
        "AnaxiGraph recorded the parsed code's only one implementation as no. This points against using the pattern here.",
    ]
    assert "a separate AI pass checks" in result["what_happens_next"]
    assert result["queue_rank"]["value"] == 76
    assert (
        "not a code grade, pattern fit rating, or recommendation" in result["queue_rank"]["meaning"]
    )


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("no_positive_evidence", "does not show the problem"),
        ("counter_evidence", "currently points away"),
        ("below_priority", "did not rank high enough"),
        ("sparse_plan_bound", "higher-ranked work filled"),
        ("plan_not_ready", "has not finished choosing"),
    ],
)
def test_each_skip_reason_has_a_direct_conclusion(reason, expected):
    item = _item(reason, selected=False)
    if reason in {"no_positive_evidence", "counter_evidence", "below_priority"}:
        item["selection_reasons"] = []
        item["priority"] = 0

    assert expected in candidate_explanation(item, "Strategy")["conclusion"]


def test_capability_gap_explains_what_the_analyzer_could_not_check():
    item = _item("sparse_plan_bound", selected=False)
    item["missing_evidence"] = ["semantic.provider_boundary"]
    item["capability_gaps"] = ["syntax.inheritance:summary (0/2, best=unavailable)"]

    result = candidate_explanation(item, "Strategy")

    assert result["what_anaxigraph_could_not_check"] == [
        (
            "AnaxiGraph has no usable information about the AI description's shared caller-facing interface for providers "
            "for this target."
        ),
        (
            "This check needs a short explanation of what the code does for the parsed code's class inheritance, but only "
            "0 of 2 relevant items met it; the best available information was not available."
        ),
    ]


def test_non_candidate_has_no_fake_zero_rank_or_refactoring_instruction():
    item = _item("no_positive_evidence", selected=False)
    item["selection_reasons"] = []
    item["priority"] = 0

    result = candidate_explanation(item, "Strategy")

    assert result["queue_rank"] == {
        "value": None,
        "meaning": "No work-order score was assigned because the evidence did not create a possible pattern match.",
    }
    assert result["what_happens_next"].startswith("No AI pattern task is created")


def test_signal_detail_explains_the_check_effect_and_confidence_scale():
    result = candidate_signal_explanation(
        {
            "role": "problem",
            "feature": "code.complexity",
            "operator": "gte",
            "expected": 10,
            "actual": 14,
            "outcome": "matched",
            "confidence": 0.88,
        }
    )

    assert result["what_was_checked"] == (
        "AnaxiGraph checked whether the code's decision-branch count was at least 10."
    )
    assert result["what_was_found"] == (
        "The recorded value passed this pattern-library check. It recorded the value as 14."
    )
    assert "problem that the pattern may address" in result["how_it_affected_selection"]
    assert result["evidence_strength"] == {
        "value": 88,
        "meaning": (
            "Support for this observation is strong (88 out of 100). This measures evidence for "
            "the observation, not code quality or pattern quality."
        ),
    }


def test_capability_detail_explains_what_coverage_and_levels_mean():
    result = candidate_capability_explanation(
        {
            "fact": "syntax.inheritance",
            "minimum": "summary",
            "best_level": "structural",
            "ratio": 0.5,
            "complete": False,
        }
    )

    assert (
        "did not supply enough information about the parsed code's class inheritance"
        in result["conclusion"]
    )
    assert result["required_detail"] == (
        "This check needs a short explanation of what the code does to understand the parsed code's class inheritance."
    )
    assert result["available_detail"] == (
        "AnaxiGraph had the required information for 50% of the relevant code. The best available "
        "information came from parsed code structure."
    )
    assert result["how_to_use_this"] == (
        "Treat conclusions that depend on this information as incomplete."
    )
