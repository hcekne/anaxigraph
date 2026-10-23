"""A card request owns its dependency prefix; overlapping requests share durable leases."""

import asyncio
import threading

import httpx
import pytest
from semantic_support import _DeterministicLifecycleProvider
from test_workflow_steps import choice, save, start
from test_workflows import finish, prepare

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine


@pytest.mark.anyio
async def test_review_runs_missing_prerequisites_stops_at_target_and_reuses_results(
    repository, database, monkeypatch
):
    app = prepare(repository, database, monkeypatch)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await start(client, step="taxonomy_review")
            assert result["semantic"]["taxonomy"]["ready"]
            assert result["semantic"]["worker"]["steps"] == [
                "annotation",
                "contracts",
                "taxonomy_proposal",
                "taxonomy_review",
            ]
            with database.connect() as connection:
                jobs = connection.execute(
                    "SELECT job_kind, executor_model, attempts FROM semantic_jobs "
                    "WHERE status = 'completed' ORDER BY id"
                ).fetchall()
            assert {row["job_kind"] for row in jobs} == {
                "annotation",
                "taxonomy_proposal",
                "taxonomy_review",
            }
            assert [
                row["executor_model"] for row in jobs if row["job_kind"] == "taxonomy_review"
            ] == ["gpt-6.1-sol", "claude-opus-5-5"]
            assert all(row["attempts"] == 1 for row in jobs)
            reused = await start(client, step="taxonomy_review")
            assert reused["semantic"]["worker"]["processed"] == 0
            (repository / "pkg" / "util.py").write_text("UPDATED = 2\n")
            RepositoryScanner(database).scan(repository)
            updated = await start(client, step="taxonomy_review")
            assert updated["semantic"]["taxonomy"]["ready"]
            assert updated["coverage"]["scopes"]["module"]["intrinsic_reused"] > 0
            with database.connect() as connection:
                assert not connection.execute(
                    "SELECT 1 FROM semantic_jobs WHERE status='completed' AND job_kind='synthesis'"
                ).fetchone()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "workflow,step", [("patterns", "pattern_review"), ("fresh-eyes", "comparison")]
)
async def test_optional_review_builds_missing_map_without_changing_file_contracts(
    repository, database, monkeypatch, workflow, step
):
    app = prepare(repository, database, monkeypatch)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await start(client, workflow, step)
            assert result["semantic"]["architecture_charter"]["status"] == "current"
            reused = await start(client, step="annotation")
            assert reused["semantic"]["worker"]["processed"] == 0
            assert not load_config(repository).semantic.detailed_reviews
            if workflow == "fresh-eyes":
                states = {stage["key"]: stage["state"] for stage in result["fresh_eyes"]["stages"]}
                comparisons = [
                    state for key, state in states.items() if key.endswith(":comparison")
                ]
                assert len(comparisons) == 3 and set(comparisons) == {"current"}
                assert states.get("functional:review") != "current"
            else:
                assert result["coverage"]["scopes"]["pattern"]["current"] > 0


@pytest.mark.anyio
@pytest.mark.parametrize("description_workers", [1, 2])
async def test_two_step_requests_share_slots_without_duplicate_calls(
    repository, database, monkeypatch, description_workers
):
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    calls = []
    counters = {"active": 0, "peak": 0}

    class Provider(_DeterministicLifecycleProvider):
        def analyze(self, request):
            key = (request["analysis_kind"], request.get("path") or request.get("scope_key"))
            with lock:
                first = not calls
                calls.append(key)
                counters["active"] += 1
                counters["peak"] = max(counters["peak"], counters["active"])
            try:
                if first:
                    entered.set()
                    assert release.wait(10)
                return super().analyze(request)
            finally:
                with lock:
                    counters["active"] -= 1

    app = prepare(repository, database, monkeypatch, Provider())
    body = {"workflow": "mapping", "step": "annotation", "use_step_settings": True}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await save(client, "annotation", [choice(workers=description_workers)])
            try:
                first = await client.post("/api/workflows/run", json=body)
                assert first.json()["status"] == "started"
                assert await asyncio.to_thread(entered.wait, 5)
                second = await client.post("/api/workflows/run", json={**body, "step": "contracts"})
                assert second.json()["status"] == "started"
                duplicate = await client.post("/api/workflows/run", json=body)
                assert duplicate.json()["status"] == "already_running"
                status = (await client.get("/api/workflows")).json()["semantic"]["worker"]
                assert status["active_count"] == 2
                assert {run["step"] for run in status["runs"]} == {"annotation", "contracts"}
                if description_workers == 2:
                    for _ in range(100):
                        if len(calls) > 1:
                            break
                        await asyncio.sleep(0.02)
                    assert len(calls) > 1, (
                        "Independent annotations must use the configured parallel slots"
                    )
                else:
                    await asyncio.sleep(0.2)
                    assert len(calls) == 1, (
                        "Joining prerequisites must not multiply the configured pool"
                    )
            finally:
                release.set()
            result = await finish(client)
            assert all(run["status"] == "complete" for run in result["semantic"]["worker"]["runs"])
            assert result["coverage"]["scopes"]["module"]["current"] == 8
            assert len(calls) == len(set(calls)) == 8
            assert counters["peak"] <= 2


def test_reopening_existing_index_installs_scope_lookup_without_changing_jobs(
    repository, database, monkeypatch
):
    prepare(repository, database, monkeypatch)
    row = database.repository(repository)
    engine = SemanticEngine(database)
    engine.plan(row["id"], repository, load_config(repository))
    with database.transaction() as connection:
        connection.execute("DROP INDEX idx_semantic_jobs_scope")
        before = list(connection.execute("SELECT * FROM semantic_jobs ORDER BY id"))
    for _ in range(2):
        AnaxiIndex(database.path).initialize()
    with database.connect() as connection:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM semantic_jobs "
            "WHERE snapshot_id=? AND scope_type=? AND scope_key=? AND job_kind=? AND input_hash=?",
            (before[0]["snapshot_id"], "module", "pkg/core.py", "annotation", "hash"),
        ).fetchall()
        assert "idx_semantic_jobs_scope" in str([tuple(row) for row in plan])
        assert list(connection.execute("SELECT * FROM semantic_jobs ORDER BY id")) == before
