"""Plan item 2.5: the fresh-eyes start route is gated, offloaded, and deferrable."""

from __future__ import annotations

import threading

import anyio
import httpx
import pytest
from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.api import create_app
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_fresh_eyes_plan import FRESH_EYES_PLAN_KEY, FRESH_EYES_SCOPE
from anaxigraph.semantic_scope_plan import SemanticPlanningService
from anaxigraph.understanding import SemanticEngine

_PLAN_STATUS_SQL = "SELECT status FROM semantic_scope_states WHERE scope_type = ? AND scope_key = ?"
_PROPOSAL_COUNT_SQL = "SELECT COUNT(*) FROM semantic_jobs WHERE job_kind = 'fresh_proposal'"


def _drain_queue(engine, repository_id, repository, config, *, prefix="gate") -> None:
    """Finish every prepared job so the queue is empty for the next claim."""

    for index in range(500):
        packet = engine.claim_agent_work(
            repository_id,
            repository,
            config,
            agent_id=f"{prefix}-{index}",
            agent_model="fixture-model",
        )
        if packet["status"] == "complete":
            return
        assert packet["status"] == "work"
        engine.submit_agent_work(
            repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=_agent_dossier(packet["analysis_request"]),
        )
    raise AssertionError("Semantic queue did not converge")


def _ready_repository(repository, database):
    """Scan, finish the understanding baseline, and return an engine on an empty queue."""

    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _drain_queue(engine, stats.repository_id, repository, config, prefix="baseline")
    return engine, stats.repository_id, config


def _plan_status(database) -> str | None:
    with database.connect() as connection:
        row = connection.execute(
            _PLAN_STATUS_SQL, (FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY)
        ).fetchone()
    return None if row is None else str(row["status"])


def _proposal_jobs(database) -> int:
    with database.connect() as connection:
        return int(connection.execute(_PROPOSAL_COUNT_SQL).fetchone()[0])


@pytest.mark.anyio
async def test_fresh_eyes_start_is_gated_and_offloaded(repository, database, monkeypatch):
    """The in-flight start holds the operation gate without blocking the event loop."""

    _ready_repository(repository, database)
    entered = threading.Event()
    release = threading.Event()
    original = SemanticPlanningService.plan

    def blocked_plan(self, *args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SemanticPlanningService, "plan", blocked_plan)
    app = create_app(database=database, repository=repository, enable_mcp=False)
    started: dict[str, httpx.Response] = {}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=15
    ) as client:
        async with anyio.create_task_group() as tasks:

            async def start() -> None:
                started["response"] = await client.post("/api/fresh-eyes", json={})

            tasks.start_soon(start)
            while not entered.is_set():
                await anyio.sleep(0.01)
            in_flight = (await client.get("/api/health")).json()
            concurrent = await client.get("/api/fresh-eyes")
            release.set()

        settled = (await client.get("/api/health")).json()

    operations = in_flight["pressure"]["http_operations"]
    assert operations["active_count"] >= 1
    assert [item["operation"] for item in operations["active"]] == ["fresh_eyes_start"]
    assert in_flight["pressure"]["busy"] is True
    assert concurrent.status_code == 200
    assert started["response"].status_code == 200
    assert started["response"].json()["status"] == "started"
    assert started["response"].json()["plan_stage"] == "fresh_eyes_proposals"
    assert _proposal_jobs(database) == 2
    assert settled["pressure"]["http_operations"]["active_count"] == 0


@pytest.mark.anyio
async def test_fresh_eyes_wait_false_returns_deferred_plan_stage(repository, database):
    """``wait: false`` commits the request and leaves planning to the next claim."""

    _ready_repository(repository, database)
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=15
    ) as client:
        deferred = await client.post("/api/fresh-eyes", json={"wait": False})
        health = (await client.get("/api/health")).json()

    payload = deferred.json()
    assert deferred.status_code == 200
    assert payload["status"] == "started"
    assert payload["plan_stage"] == "deferred"
    assert payload["enqueued"] == 0
    assert _plan_status(database) == "requested"
    assert _proposal_jobs(database) == 0
    assert health["pressure"]["http_operations"]["active_count"] == 0


@pytest.mark.anyio
async def test_back_to_back_fresh_eyes_starts_are_admitted_without_a_cooldown(repository, database):
    """Sequential starts are never rate limited, and a refused rerun still frees the gate."""

    _ready_repository(repository, database)
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=15
    ) as client:
        first = await client.post("/api/fresh-eyes", json={"wait": False})
        second = await client.post("/api/fresh-eyes", json={"wait": False})
        rerun = await client.post("/api/fresh-eyes", json={"wait": False, "restart": True})
        health = (await client.get("/api/health")).json()

    assert first.status_code == 200
    assert first.json()["status"] == "started"
    assert second.status_code == 200
    assert second.json()["status"] == "already_started"
    assert rerun.status_code == 400
    assert "Finish or retry" in rerun.json()["detail"]
    assert health["pressure"]["http_operations"]["active_count"] == 0


def test_deferred_fresh_eyes_request_is_planned_by_the_next_executor_claim(repository, database):
    """The next claim plans the deferred request, but only on an otherwise empty queue."""

    engine, repository_id, config = _ready_repository(repository, database)

    deferred = engine.start_fresh_eyes_review(repository_id, repository, config, plan=False)

    assert deferred["plan_stage"] == "deferred"
    assert deferred["enqueued"] == 0
    assert _plan_status(database) == "requested"
    assert _proposal_jobs(database) == 0

    packet = engine.claim_agent_work(
        repository_id,
        repository,
        config,
        agent_id="deferred-claim",
        agent_model="fixture-model",
    )

    assert packet["status"] == "work"
    assert packet["job"]["kind"] == "fresh_proposal"
    assert _proposal_jobs(database) == 2
