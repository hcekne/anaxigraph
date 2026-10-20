"""Remote ownership stays alive through long model calls and rejects stale writers."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from semantic_support import _agent_dossier
from test_semantic_lease_concurrency import _agent_queue, _expire_running_leases, _job_row

import anaxigraph.semantic_remote_leases as remote_leases


def claim(engine, repository_id, repository, config):
    return engine.claim_agent_work(
        repository_id, repository, config, agent_id="cli:claude:test", agent_model="fixture"
    )


def renew(engine, repository_id, config, packet, **overrides):
    return engine.renew_agent_work(
        repository_id,
        config,
        **{"job_id": packet["job"]["id"], "lease_token": packet["lease"]["token"], **overrides},
    )


@pytest.mark.anyio
async def test_long_remote_call_renews_then_saves_without_a_second_attempt(
    repository, database, monkeypatch
):
    config, repository_id, engine = _agent_queue(repository, database)
    config = replace(config, semantic=replace(config.semantic, agent_lease_seconds=1))
    packet = claim(engine, repository_id, repository, config)
    before = _job_row(database, packet["job"]["id"])
    renewals = []

    async def call(_session, name, arguments, **kwargs):
        assert name == "ANAXIGRAPH_SEMANTIC_RENEW"
        result = engine.renew_agent_work(
            repository_id, config, job_id=arguments["job_id"], lease_token=arguments["lease_token"]
        )
        renewals.append(result)
        return result

    monkeypatch.setattr(remote_leases, "call_tool_retrying_locks", call)
    remaining = {0}
    async with remote_leases.keep_remote_leases(
        object(), SimpleNamespace(repository_id=repository_id), [packet], remaining
    ):
        await asyncio.sleep(1.2)
        saved = engine.submit_agent_work(
            repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=_agent_dossier(packet["analysis_request"]),
        )
        remaining.clear()
    assert len(renewals) >= 2
    assert renewals[-1]["expires_at"] > before["lease_expires_at"]
    assert saved["status"] == "completed"
    after = _job_row(database, packet["job"]["id"])
    assert (after["status"], after["attempts"]) == ("completed", 1)
    # A renewal racing with submission is harmless and cannot reopen completed work.
    assert renew(engine, repository_id, config, packet)["status"] == "already_completed"
    assert _job_row(database, packet["job"]["id"])["status"] == "completed"


def test_renewal_rejects_wrong_owner_repository_and_expired_lease(repository, database):
    config, repository_id, engine = _agent_queue(repository, database)
    packet = claim(engine, repository_id, repository, config)
    before = _job_row(database, packet["job"]["id"])["lease_expires_at"]
    with pytest.raises(ValueError, match="token"):
        renew(engine, repository_id, config, packet, lease_token="wrong")
    with pytest.raises(ValueError, match="repository"):
        renew(engine, repository_id + 1, config, packet)
    assert _job_row(database, packet["job"]["id"])["lease_expires_at"] == before
    _expire_running_leases(database)
    with pytest.raises(ValueError, match="expired"):
        renew(engine, repository_id, config, packet)
    replacement = claim(engine, repository_id, repository, config)
    assert replacement["job"]["id"] == packet["job"]["id"]
    with pytest.raises(ValueError, match="token"):
        renew(engine, repository_id, config, packet)
    assert renew(engine, repository_id, config, replacement)["status"] == "renewed"


def test_renewal_cannot_extend_work_from_an_older_scan(repository, database):
    from anaxigraph.scanner import RepositoryScanner

    config, repository_id, engine = _agent_queue(repository, database)
    packet = claim(engine, repository_id, repository, config)
    before = _job_row(database, packet["job"]["id"])["lease_expires_at"]
    (repository / "pkg" / "new_source.py").write_text("VALUE = 1\n")
    RepositoryScanner(database).scan(repository)
    with pytest.raises(ValueError, match="older source scan|not leased"):
        renew(engine, repository_id, config, packet)
    assert _job_row(database, packet["job"]["id"])["lease_expires_at"] == before


@pytest.mark.anyio
async def test_transient_renewal_failure_does_not_kill_the_heartbeat(monkeypatch):
    calls, progress = [], []
    recovered = asyncio.Event()
    packet = {
        "job": {"id": 1},
        "lease": {
            "token": "owned",
            "renewal_tool": "ANAXIGRAPH_SEMANTIC_RENEW",
            "renew_after_seconds": 0.01,
        },
    }

    async def call(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("temporary transport failure")
        recovered.set()

    monkeypatch.setattr(remote_leases, "call_tool_retrying_locks", call)
    monkeypatch.setattr(
        remote_leases, "report_background_progress", lambda **value: progress.append(value)
    )
    async with remote_leases.keep_remote_leases(
        object(), SimpleNamespace(repository_id=1), [packet], {0}
    ):
        await asyncio.wait_for(recovered.wait(), 2)
    assert len(calls) == 2
    assert "temporary transport failure" in progress[0]["last_error"]
