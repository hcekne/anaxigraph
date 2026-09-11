"""A recommendation may carry a plan; only a real check makes it verified.

The gap these tests close is the one between proposing a change and observing that
behavior survived it. AnaxiGraph never runs the change, so the only honest report of
behavior is the one a tool that did run it supplied, tied to the revision it ran on.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator

from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_REVIEW_SCHEMA,
    attributed_verification,
)
from anaxigraph.semantic_freshness import semantic_input_hash

_ITEM = FRESH_EYES_REVIEW_SCHEMA["properties"]["recommendations"]["items"]


def _recommendation(**extra: Any) -> dict[str, Any]:
    return {
        "rank": 1,
        "title": "Split the review projection from its storage",
        "action": "split",
        "mission_capability": "Explain architecture to a new reader.",
        "current_evidence": ["One module reads and renders; both call sites were read."],
        "reference_insight": "A module should hide one decision.",
        "smallest_change": "Move projection into its own module.",
        "expected_benefit": "The storage shape can change without touching rendering.",
        "expected_deletions": [],
        "protected_behavior": ["The rendered payload is byte-identical."],
        "affected_contracts": [],
        "risks": [],
        "counter_evidence": [],
        "reasons_not_to_proceed": [],
        "dependencies": [],
        "verification": ["pytest tests/test_fresh_eyes_payload.py"],
        "reversible": True,
        "confidence": 0.6,
        **extra,
    }


def _plan(**extra: Any) -> dict[str, Any]:
    return {
        "target": "src/anaxigraph/semantic_fresh_eyes_payload.py",
        "preconditions": ["The payload tests pass before the first step."],
        "sequence": ["Extract the projection.", "Point the reader at it."],
        "preserved_behavior": "The rendered payload is byte-identical.",
        "verification_command": "pytest tests/test_fresh_eyes_payload.py",
        "rollback": "git revert the extraction commit.",
        **extra,
    }


def test_a_review_written_before_transformation_existed_is_still_valid():
    Draft202012Validator(_ITEM).validate(_recommendation())


def test_a_plan_without_a_result_is_accepted_and_reports_nothing_verified():
    item = _recommendation(transformation=_plan())

    Draft202012Validator(_ITEM).validate(item)
    assert attributed_verification(item) == "unchecked"


def test_a_result_counts_only_when_a_tool_says_which_revision_it_ran_on():
    named = _recommendation(
        transformation=_plan(result={"status": "passed", "revision": "b6f6a9a", "source": "pytest"})
    )
    unattributed = _recommendation(
        transformation=_plan(result={"status": "passed", "revision": "  ", "source": "pytest"})
    )

    assert attributed_verification(named) == "passed"
    assert attributed_verification(unattributed) == "unchecked"


def test_a_failed_check_is_reported_rather_than_hidden():
    failed = _recommendation(
        transformation=_plan(result={"status": "failed", "revision": "b6f6a9a", "source": "pytest"})
    )

    assert attributed_verification(failed) == "failed"


@pytest.mark.parametrize("recommendation", [{}, {"transformation": None}, _recommendation()])
def test_absent_or_empty_input_never_claims_a_check(recommendation: dict[str, Any]):
    assert attributed_verification(recommendation) == "unchecked"


def test_a_status_the_schema_does_not_allow_is_rejected():
    invented = _recommendation(
        transformation=_plan(result={"status": "looks_fine", "revision": "b6f6a9a", "source": "x"})
    )

    with pytest.raises(Exception):
        Draft202012Validator(_ITEM).validate(invented)


def test_adding_the_block_does_not_invalidate_saved_semantic_work():
    assert semantic_input_hash("fresh-eyes-review-v1", "v1", {"x": 1})[:16] == "2319aced239cd147"
