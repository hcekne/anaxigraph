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


def test_selected_candidate_explains_the_bounded_machine_workflow():
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
        "AnaxiGraph selected Strategy for src/anaxigraph/provider.py for a full agent evaluation."
    )
    assert result["why_this_pair_was_considered"] == [
        "The code shows a problem that this pattern is designed to address.",
        "Other repository evidence also supports checking this pattern here.",
    ]
    assert result["what_anaxigraph_found"] == [
        "AnaxiGraph found the code's complexity = 14. This shows a problem that the pattern may address.",
        "AnaxiGraph found the AI description's provider boundary = yes. This supports checking the pattern here.",
        "AnaxiGraph found the parsed code's single implementation = no. This points against using the pattern here.",
    ]
    assert "a second agent critiques" in result["what_happens_next"]
    assert result["queue_rank"]["value"] == 76
    assert "not a grade, pattern rating, or recommendation" in result["queue_rank"]["meaning"]


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("no_positive_evidence", "does not show the problem"),
        ("counter_evidence", "currently points away"),
        ("below_priority", "did not rank high enough"),
        ("sparse_plan_bound", "more relevant work filled"),
        ("plan_not_ready", "evaluation plan is not ready"),
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
            "AnaxiGraph has no usable information about the AI description's provider boundary "
            "for this target."
        ),
        (
            "This check needs at least summary detail for the parsed code's inheritance, but only "
            "0 of 2 relevant items met it; the best available detail was unavailable."
        ),
    ]


def test_non_candidate_has_no_fake_zero_rank_or_refactoring_instruction():
    item = _item("no_positive_evidence", selected=False)
    item["selection_reasons"] = []
    item["priority"] = 0

    result = candidate_explanation(item, "Strategy")

    assert result["queue_rank"] == {
        "value": None,
        "meaning": "No queue rank was assigned because the evidence did not create a candidate.",
    }
    assert result["what_happens_next"].startswith("No agent work is created")


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
        "AnaxiGraph checked whether the code's complexity was at least 10."
    )
    assert result["what_was_found"] == (
        "The observation met the pattern's evidence rule. It recorded the value as 14."
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

    assert "did not supply enough syntax inheritance detail" in result["conclusion"]
    assert result["required_detail"] == (
        "This pattern check needs at least summary detail about syntax inheritance."
    )
    assert result["available_detail"] == (
        "50% of the relevant analyzers could provide the required detail. The best available "
        "information came from parsed code structure."
    )
    assert result["how_to_use_this"] == (
        "Treat conclusions that depend on this information as incomplete."
    )
