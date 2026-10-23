"""Per-slot executor pinning for one fresh-eyes review."""

from __future__ import annotations

import json

import pytest
from fresh_eyes_support import CLAUDE_EXECUTOR, CODEX_EXECUTOR, baseline_review

from anaxigraph.cli import main
from anaxigraph.semantic_fresh_eyes_contract import (
    fresh_eyes_plan_executors,
    fresh_eyes_plan_options,
    fresh_eyes_plan_token,
    fresh_eyes_required_executor,
    parse_proposal_executors,
)
from anaxigraph.semantic_fresh_eyes_functional import semantic_input_hash

_PLAN_SQL = (
    "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = 'fresh_eyes' "
    "AND scope_key = 'plan'"
)
_PROPOSAL_JOBS_SQL = (
    "SELECT scope_key, metadata_json, input_hash FROM semantic_jobs "
    "WHERE job_kind = 'fresh_proposal' AND snapshot_id = ? AND status IN ('pending', 'retry') "
    "ORDER BY scope_key"
)


def _plan_row(database, snapshot_id: int) -> dict:
    with database.connect() as connection:
        return dict(connection.execute(_PLAN_SQL, (snapshot_id,)).fetchone())


def _proposal_jobs(database, snapshot_id: int) -> list[dict]:
    with database.connect() as connection:
        return [dict(row) for row in connection.execute(_PROPOSAL_JOBS_SQL, (snapshot_id,))]


def _snapshot_id(database, repository_id: int) -> int:
    return int(database.latest_snapshot(repository_id)["id"])


def test_plan_token_records_executors_and_still_reads_two_part_tokens():
    assert fresh_eyes_plan_token(3, 3) == "functional-v2|3:3"
    assert fresh_eyes_plan_token(2, 3, functional=False) == "2:3"
    assert fresh_eyes_plan_token(2, 3, ("codex", "claude"), functional=False) == "2:3:codex,claude"
    pinned = {"interface_hash": "2:3:codex,claude"}

    assert fresh_eyes_plan_options(pinned) == (2, 3)
    assert fresh_eyes_plan_executors(pinned) == ("codex", "claude")
    assert fresh_eyes_plan_options({"interface_hash": "2:3"}) == (2, 3)
    assert fresh_eyes_plan_executors({"interface_hash": "2:3"}) == ()
    assert fresh_eyes_plan_options({"interface_hash": "3"}) == (3, 1)
    assert fresh_eyes_plan_options({"interface_hash": None}) == (3, 1)
    assert fresh_eyes_plan_options({"interface_hash": "two:one"}) == (2, 1)


def test_required_executor_names_one_slot_and_treats_any_as_unpinned():
    executors = ("codex", "any", "claude")

    assert fresh_eyes_required_executor(executors, "proposal:a") == "codex"
    assert fresh_eyes_required_executor(executors, "proposal:b") is None
    assert fresh_eyes_required_executor(executors, "proposal:c") == "claude"
    assert fresh_eyes_required_executor(executors, "functional:product:proposal:c") == "claude"
    assert fresh_eyes_required_executor(executors, "adjudication") is None
    assert fresh_eyes_required_executor((), "proposal:a") is None
    assert fresh_eyes_required_executor(executors, "proposal:") is None


def test_proposal_executors_are_parsed_from_a_string_or_a_list():
    assert parse_proposal_executors("codex, Claude") == ("codex", "claude")
    assert parse_proposal_executors(["codex", "claude"]) == ("codex", "claude")
    assert parse_proposal_executors("") == ()
    assert parse_proposal_executors(None) == ()


def test_pinned_start_records_executors_per_slot_without_changing_stage_freshness(
    repository, database
):
    review = baseline_review(repository, database)
    snapshot_id = _snapshot_id(database, review.repository_id)

    started = review.engine.start_fresh_eyes_review(
        review.repository_id,
        review.repository,
        review.config,
        proposal_count=2,
        proposal_executors=("codex", "claude"),
    )

    assert started["status"] == "started"
    plan = _plan_row(database, snapshot_id)
    assert plan["interface_hash"] == "functional-v2|3:1:codex,claude,any"
    assert fresh_eyes_plan_options(plan) == (3, 1)
    assert fresh_eyes_plan_executors(plan) == ("codex", "claude", "any")
    _finish_hierarchy(review)
    jobs = _proposal_jobs(database, snapshot_id)
    assert [job["scope_key"] for job in jobs] == [
        f"functional:product:proposal:{slot}" for slot in "abc"
    ]
    pins = [_metadata(job).get("required_executor") for job in jobs]
    assert pins == ["codex", "claude", None]
    assert "required_executor" not in _metadata(jobs[0])["input_manifest"]
    result = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    stages = {item["key"]: item["required_executor"] for item in result["stages"]}
    assert stages == {
        "functional:product:proposal:a": "codex",
        "functional:product:proposal:b": "claude",
        "functional:product:proposal:c": None,
        "functional:brief": None,
    }
    assert [job["input_hash"] for job in jobs] == _unpinned_input_hashes(
        database, snapshot_id, review.config.semantic.prompt_version
    )


