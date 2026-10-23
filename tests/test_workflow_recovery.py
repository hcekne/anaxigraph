"""One click drains both model pools, including retries, without calling paid models."""

from __future__ import annotations

import json
import threading
from collections import Counter
from dataclasses import replace

import httpx
import pytest
from semantic_support import _DeterministicLifecycleProvider
from test_workflow_steps import choice, save, start
from test_workflows import prepare

from anaxigraph.api_workflows import WorkflowRequest
from anaxigraph.config import load_config
from anaxigraph.persistence.workflow_read import workflow_coverage
from anaxigraph.workflow_execution import WorkflowExecution, validate_proposal_settings
from anaxigraph.workflow_settings import WorkflowSettings


@pytest.mark.parametrize("unavailable", [(), ("claude",), ("codex", "claude")])
def test_two_sixteen_worker_pools_drain_all_files_and_isolate_executor_failure(
    repository, database, monkeypatch, unavailable
):
    for index in range(88):
        (repository / "pkg" / f"module_{index}.py").write_text(f"VALUE = {index}\n")
    prepare(repository, database, monkeypatch)
    config = load_config(repository)
    config = replace(config, semantic=replace(config.semantic, max_parallel_jobs=32))
    row = database.repository(repository)
    calls, active, peak = [], Counter(), Counter()
    barrier, lock = threading.Barrier(32), threading.Lock()

    class Provider(_DeterministicLifecycleProvider):
        def __init__(self, semantic):
            self.provider = semantic.provider

        def analyze(self, request):
            with lock:
                calls.append((self.provider, request["path"]))
                first_wave = len(calls) <= 32
                active[self.provider] += 1
                peak[self.provider] = max(peak[self.provider], active[self.provider])
            try:
                if first_wave:
                    barrier.wait(20)
                if self.provider in unavailable:
                    raise RuntimeError("[claude-code:unrecognized_model] selected model rejected")
                return super().analyze(request)
            finally:
                with lock:
                    active[self.provider] -= 1

    monkeypatch.setattr("anaxigraph.semantic_runner.create_semantic_provider", Provider)
    errors = []
    execution = WorkflowExecution(
        database,
        row,
        config,
        WorkflowRequest(workflow="mapping", step="annotation"),
        {"annotation": [choice(workers=16), choice("claude", "claude-sonnet-5-5", 16)]},
        on_pool_error=errors.append,
    )
    result = execution.run()
    assert peak == {"codex": 16, "claude": 16}
    assert {error["provider"] for error in errors} == set(unavailable)
    assert result["pool_errors"] == errors
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT status, attempts FROM semantic_jobs WHERE job_kind='annotation'"
        ).fetchall()
        coverage = workflow_coverage(connection, execution.snapshot_id)
        other = connection.execute(
            "SELECT COUNT(*) FROM semantic_jobs WHERE job_kind!='annotation' AND attempts>0"
        ).fetchone()[0]
    assert other == 0
    if len(unavailable) == 2:
        assert result["status"] == "waiting"
        assert result["processed"] == len(calls) == 32
        assert "unrecognized_model" in result["message"]
        assert Counter(tuple(row) for row in rows) == {("retry", 1): 32, ("pending", 0): 64}
        assert coverage["failures"][0]["status"] == "retry"
    else:
        failed_calls = sum(provider in unavailable for provider, _ in calls)
        assert failed_calls == 16 * len(unavailable)
        assert result["status"] == "complete"
        assert result["processed"] == len(calls) == 96 + failed_calls
        assert sum(row["status"] == "completed" for row in rows) == 96
        assert sum(row["attempts"] for row in rows) == len(calls)
        assert coverage["scopes"]["module"]["intrinsic"] == 96
        assert not coverage["failures"]
        successful_paths = [path for provider, path in calls if provider not in unavailable]
        assert len(successful_paths) == len(set(successful_paths)) == 96


@pytest.mark.anyio
@pytest.mark.parametrize("permanent", [False, True])
async def test_file_errors_retry_automatically_without_stopping_other_files(
    repository, database, monkeypatch, permanent
):
    calls, first_path = Counter(), []

    class Provider(_DeterministicLifecycleProvider):
        def analyze(self, request):
            path = request["path"]
            if not first_path:
                first_path.append(path)
            calls[path] += 1
            if path == first_path[0] and (permanent or calls[path] == 1):
                raise RuntimeError("Provider response was incomplete")
            return super().analyze(request)

    app = prepare(repository, database, monkeypatch, Provider())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await save(client, "annotation", [choice(workers=1)])
            value = await start(
                client, step="annotation", expected="waiting" if permanent else "complete"
            )
    maximum = load_config(repository).semantic.max_attempts
    assert calls[first_path[0]] == (maximum if permanent else 2)
    assert len(calls) == 8
    assert sum(calls.values()) == 7 + calls[first_path[0]]
    assert value["coverage"]["scopes"]["module"]["intrinsic"] == (7 if permanent else 8)
    if permanent:
        assert "Provider response was incomplete" in value["semantic"]["worker"]["message"]
        assert value["coverage"]["failures"][0]["status"] == "failed"


def test_saved_family_alias_is_migrated_without_losing_worker_counts(database):
    settings = WorkflowSettings(database.path)
    settings.directory.mkdir()
    path = settings.directory / "1.json"
    path.write_text(json.dumps({"intrinsic": [choice("claude", "claude-sonnet", 16)]}))
    value = settings.read(1, 32)
    assert value["steps"]["annotation"] == [choice("claude", "claude-sonnet-5-5", 16)]
    assert "claude-sonnet" not in value["models"]["claude"]


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("portable", [False, True])
def test_legacy_proposal_choices_resume_with_three_retained_alternatives(database, count, portable):
    settings = WorkflowSettings(database.path)
    original = [choice(), choice("claude", "claude-opus")][:count]
    saved = {"proposals": original}
    if portable:
        settings.restore_choices(1, saved)
    else:
        settings.directory.mkdir()
        (settings.directory / "1.json").write_text(json.dumps(saved))
    workers = settings.read(1, 4)["steps"]["proposals"]
    assert len(workers) == 3
    assert workers[0] == original[0]
    if count == 2:
        assert workers[1] == choice("claude", "claude-opus-5-5")
    assert workers[2] == original[0]
    stages = [
        {"key": f"functional:product:proposal:{slot}", "required_executor": worker["provider"]}
        for slot, worker in zip("abc", workers)
    ]
    validate_proposal_settings({"stages": stages}, workers)
    assert saved == {"proposals": original}


@pytest.mark.anyio
async def test_model_dropdown_is_enforced_by_the_settings_api(repository, database, monkeypatch):
    app = prepare(repository, database, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for provider, model in [
            ("codex", "claude-sonnet-5-5"),
            ("claude", "gpt-6-luna"),
            ("codex", "gpt-6.1-luna"),
            ("claude", "made-up-model"),
        ]:
            response = await client.put(
                "/api/workflows/settings",
                json={"step": "annotation", "workers": [choice(provider, model)]},
            )
            assert response.status_code == 422
        saved = await save(client, "annotation", [choice("claude", "claude-sonnet")])
        assert saved["settings"]["steps"]["annotation"][0]["model"] == "claude-sonnet-5-5"
