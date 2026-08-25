from __future__ import annotations

import re

import pytest

from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.pattern_language import (
    _PATTERN_TERM_DEFINITIONS,
    PATTERN_LANGUAGE_VERSION,
    pattern_explanation,
)
from anaxigraph.semantic_file_language import explain_specialist_terms


def _evaluation(recommendation: str = "improve_conformance") -> dict:
    values = {
        "applicability": 82,
        "suitability": 91,
        "conformance": 24,
        "opportunity": 88,
        "confidence": 86,
        "benefit": 84,
        "urgency": 62,
        "execution_safety": 73,
        "migration_cost": 37,
    }
    return {
        "summary": "The provider boundary resembles Strategy, but selection policy leaks.",
        "rationale": "Three providers implement the same behavior through one boundary.",
        "presence": "partial",
        "recommendation": recommendation,
        "scores": {name: {"value": value} for name, value in values.items()},
        "evidence": ["Three providers implement the same execution contract."],
        "counter_evidence": ["Only one provider currently needs a special selection rule."],
        "prerequisites": ["Preserve provider error behavior."],
        "risks": ["Another abstraction could hide a simple selection rule."],
        "invariants": ["Every configured provider remains selectable."],
        "invalidation_conditions": ["The providers stop sharing one behavior boundary."],
    }


def _explanation(recommendation: str = "improve_conformance") -> dict:
    return pattern_explanation(
        _evaluation(recommendation),
        {
            "verdict": "approve",
            "summary": "The second agent found the scope and evidence proportionate.",
        },
        {
            "key": "module:src/anaxigraph/provider.py",
            "path": "src/anaxigraph/provider.py",
        },
        {
            "key": "strategy",
            "name": "Strategy",
            "intent": "Encapsulate interchangeable algorithms behind one stable operation contract.",
        },
    )


def test_pattern_explanation_makes_the_decision_and_all_nine_ratings_readable():
    result = _explanation()

    assert result["version"] == PATTERN_LANGUAGE_VERSION
    assert result["conclusion"].startswith("src/anaxigraph/provider.py partly follows Strategy")
    assert result["what_the_pattern_name_means"].startswith(
        "In this result, Strategy means: Put different ways of solving the same problem"
    )
    assert "so callers can switch between them" in result["what_the_pattern_name_means"]
    assert result["what_anaxigraph_saw"] == [
        "src/anaxigraph/provider.py shows some, but not all, of Strategy.",
        "Three providers implement the same required caller-visible behavior.",
    ]
    assert result["why_it_may_matter"] == (
        "Three providers implement the same behavior through one shared caller-facing interface."
    )
    assert "smallest confusing or inconsistent part" in result["what_to_do"]
    assert len(result["score_meanings"]) == 5
    assert result["score_meanings"][0]["scores"] == {
        "problem_match": 82,
        "pattern_fit": 91,
    }
    assert "not code quality" in result["score_meanings"][-1]["meaning"]
    assert "A separate AI pass checked" in result["independent_review"]


def test_pattern_explanation_keeps_counter_evidence_and_verification_in_the_main_contract():
    result = _explanation("introduce")

    assert result["reasons_not_to_change_the_code"] == [
        "Only one provider currently needs a special selection rule.",
        "Another shared layer of code could hide a simple selection rule.",
        "The providers stop sharing one caller-facing behavior.",
    ]
    assert result["how_to_check"] == [
        "Preserve provider error behavior.",
        "Every configured provider remains selectable.",
        (
            "Run focused tests for src/anaxigraph/provider.py, scan the repository again, and "
            "compare the pattern result."
        ),
    ]

    visible = str(result).lower()
    for unexplained in (
        "execution contract",
        "provider boundary",
        "selection policy",
        "behavior boundary",
        "another abstraction",
        "scope and evidence proportionate",
    ):
        assert unexplained not in visible


@pytest.mark.parametrize(
    ("recommendation", "expected"),
    [
        ("retain", "Keep Strategy"),
        ("introduce", "Consider adding Strategy"),
        ("improve_conformance", "partly follows Strategy"),
        ("replace", "replacing the current approach"),
        ("avoid", "Do not add Strategy"),
        ("no_action", "does not recommend a pattern change"),
        ("insufficient_evidence", "not enough evidence"),
    ],
)
def test_each_machine_recommendation_has_a_direct_human_conclusion(recommendation, expected):
    assert expected in _explanation(recommendation)["conclusion"]


def test_no_change_result_does_not_invent_a_refactoring_step():
    evaluation = _evaluation("no_action")
    evaluation["counter_evidence"] = []
    evaluation["risks"] = []
    evaluation["invalidation_conditions"] = []
    evaluation["prerequisites"] = []
    evaluation["invariants"] = []

    result = pattern_explanation(
        evaluation,
        {"verdict": "retain_competing", "summary": "Two explanations remain plausible."},
        {"label": "provider.py"},
        {"name": "Strategy"},
    )

    assert result["what_to_do"].startswith("Leave the structure alone")
    assert result["reasons_not_to_change_the_code"] == [
        "The current recommendation does not require a structural code change."
    ]
    assert result["how_to_check"] == [
        "Keep focused tests for provider.py passing as the code changes."
    ]
    assert "reasonable explanation" in result["independent_review"]


def test_every_bundled_pattern_defines_specialist_words_inside_its_main_meaning():
    evaluation = _evaluation("no_action")
    review = {"verdict": "approve", "summary": "The evidence supports this result."}
    target = {"label": "this code"}

    for card in bundled_pattern_catalog().cards:
        meaning = pattern_explanation(evaluation, review, target, card.as_dict())[
            "what_the_pattern_name_means"
        ]
        rewritten_intent = explain_specialist_terms(card.intent)
        for term, pattern, _definition in _PATTERN_TERM_DEFINITIONS:
            if re.search(pattern, rewritten_intent, flags=re.IGNORECASE):
                assert f"“{term}” means" in meaning, (card.name, term, meaning)

    adapter = next(card for card in bundled_pattern_catalog().cards if card.stable_key == "adapter")
    adapter_meaning = pattern_explanation(evaluation, review, target, adapter.as_dict())[
        "what_the_pattern_name_means"
    ]
    assert "“interface” means the names and operations" in adapter_meaning
    assert "“contract” means behavior or data that other code relies on" in adapter_meaning
