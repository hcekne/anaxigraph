"""Durable recovery contracts for an until-complete remote semantic worker."""

from __future__ import annotations

import pytest

import anaxigraph.semantic_remote_worker as remote_worker
from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_service import SemanticServiceTarget


@pytest.mark.anyio
async def test_until_complete_rescans_a_stranded_queue_and_resumes(monkeypatch):
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
    monkeypatch.setattr(remote_worker, "prepare_semantic_service", prepare)
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
    recovery = remote_worker._IdleRecovery(_target(), retry_failed=False)
    semantic = {"snapshot_id": 7, "pending": 3, "jobs": {}}
    monkeypatch.setattr(
        remote_worker,
        "prepare_semantic_service",
        lambda *_args, **_kwargs: {"semantic": semantic},
    )

    assert await recovery.recover("waiting", semantic) is None
    assert await recovery.recover("waiting", semantic) is None
    assert await recovery.recover("waiting", semantic) is not None
    assert await recovery.recover("waiting", semantic) is None
    assert await recovery.recover("waiting", semantic) is None
    with pytest.raises(RuntimeError, match="after a synchronous rescan"):
        await recovery.recover("waiting", semantic)


def _target() -> SemanticServiceTarget:
    return SemanticServiceTarget("http://127.0.0.1:8765", 1, "AnaxiGraph", "/anaxigraph")
