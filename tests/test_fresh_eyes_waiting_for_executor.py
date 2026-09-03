"""Waiting for the other executor, and the way out when it never arrives."""

from __future__ import annotations

import pytest
from fresh_eyes_support import CLAUDE_EXECUTOR, CODEX_EXECUTOR, prepared_review

import anaxigraph.semantic_remote_recovery as remote_recovery
import anaxigraph.semantic_remote_worker as remote_worker
from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_agent_protocol import (
    WAITING_FOR_EXECUTOR,
    waiting_for_executor_message,
)
from anaxigraph.semantic_fresh_eyes_contract import fresh_eyes_plan_executors
from anaxigraph.semantic_service import SemanticServiceTarget

_PLAN_SQL = (
    "SELECT interface_hash FROM semantic_scope_states WHERE scope_type = 'fresh_eyes' "
    "AND scope_key = 'plan' AND snapshot_id = ?"
)


def _target() -> SemanticServiceTarget:
    return SemanticServiceTarget("http://127.0.0.1:8765", 1, "Fixture", "/repo")


def _waiting_reply(message: str = "start claude") -> dict:
    return {
        "status": WAITING_FOR_EXECUTOR,
        "message": message,
        "waiting_for": [{"scope_key": "proposal:b", "required_executor": "claude"}],
        "semantic": {"snapshot_id": 7, "jobs": {"pending": 1}},
    }


def _plan_token(database, repository_id: int) -> str:
    snapshot_id = int(database.latest_snapshot(repository_id)["id"])
    with database.connect() as connection:
        return str(connection.execute(_PLAN_SQL, (snapshot_id,)).fetchone()["interface_hash"])


def test_the_waiting_message_names_the_reserved_work_and_the_command_to_run():
    message = waiting_for_executor_message(
        "/repos/anaxigraph",
        [{"scope_key": "proposal:b", "required_executor": "claude"}],
    )

    assert "proposal:b" in message
    assert "anaxigraph understand /repos/anaxigraph --executor claude --until-complete" in message


def test_a_worker_is_told_to_wait_for_the_pinned_peer_instead_of_complete(repository, database):
    review = prepared_review(
        repository, database, proposal_count=2, proposal_executors=("codex", "claude")
    )
    codex = review.claim(CODEX_EXECUTOR)
    assert codex["job"]["scope_key"] == "proposal:a"
    review.submit(codex)

    blocked = review.claim(CODEX_EXECUTOR)

    assert blocked["status"] == WAITING_FOR_EXECUTOR
    assert blocked["waiting_for"] == [{"scope_key": "proposal:b", "required_executor": "claude"}]
    assert "--executor claude --until-complete" in blocked["message"]
    assert blocked["status"] not in remote_worker._TERMINAL_STATES
    assert blocked["semantic"]["semantically_ready"] is True
    claude = review.claim(CLAUDE_EXECUTOR)
    assert claude["job"]["scope_key"] == "proposal:b"
    review.submit(claude)
    assert [kind for _, kind in review.run_until_complete()] == [
        "fresh_adjudication",
        "fresh_comparison",
        "fresh_review",
    ]


def test_the_review_next_action_names_the_executor_that_has_not_started(repository, database):
    review = prepared_review(
        repository, database, proposal_count=2, proposal_executors=("codex", "claude")
    )
    review.submit(review.claim(CODEX_EXECUTOR))

    status = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)

    assert status["state"] == "in_progress"
    assert "--executor claude" in status["next_action"]
    assert "independent proposal b" in status["next_action"]


def test_unpinning_lets_any_executor_finish_a_half_pinned_review(repository, database):
    review = prepared_review(
        repository, database, proposal_count=2, proposal_executors=("codex", "claude")
    )
    review.submit(review.claim(CODEX_EXECUTOR))
    assert _plan_token(database, review.repository_id) == "2:1:codex,claude"

    released = review.engine.unpin_fresh_eyes_executors(
        review.repository_id, review.config.semantic
    )

    assert released["status"] == "unpinned"
    assert released["unpinned"] == [{"scope_key": "proposal:b", "required_executor": "claude"}]
    assert _plan_token(database, review.repository_id) == "2:1"
    assert fresh_eyes_plan_executors({"interface_hash": "2:1"}) == ()
    assert [item["required_executor"] for item in released["review"]["stages"][:2]] == [None, None]
    assert "--executor" not in released["review"]["next_action"]
    codex = review.claim(CODEX_EXECUTOR)
    assert codex["job"]["scope_key"] == "proposal:b"
    review.submit(codex)
    assert [kind for _, kind in review.run_until_complete()] == [
        "fresh_adjudication",
        "fresh_comparison",
        "fresh_review",
    ]


def test_unpinning_an_unpinned_review_changes_nothing(repository, database):
    review = prepared_review(repository, database, proposal_count=2)

    released = review.engine.unpin_fresh_eyes_executors(
        review.repository_id, review.config.semantic
    )

    assert released["status"] == "not_pinned"
    assert released["unpinned"] == []
    assert _plan_token(database, review.repository_id) == "2:1"


@pytest.mark.anyio
async def test_a_queue_waiting_for_another_executor_is_never_stranded():
    semantic = {"snapshot_id": 7, "jobs": {"pending": 1}}
    recovery = remote_recovery.IdleRecovery(_target(), retry_failed=False)

    assert remote_recovery._stranded_queue(WAITING_FOR_EXECUTOR, semantic) is False
    for _ in range(5):
        assert await recovery.recover(WAITING_FOR_EXECUTOR, semantic) is None


@pytest.mark.anyio
async def test_a_bounded_run_still_stops_when_no_packet_is_claimed():
    recovery = remote_recovery.IdleRecovery(_target(), retry_failed=False)

    stop, latest = await remote_worker._wait_or_recover(
        recovery, _waiting_reply(), {"jobs": {}}, 5, remote_worker._empty_result()
    )

    assert stop is True
    assert latest == {"jobs": {}}


@pytest.mark.anyio
async def test_until_complete_keeps_polling_and_names_the_missing_executor_once(
    monkeypatch, capsys
):
    waiting = _waiting_reply("Start it with: anaxigraph understand . --executor claude")
    claims = iter(
        [
            ([], waiting),
            ([], waiting),
            ([{"job": {"kind": "fresh_proposal"}}], None),
            ([], {"status": "complete", "semantic": {"semantically_ready": True}}),
        ]
    )
    sleeps: list[float] = []

    async def claim(*_args):
        return next(claims)

    async def execute(_session, _target, _execution, _packets, total, _latest):
        total["processed"] += 1
        return {"snapshot_id": 7, "jobs": {}}

    async def sleep(seconds):
        sleeps.append(seconds)

    def refuse(*_args, **_kwargs):
        raise AssertionError("a queue waiting for a peer executor must not be re-prepared")

    monkeypatch.setattr(remote_worker, "_claim_wave", claim)
    monkeypatch.setattr(remote_worker, "_execute_wave", execute)
    monkeypatch.setattr(remote_recovery, "prepare_semantic_service", refuse)
    monkeypatch.setattr(remote_worker.asyncio, "sleep", sleep)
    total = remote_worker._empty_result()

    semantic = await remote_worker._run_queue(
        object(),
        _target(),
        SemanticConfig(max_parallel_jobs=1),
        SemanticConfig(provider="codex"),
        None,
        False,
        total,
    )

    assert sleeps == [2, 2]
    assert total["processed"] == 1
    assert semantic["semantically_ready"] is True
    assert capsys.readouterr().err.count("--executor claude") == 1
