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


def test_goal_change_keeps_immutable_brief_history_and_survives_resume(repository, database):
    goal = 'Keep retry behavior and "caller consistency" clear without more layers.'
    review = prepared_review(repository, database, goal=goal)
    review.run_until_complete()
    engine, repository_id, config = review.engine, review.repository_id, review.config
    first = engine.fresh_eyes_status(repository_id, config.semantic)
    reference_ids = {item["document_id"] for item in first["stages"]}
    assert first["review_goal"] == goal
    _assert_packets(review.claims, goal)

    review.claims.clear()
    goal2 = "Clarify the user-visible retry and failure contracts."
    engine.start_fresh_eyes_review(repository_id, repository, config, goal=goal2)
    resumed = engine.start_fresh_eyes_review(repository_id, repository, config)
    assert resumed["review"]["review_goal"] == goal2
    assert not resumed["review"]["ready"]
    review.run_until_complete()
    second = engine.fresh_eyes_status(repository_id, config.semantic)
    assert reference_ids.isdisjoint({item["document_id"] for item in second["stages"]})
    assert second["functional_brief"]["revision"] != first["functional_brief"]["revision"]
    assert second["review_generation"] == 2
    assert {item["kind"] for item in review.claims if item["status"] == "work"} == {
        "fresh_comparison",
        "fresh_review",
        "fresh_proposal",
        "fresh_adjudication",
    }
    _assert_packets(review.claims, goal2)

    engine.start_fresh_eyes_review(repository_id, repository, config, restart=True)
    assert engine.fresh_eyes_status(repository_id, config.semantic)["review_goal"] == goal2
    historical = engine.fresh_eyes_status(repository_id, config.semantic, generation=1)
    assert historical["review_goal"] == goal
    with pytest.raises(ValueError, match="4,000"):
        engine.start_fresh_eyes_review(repository_id, repository, config, goal="x" * 4001)


def _assert_packets(claims, goal):
    for item in claims:
        request = item.get("request") or {}
        kind = request.get("analysis_kind")
        if kind and kind.startswith("fresh_"):
            assert "current_system" not in request
            assert "pkg/core.py" not in json.dumps(request)
            assert request["information_boundary"]["mode"] == "implementation_blind"
        if kind == "fresh_adjudication":
            assert goal in request["capability_projection"]["non_functional_requirements"]


@pytest.mark.parametrize("goal", ["", "paths: src/a.py, src/b.py", 'Unicode ☃ and "quotes"'])
def test_goal_plan_token_preserves_existing_control_fields(goal):
    plan = {"interface_hash": fresh_eyes_plan_token(3, 3, ("codex", "claude", "any"), goal=goal)}
    assert fresh_eyes_plan_options(plan) == (3, 3)
    assert fresh_eyes_plan_executors(plan) == ("codex", "claude", "any")
    assert fresh_eyes_plan_goal(plan) == goal


def test_source_specific_goal_is_rejected_before_a_plan_is_saved(repository, database):
    review = prepared_review(repository, database)
    with database.transaction() as connection:
        connection.execute("DELETE FROM semantic_scope_states WHERE scope_type='fresh_eyes'")
        connection.execute("DELETE FROM semantic_jobs WHERE scope_type='fresh_eyes'")
    with pytest.raises(ValueError, match="without source paths"):
        review.engine.start_fresh_eyes_review(
            review.repository_id, repository, review.config, goal="Rewrite pkg/core.py"
        )
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_scope_states WHERE scope_type='fresh_eyes'"
            ).fetchone()[0]
            == 0
        )
