"""Long calls, rolling queues, and explicit stopping conditions for remote workers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import anaxigraph.semantic_remote_worker as worker
from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_agent_protocol import agent_no_work_status


@pytest.mark.anyio
@pytest.mark.parametrize("maximum", [None, 9])
async def test_remote_slots_refill_while_one_slow_job_stays_running(monkeypatch, maximum):
    count = maximum or 40
    queue = list(range(40))
    started, running, claims = [], set(), []
    last_started = asyncio.Event()
    peak = 0

    async def claim(_session, _target, execution, available, retry_failed):
        claims.append(retry_failed)
        packets = [{"job": {"id": queue.pop(0)}} for _ in range(min(available, len(queue)))]
        return packets, {"status": "complete", "semantic": {"semantically_ready": True}}

    async def execute(_session, _target, execution, packets, total, latest):
        nonlocal peak
        identifier = packets[0]["job"]["id"]
        assert execution.max_parallel_jobs == 1
        running.add(identifier)
        peak = max(peak, len(running))
        started.append(identifier)
        if len(started) == count:
            last_started.set()
        if identifier == 0:
            # A batch barrier deadlocks here: new jobs must start before job zero ends.
            await asyncio.wait_for(last_started.wait(), 5)
        else:
            await asyncio.sleep(0)
        running.remove(identifier)
        total["processed"] += 1
        total["completed"] += 1
        return latest

    monkeypatch.setattr(worker, "_claim_wave", claim)
    monkeypatch.setattr(worker, "_execute_wave", execute)
    total = worker._empty_result()
    await worker._run_queue(
        object(),
        SimpleNamespace(repository_id=1),
        SemanticConfig(max_parallel_jobs=4),
        SemanticConfig(provider="codex", max_parallel_jobs=16),
        maximum,
        True,
        total,
    )
    assert total["completed"] == count
    assert sorted(started) == list(range(count))
    assert peak == 4
    assert claims[0] is True and not any(claims[1:])
    assert len(queue) == 40 - count


@pytest.mark.anyio
async def test_peer_result_is_saved_when_another_submission_fails():
    from anaxigraph.semantic_remote_schedule import drain_available

    saved = []

    async def execute(execution, packets, total, latest):
        if packets[0] == "failed":
            raise RuntimeError("Disconnected during write")
        await asyncio.sleep(0.01)
        saved.append(packets[0])
        return latest

    async def claim(count):
        pytest.fail("A transport failure must be handled before claiming more work")

    with pytest.raises(RuntimeError, match="Disconnected"):
        await drain_available(
            ["failed", "saved"],
            SemanticConfig(max_parallel_jobs=2),
            {"processed": 0},
            {},
            maximum=None,
            claim=claim,
            execute=execute,
        )
    assert saved == ["saved"]


@pytest.mark.anyio
async def test_partial_claim_failure_releases_owned_jobs(monkeypatch):
    released, calls = [], []

    async def call(_session, name, arguments, **kwargs):
        calls.append(arguments["retry_failed"])
        if len(calls) == 2:
            raise RuntimeError("connection lost")
        return {"status": "work", "job": {"id": 1}, "lease": {"token": "owned"}}

    async def release(_session, _target, packet, reason):
        released.append(packet["job"]["id"])

    monkeypatch.setattr(worker, "call_tool_retrying_locks", call)
    monkeypatch.setattr(worker, "_release_packet", release)
    with pytest.raises(RuntimeError, match="connection lost"):
        await worker._claim_wave(
            object(), SimpleNamespace(repository_id=1), SemanticConfig(provider="claude"), 4, True
        )
    assert calls == [True, False]
    assert released == [1]


@pytest.mark.anyio
@pytest.mark.parametrize("terminal", ["scan_required", "complete_with_failures", "paused"])
async def test_reported_blocker_ends_remote_waiting(monkeypatch, terminal):
    async def claim(*args):
        return [], {"status": terminal, "semantic": {"state": terminal}}

    monkeypatch.setattr(worker, "_claim_wave", claim)
    result = await worker._run_queue(
        object(),
        SimpleNamespace(repository_id=1),
        SemanticConfig(),
        SemanticConfig(),
        None,
        False,
        worker._empty_result(),
    )
    assert result["state"] == terminal


@pytest.mark.parametrize("ready", [False, True])
def test_exhausted_file_or_optional_review_is_a_reported_failure(ready):
    assert (
        agent_no_work_status(
            {"semantically_ready": ready, "baseline_complete": ready, "jobs": {"failed": 1}}
        )
        == "complete_with_failures"
    )


@pytest.mark.parametrize(
    "mode,limit,plan_only,expected",
    [
        ("codex", None, False, True),
        ("claude", None, False, True),
        ("command", None, False, True),
        ("codex", 2, False, False),
        ("mcp", None, False, False),
        ("plan_only", None, True, False),
    ],
)
def test_cli_defaults_to_complete_only_when_it_can_execute(mode, limit, plan_only, expected):
    from anaxigraph.cli_semantic_commands import _default_completion

    args = SimpleNamespace(until_complete=None, limit=limit, plan_only=plan_only)
    _default_completion(args, mode)
    assert args.until_complete is expected


@pytest.mark.parametrize("extra,complete", [([], True), (["--limit", "2"], False)])
def test_cli_runs_past_batch_default_unless_a_sample_is_requested(
    repository, database, monkeypatch, capsys, extra, complete
):
    import json

    from test_workflows import prepare

    from anaxigraph.cli import main

    prepare(repository, database, monkeypatch)
    main(
        [
            "understand",
            str(repository),
            "--db",
            str(database.path),
            "--executor",
            "codex",
            "--model",
            "fixture",
            *extra,
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert result["complete"] is complete
    if complete:
        assert result["processed"] > 3  # Repository policy sets max_jobs_per_run=3.
        assert result["semantic"]["semantically_ready"]
    else:
        assert result["processed"] == 2


def test_cli_does_not_report_a_failed_optional_review_as_complete():
    from anaxigraph.cli_semantic_commands import _queue_complete

    assert not _queue_complete({"semantically_ready": True, "jobs": {"failed": 1}})
    assert _queue_complete({"semantically_ready": True, "jobs": {"completed": 40}})
