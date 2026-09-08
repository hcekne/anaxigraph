"""Review goals are durable, bounded, and never leak implementation into blind stages."""

import json

import pytest
from fresh_eyes_support import prepared_review

from anaxigraph.semantic_fresh_eyes_contract import (
    fresh_eyes_plan_executors,
    fresh_eyes_plan_goal,
    fresh_eyes_plan_options,
    fresh_eyes_plan_token,
)


def test_goal_change_reuses_blind_stages_and_survives_resume(repository, database):
    goal = 'Improve pkg/core.py: ownership and "caller consistency" — without more layers.'
    review = prepared_review(repository, database, goal=goal)
    review.run_until_complete()
    engine, repository_id, config = review.engine, review.repository_id, review.config
    first = engine.fresh_eyes_status(repository_id, config.semantic)
    reference_ids = [item["document_id"] for item in first["stages"][:3]]
    assert first["review_goal"] == goal
    _assert_packets(review.claims, goal)

    review.claims.clear()
    goal2 = "Clarify the user-visible retry and failure contracts in pkg/core.py."
    engine.start_fresh_eyes_review(repository_id, repository, config, goal=goal2)
    resumed = engine.start_fresh_eyes_review(repository_id, repository, config)
    assert resumed["review"]["review_goal"] == goal2
    assert not resumed["review"]["ready"]
    review.run_until_complete()
    second = engine.fresh_eyes_status(repository_id, config.semantic)
    assert [item["document_id"] for item in second["stages"][:3]] == reference_ids
    assert second["fingerprints"]["comparison"] != first["fingerprints"]["comparison"]
    assert {item["kind"] for item in review.claims if item["status"] == "work"} == {
        "fresh_comparison",
        "fresh_review",
    }
    _assert_packets(review.claims, goal2)

    engine.start_fresh_eyes_review(repository_id, repository, config, restart=True)
    assert engine.fresh_eyes_status(repository_id, config.semantic)["review_goal"] == goal2
    historical = engine.fresh_eyes_status(repository_id, config.semantic, generation=1)
    assert historical["review_goal"] == goal2
    with pytest.raises(ValueError, match="4,000"):
        engine.start_fresh_eyes_review(repository_id, repository, config, goal="x" * 4001)


def _assert_packets(claims, goal):
    for item in claims:
        request = item.get("request") or {}
        kind = request.get("analysis_kind")
        if kind in {"fresh_proposal", "fresh_adjudication"}:
            assert "review_goal" not in json.dumps(request)
            assert goal not in json.dumps(request, ensure_ascii=False)
        elif kind in {"fresh_comparison", "fresh_review"}:
            assert request["review_goal"] == goal
            assert request["input_manifest"]["review_goal"]["text"] == goal


@pytest.mark.parametrize("goal", ["", "paths: src/a.py, src/b.py", 'Unicode ☃ and "quotes"'])
def test_goal_plan_token_preserves_existing_control_fields(goal):
    plan = {"interface_hash": fresh_eyes_plan_token(2, 3, ("codex", "claude"), goal=goal)}
    assert fresh_eyes_plan_options(plan) == (2, 3)
    assert fresh_eyes_plan_executors(plan) == ("codex", "claude")
    assert fresh_eyes_plan_goal(plan) == goal
