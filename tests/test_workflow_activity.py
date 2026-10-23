"""Continuous handoffs and truthful activity without calling real model providers."""

from __future__ import annotations

import asyncio
import threading

import httpx
import pytest
from semantic_support import _DeterministicLifecycleProvider
from test_workflow_steps import choice, save
from test_workflows import finish, prepare

from anaxigraph.semantic_runner import _run_workers
from anaxigraph.workflow_execution import WorkflowExecution


@pytest.mark.anyio
@pytest.mark.parametrize("step", ["annotation", None])
async def test_free_slot_keeps_claiming_while_slow_job_runs_and_limit_is_exact(
    repository, database, monkeypatch, step
):
    release, fourth_started = threading.Event(), threading.Event()
    lock = threading.Lock()
    calls, active, peak = [], 0, 0

    class Provider(_DeterministicLifecycleProvider):
        def analyze(self, request):
            nonlocal active, peak
            with lock:
                calls.append(request["analysis_kind"])
                number = len(calls)
                active += 1
                peak = max(active, peak)
            try:
                if number == 1:
                    assert release.wait(10)
                if number == 4:
                    fourth_started.set()
                return super().analyze(request)
            finally:
                with lock:
                    active -= 1

    app = prepare(repository, database, monkeypatch, Provider())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await save(client, "annotation", [choice(workers=2)])
            response = await client.post(
                "/api/workflows/run",
                json=dict(workflow="mapping", step=step, use_step_settings=True, max_jobs=4),
            )
            assert response.json()["status"] == "started"
            try:
                # The fixture's max_jobs_per_run is 3. Neither that chunk boundary nor
                # the slow first call should prevent jobs 3 and 4 using the other slot.
                assert await asyncio.to_thread(fourth_started.wait, 5)
                await save(client, "annotation", [choice(model="gpt-6.1-sol", workers=1)])
                value = (await client.get("/api/workflows")).json()
                worker = value["semantic"]["worker"]
                assert worker["status"] == "running"
                assert worker["step"] == step
                assert worker["active_step"] == "annotation"
                assert worker["settings"]["annotation"] == [choice(workers=2)]
                assert value["settings"]["steps"]["annotation"][0]["model"] == "gpt-6.1-sol"
                assert value["coverage"]["workers"][0]["running"] >= 1
            finally:
                release.set()
            result = await finish(client, "waiting")
    assert calls == ["annotation"] * 4
    assert peak == 2
    assert result["semantic"]["worker"]["processed"] == 4
    assert result["coverage"]["scopes"]["module"]["intrinsic"] == 4


@pytest.mark.anyio
async def test_requested_step_is_visible_during_planning_before_any_claim(
    repository, database, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    plan = WorkflowExecution._plan

    def blocked_plan(self):
        entered.set()
        assert release.wait(10)
        return plan(self)

    monkeypatch.setattr(WorkflowExecution, "_plan", blocked_plan)
    app = prepare(repository, database, monkeypatch)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await save(client, "annotation", [choice(workers=2)])
            response = await client.post(
                "/api/workflows/run",
                json=dict(
                    workflow="mapping", step="annotation", use_step_settings=True, max_jobs=1
                ),
            )
            assert response.json()["status"] == "started"
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                value = (await client.get("/api/workflows")).json()
                assert value["semantic"]["worker"]["step"] == "annotation"
                assert value["semantic"]["worker"]["settings"]["annotation"] == [choice(workers=2)]
                assert value["coverage"]["workers"] == []
            finally:
                release.set()
            await finish(client, "waiting")


def test_workers_stop_on_an_empty_or_blocked_queue_without_spinning():
    calls = []

    def no_work():
        calls.append(None)
        return None

    assert _run_workers(no_work, workers=3, limit=100)["processed"] == 0
    assert len(calls) == 3


@pytest.mark.parametrize("status", ["completed", "failed", "retry", "superseded", "lease_lost"])
def test_all_processed_outcomes_count_toward_the_shared_limit(status):
    counts = _run_workers(lambda: status, workers=3, limit=5)
    assert counts["processed"] == counts[status] == 5


def test_executor_error_stops_its_pool_and_allows_existing_workers_to_finish():
    stop = threading.Event()
    lock = threading.Lock()
    calls = []

    def work():
        with lock:
            calls.append(None)
            first = len(calls) == 1
        if first:
            stop.set()
            return "failed"
        assert stop.wait(5)
        return "completed"

    counts = _run_workers(work, workers=2, limit=10, stop_on_failure=stop)
    assert stop.is_set()
    assert len(calls) == counts["processed"] == 2
    assert counts["failed"] == counts["completed"] == 1
    assert _run_workers(work, workers=2, limit=10, stop_on_failure=stop)["processed"] == 0
    assert len(calls) == 2


@pytest.mark.anyio
async def test_workflow_error_stops_refilling_instead_of_failing_the_entire_queue(
    repository, database, monkeypatch
):
    calls = []

    class Provider(_DeterministicLifecycleProvider):
        def analyze(self, request):
            calls.append(request["analysis_kind"])
            raise RuntimeError("Model is unavailable")

    app = prepare(repository, database, monkeypatch, Provider())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await save(client, "annotation", [choice(workers=2)])
            response = await client.post(
                "/api/workflows/run",
                json=dict(workflow="mapping", step="annotation", use_step_settings=True),
            )
            assert response.json()["status"] == "started"
            result = await finish(client, "waiting")
    assert 1 <= len(calls) <= 2
    assert result["semantic"]["worker"]["processed"] == len(calls)
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_jobs WHERE status = 'pending'"
            ).fetchone()[0]
            > 0
        )
