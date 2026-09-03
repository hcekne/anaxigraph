from __future__ import annotations

import json
from typing import Any

from anaxigraph.semantic_fresh_eyes_consensus import (
    ALIGNMENT_CAVEATS,
    FRESH_EYES_ALIGNMENT_VERSION,
    align_reviews,
    compare_generations,
)


def _recommendation(
    rank: int,
    title: str,
    action: str,
    capability: str,
    *,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "rank": rank,
        "title": title,
        "action": action,
        "mission_capability": capability,
        "affected_contracts": [],
        "current_evidence": evidence or [],
        "expected_deletions": [],
    }


def _review(
    recommendations: list[dict[str, Any]], rejected: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "contract_version": "fresh-eyes-review-v1",
        "recommendations": recommendations,
        "rejected_ideas": rejected,
        "confidence": 0.7,
    }


def _left() -> dict[str, Any]:
    return _review(
        [
            _recommendation(
                1,
                "Consolidate duplicate orchestration",
                "consolidate",
                "Durable reasoning",
                evidence=["src/anaxigraph/semantic_runner.py:12"],
            ),
            _recommendation(2, "Bound the working tree drift window", "move", "Operational trust"),
            _recommendation(3, "Split saved read repair", "split", "Snapshot projection"),
        ],
        [],
    )


def _right() -> dict[str, Any]:
    return _review(
        [
            _recommendation(
                1,
                "Consolidate the duplicate orchestration branch",
                "consolidate",
                "Bounded queue",
                evidence=["semantic_runner.py:40"],
            ),
            _recommendation(2, "Give each saved read its own prepared view", "delete", "Isolation"),
            _recommendation(3, "Split saved read repair", "refactor", "Snapshot projection"),
        ],
        [],
    )


def _titles(entries: list[dict[str, Any]]) -> list[str]:
    return [item["title"] for item in entries]


def test_aligned_conflicting_and_unmatched_labels_are_deterministic():
    result = align_reviews(_left(), _right())

    assert result["contract_version"] == FRESH_EYES_ALIGNMENT_VERSION
    assert result["method"] == "lexical"
    assert len(result["aligned"]) == 1
    aligned = result["aligned"][0]
    assert aligned["left"]["title"] == "Consolidate duplicate orchestration"
    assert aligned["right"]["title"] == "Consolidate the duplicate orchestration branch"
    assert 0.0 <= aligned["score"] <= 1.0
    assert aligned["signals"]["shared_terms"] == ["consolidate", "duplicate", "orchestration"]
    assert aligned["signals"]["shared_paths"] == ["semantic_runner.py"]
    assert aligned["signals"]["same_action"] is True
    assert _titles(result["unmatched_left"]) == ["Bound the working tree drift window"]
    assert _titles(result["unmatched_right"]) == ["Give each saved read its own prepared view"]
    assert {item["label"] for item in result["pairs"]} <= {"aligned", "conflicting", "candidate"}
    assert json.dumps(align_reviews(_left(), _right()), sort_keys=True) == json.dumps(
        result, sort_keys=True
    )


def test_a_shared_target_with_two_actions_is_conflicting_and_never_aligned():
    result = align_reviews(_left(), _right())

    conflicts = [item for item in result["conflicting"] if item["kind"] == "action_conflict"]
    assert len(conflicts) == 1
    assert conflicts[0]["left"]["action"] == "split"
    assert conflicts[0]["right"]["action"] == "refactor"
    assert "split versus refactor" in conflicts[0]["detail"]
    assert "Split saved read repair" not in _titles([item["left"] for item in result["aligned"]])
    assert "Split saved read repair" not in _titles(result["unmatched_left"])
    assert result["facts"]["conflicting"] == 1
    assert result["facts"]["left"]["actions"] == {"consolidate": 1, "move": 1, "split": 1}


def test_rejected_idea_matching_a_recommendation_is_conflicting():
    idea = {
        "idea": "Add a general workflow engine to run every reasoning stage",
        "reason": "The fixed sequence does not justify one.",
        "evidence": [],
    }
    left = _review(
        [_recommendation(1, "Keep the fixed recipe", "retain", "Bounded review")], [idea]
    )
    right = _review(
        [
            _recommendation(
                1,
                "Add a general workflow engine",
                "split",
                "Run every reasoning stage on one durable engine",
            )
        ],
        [],
    )

    result = align_reviews(left, right)

    assert result["aligned"] == []
    assert len(result["conflicting"]) == 1
    conflict = result["conflicting"][0]
    assert conflict["kind"] == "rejected_vs_recommended"
    assert conflict["left"]["kind"] == "rejected_idea"
    assert conflict["right"]["kind"] == "recommendation"
    assert "the left generation rejected this idea" in conflict["detail"].lower()
    assert result["unmatched_right"] == []
    assert _titles(result["unmatched_left"]) == ["Keep the fixed recipe"]
    assert result["facts"]["rejected_vs_recommended"] == 1


def test_alignment_is_symmetric_and_fingerprinted():
    left = _left()
    right = _right()
    right["rejected_ideas"] = [
        {"idea": "Bound the working tree drift window", "reason": "Already bounded", "evidence": []}
    ]

    result = align_reviews(left, right)
    swapped = align_reviews(right, left)

    assert swapped["unmatched_left"] == result["unmatched_right"]
    assert swapped["unmatched_right"] == result["unmatched_left"]
    assert {item["kind"] for item in swapped["conflicting"]} == {
        item["kind"] for item in result["conflicting"]
    }
    assert result["fingerprint"] == align_reviews(_left(), right)["fingerprint"]
    assert result["fingerprint"] != align_reviews(left, _right())["fingerprint"]
    assert len(result["fingerprint"]) == 64


def test_every_alignment_states_that_lexical_matching_is_not_agreement():
    result = align_reviews(None, None)

    assert result["caveats"] == list(ALIGNMENT_CAVEATS)
    assert any("lexical" in caveat for caveat in result["caveats"])
    assert any(
        "different words" in caveat and "not evidence" in caveat for caveat in result["caveats"]
    )
    assert result["pairs"] == []
    assert result["facts"]["left"] == {
        "recommendations": 0,
        "rejected_ideas": 0,
        "actions": {},
        "confidence": None,
    }
    assert result["facts"]["shared_paths"] == []


def test_compare_generations_names_both_sides_and_flags_a_self_comparison():
    payload = {
        "review_generation": 2,
        "snapshot_id": 7,
        "state": "superseded",
        "strategy": _left(),
    }
    other = {
        "review_generation": 3,
        "snapshot_id": 7,
        "state": "current",
        "strategy": _right(),
    }

    comparison = compare_generations(payload, other)

    assert comparison["left"] == {
        "review_generation": 2,
        "snapshot_id": 7,
        "state": "superseded",
        "recommendation_count": 3,
        "rejected_idea_count": 0,
        "confidence": 0.7,
    }
    assert comparison["right"]["review_generation"] == 3
    assert comparison["method"] == "lexical"
    assert len(comparison["aligned"]) == 1
    assert comparison["caveats"] == list(ALIGNMENT_CAVEATS)

    self_comparison = compare_generations(payload, payload)

    assert self_comparison["caveats"][-1].startswith("Both sides name the same recorded generation")
    assert len(self_comparison["aligned"]) == 3
