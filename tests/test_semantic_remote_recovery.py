"""Durable recovery contracts for an until-complete remote semantic worker."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

import anaxigraph.semantic_remote_calls as remote_calls
import anaxigraph.semantic_remote_payloads as remote_payloads
import anaxigraph.semantic_remote_recovery as remote_recovery
import anaxigraph.semantic_remote_worker as remote_worker
from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_contract import SemanticAnalysisError, SemanticResult
from anaxigraph.semantic_service import SemanticServiceTarget


@pytest.mark.anyio
async def test_until_complete_prepares_a_stranded_queue_and_resumes(monkeypatch):
    waiting = {
        "status": "waiting",
        "semantic": {"snapshot_id": 7, "pending": 3, "jobs": {}},
    }
    claims = iter(
        [
            ([], waiting),
            ([], waiting),
            ([], waiting),
            ([{"job": {"kind": "intrinsic"}}], None),
            ([], {"status": "complete", "semantic": {"semantically_ready": True}}),
        ]
    )
    sleeps = []
    preparations = []

    async def claim(*_args):
        return next(claims)

    async def execute(_session, _target, _execution, _packets, total, _latest):
        total["processed"] += 1
        total["completed"] += 1
        return {"snapshot_id": 8, "jobs": {}}

    async def sleep(seconds):
        sleeps.append(seconds)

    def prepare(target, *, force, retry_failed):
        preparations.append((target.repository_id, force, retry_failed))
        return {"enqueued": 1, "semantic": {"snapshot_id": 8, "jobs": {"pending": 1}}}

    monkeypatch.setattr(remote_worker, "_claim_wave", claim)
    monkeypatch.setattr(remote_worker, "_execute_wave", execute)
    monkeypatch.setattr(remote_recovery, "prepare_semantic_service", prepare)
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

    assert preparations == [(1, False, False)]
    assert sleeps == [2, 2]
    assert total["planned"] == 1
    assert total["processed"] == 1
    assert semantic["semantically_ready"] is True


@pytest.mark.anyio
async def test_recovery_rejects_a_snapshot_that_remains_stranded(monkeypatch):
    recovery = remote_recovery.IdleRecovery(_target(), retry_failed=False)
    semantic = {"snapshot_id": 7, "pending": 3, "jobs": {}}
    monkeypatch.setattr(
        remote_recovery,
        "prepare_semantic_service",
        lambda *_args, **_kwargs: {"semantic": semantic},
    )

    assert await recovery.recover("waiting", semantic) is None
    assert await recovery.recover("waiting", semantic) is None
    assert await recovery.recover("waiting", semantic) is not None
    assert await recovery.recover("waiting", semantic) is None
    assert await recovery.recover("waiting", semantic) is None
    with pytest.raises(RuntimeError, match="after a synchronous prepare"):
        await recovery.recover("waiting", semantic)


@pytest.mark.anyio
async def test_wave_shares_parallel_budget_and_submits_fast_jobs_first(monkeypatch):
    barrier = threading.Barrier(3)
    budgets = []
    submitted = []
    packets = [
        {"job": {"id": index, "kind": "context"}, "lease": {"token": str(index)}}
        for index in range(1, 4)
    ]

    async def request(_session, _target, packet):
        return {"index": packet["job"]["id"]}

    def analyze(request_value, execution):
        budgets.append(execution.max_parallel_jobs)
        barrier.wait(timeout=1)
        time.sleep((4 - request_value["index"]) * 0.01)
        return SimpleNamespace(value={}, input_tokens=1, output_tokens=1)

    async def submit(_session, _target, packet, _result):
        submitted.append(packet["job"]["id"])
        return {"status": "completed", "semantic": {"jobs": {}}}

    monkeypatch.setattr(remote_worker, "_request_for_packet", request)
    monkeypatch.setattr(remote_worker, "_analyze", analyze)
    monkeypatch.setattr(remote_worker, "_submit", submit)
    total = remote_worker._empty_result()

    await remote_worker._execute_wave(
        object(),
        _target(),
        SemanticConfig(provider="codex", max_parallel_jobs=9),
        packets,
        total,
        {},
    )

    assert budgets == [3, 3, 3]
    assert submitted == [3, 2, 1]
    assert total["processed"] == total["completed"] == 3


@pytest.mark.anyio
async def test_wave_runs_thirty_model_calls_without_the_default_thread_cap(monkeypatch):
    barrier = threading.Barrier(30)
    packets = [
        {"job": {"id": index, "kind": "intrinsic"}, "lease": {"token": str(index)}}
        for index in range(30)
    ]

    async def request(_session, _target, packet):
        return {"index": packet["job"]["id"]}

    def analyze(request_value, execution):
        assert execution.max_parallel_jobs == 1
        barrier.wait(timeout=2)
        return SimpleNamespace(
            value={"index": request_value["index"]}, input_tokens=1, output_tokens=1
        )

    async def submit(_session, _target, _packet, _result):
        return {"status": "completed", "semantic": {"jobs": {}}}

    monkeypatch.setattr(remote_worker, "_request_for_packet", request)
    monkeypatch.setattr(remote_worker, "_analyze", analyze)
    monkeypatch.setattr(remote_worker, "_submit", submit)
    total = remote_worker._empty_result()

    await remote_worker._execute_wave(
        object(),
        _target(),
        SemanticConfig(provider="codex", max_parallel_jobs=30),
        packets,
        total,
        {},
    )

    assert total["processed"] == total["completed"] == 30


@pytest.mark.anyio
async def test_one_model_failure_does_not_unwind_successful_peer_jobs(monkeypatch):
    packets = [
        {"job": {"id": index, "kind": "context"}, "lease": {"token": str(index)}}
        for index in range(1, 4)
    ]
    submitted = []
    failures = []

    async def request(_session, _target, packet):
        return {"index": packet["job"]["id"]}

    def analyze(request_value, _execution):
        if request_value["index"] == 2:
            raise SemanticAnalysisError("invalid JSON", input_tokens=120, output_tokens=30)
        return SimpleNamespace(value={}, input_tokens=1, output_tokens=1)

    async def submit(_session, _target, packet, _result):
        submitted.append(packet["job"]["id"])
        return {"status": "completed", "semantic": {"jobs": {}}}

    async def fail(_session, _target, packet, error):
        failures.append((packet["job"]["id"], error.input_tokens, error.output_tokens))
        return {"status": "retry", "semantic": {"jobs": {"retry": 1}}}

    monkeypatch.setattr(remote_worker, "_request_for_packet", request)
    monkeypatch.setattr(remote_worker, "_analyze", analyze)
    monkeypatch.setattr(remote_worker, "_submit", submit)
    monkeypatch.setattr(remote_worker, "_fail_packet", fail)
    total = remote_worker._empty_result()

    await remote_worker._execute_wave(
        object(),
        _target(),
        SemanticConfig(provider="codex", max_parallel_jobs=3),
        packets,
        total,
        {},
    )

    assert sorted(submitted) == [1, 3]
    assert failures == [(2, 120, 30)]
    assert total["processed"] == 3
    assert total["completed"] == 2
    assert total["retry"] == 1


_WRITE_BACK_PACKET = {"job": {"id": 7, "kind": "intrinsic"}, "lease": {"token": "lease"}}
_MODEL_RESULT = SimpleNamespace(value={"summary": "done"}, input_tokens=10, output_tokens=5)


def _error_response(text):
    return SimpleNamespace(
        isError=True, content=[SimpleNamespace(text=text)], structuredContent=None
    )


def _success_response(value):
    return SimpleNamespace(isError=False, content=[], structuredContent=value)


class _RecordingSession:
    def __init__(self, *responses):
        self._responses = iter(responses)
        self.calls = []

    async def call_tool(self, name, *, arguments, read_timeout_seconds):
        self.calls.append(name)
        return next(self._responses)


async def _claim(session):
    execution = SemanticConfig(provider="codex")
    return await remote_worker._claim_wave(session, _target(), execution, 1, False)


async def _submit(session):
    return await remote_worker._submit(session, _target(), _WRITE_BACK_PACKET, _MODEL_RESULT)


async def _fail(session):
    error = RuntimeError("model broke")
    return await remote_worker._fail_packet(session, _target(), _WRITE_BACK_PACKET, error)


async def _release(session):
    return await remote_worker._release_packet(
        session, _target(), _WRITE_BACK_PACKET, "peer submit failed"
    )


_WORK_PACKET = {"status": "work", "job": {"id": 7}}
_WRITE_BACKS = {
    "ANAXIGRAPH_SEMANTIC_WORK": (_claim, _WORK_PACKET, ([_WORK_PACKET], None)),
    "ANAXIGRAPH_SEMANTIC_SUBMIT": (_submit, {"status": "completed"}, {"status": "completed"}),
    "ANAXIGRAPH_SEMANTIC_FAIL": (_fail, {"status": "retry"}, {"status": "retry"}),
    "ANAXIGRAPH_SEMANTIC_RELEASE": (_release, {"status": "released"}, None),
}


@pytest.mark.anyio
@pytest.mark.parametrize("tool", sorted(_WRITE_BACKS))
async def test_every_write_back_retries_transient_sidecar_writer_contention(monkeypatch, tool):
    call, value, expected = _WRITE_BACKS[tool]
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(remote_calls.asyncio, "sleep", sleep)
    session = _RecordingSession(_error_response("database is locked"), _success_response(value))

    assert await call(session) == expected
    assert session.calls == [tool, tool]
    assert sleeps == [1]


@pytest.mark.anyio
@pytest.mark.parametrize("tool", sorted(_WRITE_BACKS))
async def test_non_lock_tool_errors_are_not_retried(monkeypatch, tool):
    call, _value, _expected = _WRITE_BACKS[tool]
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(remote_calls.asyncio, "sleep", sleep)
    session = _RecordingSession(_error_response("lease expired"))

    with pytest.raises(RuntimeError, match="lease expired"):
        await call(session)

    assert session.calls == [tool]
    assert sleeps == []


def _target() -> SemanticServiceTarget:
    return SemanticServiceTarget("http://127.0.0.1:8765", 1, "AnaxiGraph", "/anaxigraph")


@pytest.mark.anyio
async def test_evidence_timeout_attempts_to_release_the_leased_packet(monkeypatch):
    calls = []

    class Session:
        async def call_tool(self, name, *, arguments, read_timeout_seconds):
            calls.append((name, arguments, read_timeout_seconds))
            if name == "ANAXIGRAPH_SEMANTIC_EVIDENCE":
                await asyncio.Event().wait()
            return SimpleNamespace(isError=False, content=[], structuredContent={})

    packet = {
        "job": {"id": 7},
        "lease": {"token": "lease"},
        "analysis_request": {},
        "evidence_manifest": {"page_count": 1},
    }
    monkeypatch.setattr(remote_calls, "MCP_TOOL_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(RuntimeError, match="evidence read failed"):
        await remote_worker._wave_requests(Session(), _target(), [packet])

    assert [name for name, *_ in calls] == [
        "ANAXIGRAPH_SEMANTIC_EVIDENCE",
        "ANAXIGRAPH_SEMANTIC_RELEASE",
    ]


def test_host_executor_payloads_carry_effort_and_only_reported_usage():
    packet = {"job": {"id": 7}, "lease": {"token": "lease-token"}}
    execution = SemanticConfig(provider="claude", model="claude-test", reasoning_effort="medium")

    claim = remote_payloads.claim_arguments(
        3,
        provider=execution.provider,
        model=execution.model,
        effort=execution.reasoning_effort,
        retry_failed=True,
    )

    assert claim["agent_id"].startswith("cli:claude:")
    assert claim["agent_model"] == "claude-test"
    assert claim["agent_effort"] == "medium"
    assert claim["repository"] == "3"

    reported = SemanticResult(
        {"summary": "done"},
        0.8,
        (),
        input_tokens=39_002,
        output_tokens=800,
        cache_read_input_tokens=30_000,
        cache_creation_input_tokens=9_000,
        usage_reported=True,
    )
    submit = remote_payloads.submit_arguments(3, packet, reported)

    assert submit["job_id"] == 7
    assert submit["lease_token"] == "lease-token"
    assert submit["input_tokens"] == 39_002
    assert submit["cache_read_input_tokens"] == 30_000
    assert submit["cache_creation_input_tokens"] == 9_000

    silent = remote_payloads.submit_arguments(3, packet, SemanticResult({"s": 1}, 0.5, ()))

    assert "input_tokens" not in silent
    assert "cache_read_input_tokens" not in silent

    failure = SemanticAnalysisError(
        "model stopped", input_tokens=90, output_tokens=12, usage_reported=True
    )
    failed = remote_payloads.fail_arguments(3, packet, failure)

    assert failed["reason"] == "model stopped"
    assert (failed["input_tokens"], failed["output_tokens"]) == (90, 12)
    assert "input_tokens" not in remote_payloads.fail_arguments(3, packet, RuntimeError("boom"))
    assert remote_payloads.release_arguments(3, packet, "handoff")["reason"] == "handoff"