def _metadata(job: dict) -> dict:
    return json.loads(job["metadata_json"])


def _finish_hierarchy(review):
    packet = review.claim(CODEX_EXECUTOR)
    assert packet["job"]["kind"] == "fresh_adjudication"
    review.submit(packet)
    review.engine.plan(review.repository_id, review.repository, review.config)


def _unpinned_input_hashes(database, snapshot_id: int, prompt_version: str) -> list[str]:
    """Recompute each proposal identity from the manifest an unpinned plan would build."""

    return [
        semantic_input_hash(
            "functional-proposal-v2",
            prompt_version,
            _metadata(job)["input_manifest"],
        )
        for job in _proposal_jobs(database, snapshot_id)
    ]


@pytest.mark.parametrize(
    ("executors", "message"),
    [
        (("codex",), "one proposal executor per slot"),
        (("codex", "claude", "codex", "claude"), "one proposal executor per slot"),
        (("codex", "gemini"), "must each be one of"),
        (("codex", "auto"), "must each be one of"),
        (("codex", "mcp"), "must each be one of"),
    ],
)
def test_an_unusable_executor_assignment_fails_before_any_job_is_queued(
    repository, database, executors, message
):
    review = baseline_review(repository, database)
    snapshot_id = _snapshot_id(database, review.repository_id)

    with pytest.raises(ValueError, match=message):
        review.engine.start_fresh_eyes_review(
            review.repository_id,
            review.repository,
            review.config,
            proposal_count=2,
            proposal_executors=executors,
        )

    with database.connect() as connection:
        assert connection.execute(_PLAN_SQL, (snapshot_id,)).fetchone() is None
    assert _proposal_jobs(database, snapshot_id) == []


def test_a_restarted_generation_can_be_pinned_while_an_unpinned_review_stays_unpinned(
    repository, database
):
    review = baseline_review(repository, database)
    review.engine.start_fresh_eyes_review(
        review.repository_id, review.repository, review.config, proposal_count=2
    )
    snapshot_id = _snapshot_id(database, review.repository_id)
    assert fresh_eyes_plan_executors(_plan_row(database, snapshot_id)) == ()
    review.run_until_complete()

    restarted = review.engine.start_fresh_eyes_review(
        review.repository_id,
        review.repository,
        review.config,
        restart=True,
        proposal_count=2,
        proposal_executors=("claude", "codex"),
    )

    assert restarted["status"] == "restarted"
    plan = _plan_row(database, snapshot_id)
    assert plan["interface_hash"] == "functional-v2|3:2:claude,codex,any"
    _finish_hierarchy(review)
    result = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    assert [
        item["required_executor"] for item in result["stages"] if ":proposal:" in item["key"]
    ] == ["claude", "codex", None]
    pins = [
        _metadata(job).get("required_executor") for job in _proposal_jobs(database, snapshot_id)
    ]
    assert pins == ["claude", "codex", None]


def test_starting_an_active_review_again_keeps_the_recorded_assignment(repository, database):
    review = baseline_review(repository, database)
    review.engine.start_fresh_eyes_review(
        review.repository_id,
        review.repository,
        review.config,
        proposal_count=2,
        proposal_executors=("codex", "claude"),
    )
    snapshot_id = _snapshot_id(database, review.repository_id)

    again = review.engine.start_fresh_eyes_review(
        review.repository_id,
        review.repository,
        review.config,
        proposal_count=2,
        proposal_executors=("claude", "codex"),
    )

    assert again["status"] == "already_started"
    assert (
        _plan_row(database, snapshot_id)["interface_hash"] == "functional-v2|3:1:codex,claude,any"
    )


def test_a_pinned_review_reports_the_executor_that_produced_each_proposal(repository, database):
    review = baseline_review(repository, database)
    review.engine.start_fresh_eyes_review(
        review.repository_id,
        review.repository,
        review.config,
        proposal_count=2,
        proposal_executors=("codex", "claude"),
    )

    review.run_until_complete()

    result = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    assert result["state"] == "current"
    proposals = [item for item in result["stages"] if ":proposal:" in item["key"]]
    assert [item["required_executor"] for item in proposals[:3]] == ["codex", "claude", None]
    assert {item["provenance"]["executor_id"] for item in proposals} == {
        CODEX_EXECUTOR,
        CLAUDE_EXECUTOR,
    }


def test_cli_start_pins_each_proposal_slot_on_the_local_index(repository, database, capsys):
    review = baseline_review(repository, database)
    snapshot_id = _snapshot_id(database, review.repository_id)

    main(
        [
            "fresh-eyes",
            str(repository),
            "--db",
            str(database.path),
            "--start",
            "--proposals",
            "3",
            "--proposal-executors",
            "codex,claude,any",
            "--json",
        ]
    )

    started = json.loads(capsys.readouterr().out)
    assert started["status"] == "started"
    assert (
        _plan_row(database, snapshot_id)["interface_hash"] == "functional-v2|3:1:codex,claude,any"
    )
