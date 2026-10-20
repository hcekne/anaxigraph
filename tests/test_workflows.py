"""The dashboard runs real queue stages and reports saved coverage, not hopeful job totals."""

from __future__ import annotations

import asyncio
import threading

import httpx
import pytest
import yaml
from semantic_support import _DeterministicLifecycleProvider, _enable_agent_semantics

from anaxigraph.api import create_app
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def prepare(repository, database, monkeypatch, provider=None):
    _enable_agent_semantics(repository)
    path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(path.read_text())
    policy["semantic"].update(detailed_reviews=False, max_jobs_per_run=3, max_parallel_jobs=2)
    path.write_text(yaml.safe_dump(policy))
    RepositoryScanner(database).scan(repository)
    monkeypatch.setattr("anaxigraph.api_workflows.shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        "anaxigraph.semantic_runner.create_semantic_provider",
        lambda _: provider or _DeterministicLifecycleProvider(),
    )
    return create_app(database=database, repository=repository, enable_mcp=False)


async def finish(client, expected="complete"):
    for _ in range(500):
        value = (await client.get("/api/workflows")).json()
        if value["semantic"]["worker"]["status"] not in {"queued", "running"}:
            assert value["semantic"]["worker"]["status"] == expected, value["semantic"]["worker"]
            return value
        await asyncio.sleep(0.02)
    raise AssertionError("Workflow did not finish")


async def run(client, workflow):
    response = await client.post(
        "/api/workflows/run",
        json={
            "workflow": workflow,
            "executor": "codex",
            "model": "fixture-model",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "started"
    return await finish(client)


@pytest.mark.anyio
async def test_all_three_workflows_run_and_keep_optional_policy_unchanged(
    repository, database, monkeypatch
):
    app = prepare(repository, database, monkeypatch)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            before = (await client.get("/api/workflows")).json()
            assert before["fresh_eyes"]["state"] == "not_started"
            assert before["semantic"]["patterns"]["enabled"] is False
            mapped = await run(client, "mapping")
            modules = mapped["coverage"]["scopes"]["module"]
            assert (
                modules["current"] == modules["intrinsic"] == modules["total"] - modules["excluded"]
            )
            assert mapped["semantic"]["taxonomy"]["current"]["stored_reviews"] == 2
            assert mapped["semantic"]["worker"]["processed"] > 3  # several bounded queue batches
            assert mapped["fresh_eyes"]["state"] == "not_started"
            with database.connect() as connection:
                documents = list(
                    connection.execute(
                        "SELECT intrinsic_document_id, context_document_id FROM semantic_scope_states WHERE scope_type = 'module' ORDER BY scope_key"
                    )
                )
            patterned = await run(client, "patterns")
            assert patterned["semantic"]["patterns"]["planned"] is True
            assert patterned["coverage"]["scopes"]["pattern"]["current"] > 0
            assert load_config(repository).semantic.detailed_reviews is False
            with database.connect() as connection:
                assert (
                    list(
                        connection.execute(
                            "SELECT intrinsic_document_id, context_document_id FROM semantic_scope_states WHERE scope_type = 'module' ORDER BY scope_key"
                        )
                    )
                    == documents
                )
            reviewed = await run(client, "fresh-eyes")
            assert reviewed["fresh_eyes"]["ready"] is True
            assert len(reviewed["fresh_eyes"]["proposals"]) == 2
            assert reviewed["fresh_eyes"]["recommendation_count"] > 0
            assert "strategy" not in reviewed["fresh_eyes"]
            detailed = (await client.get("/api/workflows", params={"details": True})).json()
            assert detailed["fresh_eyes"]["strategy"]["recommendations"]
            assert reviewed["semantic"]["analysis_freshness"]["fresh_eyes"]["current"]
            assert all(
                item["provenance"]["executor_model"] == "fixture-model"
                for item in reviewed["fresh_eyes"]["stages"]
            )


@pytest.mark.anyio
async def test_reused_descriptions_are_counted_on_the_new_snapshot(
    repository, database, monkeypatch
):
    app = prepare(repository, database, monkeypatch)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await run(client, "mapping")
            path = repository / "pkg" / "util.py"
            path.write_text(path.read_text() + "\nNEW_VALUE = 3\n")
            RepositoryScanner(database).scan(repository)
            row = database.repository(repository)
            SemanticEngine(database).plan(row["id"], repository, load_config(repository))
            value = (await client.get("/api/workflows")).json()
            assert value["snapshot_id"] != first["snapshot_id"]
            assert value["coverage"]["scopes"]["module"]["intrinsic_reused"] > 0
            assert (
                value["coverage"]["scopes"]["module"]["intrinsic"]
                < first["coverage"]["scopes"]["module"]["intrinsic"]
            )


@pytest.mark.anyio
async def test_missing_model_stale_scan_and_unmounted_repo_do_not_start_workers(
    repository, database, monkeypatch
):
    app = prepare(repository, database, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.post(
            "/api/workflows/run", json={"workflow": "mapping", "executor": "codex"}
        )
        assert missing.status_code == 400
        assert "model" in missing.json()["detail"]
        (repository / "pkg" / "util.py").write_text("CHANGED = True\n")
        stale = await client.post(
            "/api/workflows/run",
            json={"workflow": "mapping", "executor": "codex", "model": "fixture"},
        )
        assert stale.status_code == 409
    readonly = create_app(database=database, enable_mcp=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=readonly), base_url="http://test"
    ) as client:
        value = (await client.get("/api/workflows")).json()
        assert value["execution"]["mounted"] is False
        assert (
            await client.post("/api/workflows/run", json={"workflow": "mapping"})
        ).status_code == 403


@pytest.mark.anyio
async def test_a_second_click_reuses_the_active_worker(repository, database, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class BlockingProvider(_DeterministicLifecycleProvider):
        def analyze(self, request):
            entered.set()
            assert release.wait(10)
            return super().analyze(request)

    app = prepare(repository, database, monkeypatch, BlockingProvider())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = {"workflow": "mapping", "executor": "codex", "model": "fixture"}
            assert (await client.post("/api/workflows/run", json=body)).json()[
                "status"
            ] == "started"
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                repeated = await client.post("/api/workflows/run", json=body)
                assert repeated.json()["status"] == "already_running"
                progress = (await client.get("/api/workflows")).json()
                assert any(row["running"] > 0 for row in progress["coverage"]["live_jobs"])
            finally:
                release.set()
            await finish(client)


@pytest.mark.anyio
async def test_pinned_review_can_resume_with_the_other_executor(repository, database, monkeypatch):
    app = prepare(repository, database, monkeypatch)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await run(client, "mapping")
            row = database.repository(repository)
            SemanticEngine(database).start_fresh_eyes_review(
                row["id"],
                repository,
                load_config(repository),
                proposal_executors=("codex", "claude"),
                plan=False,
            )
            response = await client.post(
                "/api/workflows/run",
                json={
                    "workflow": "fresh-eyes",
                    "executor": "codex",
                    "model": "first-fixture",
                },
            )
            assert response.status_code == 200
            waiting = await finish(client, expected="waiting")
            assert waiting["fresh_eyes"]["ready"] is False
            assert any(
                item["required_executor"] == "claude" for item in waiting["fresh_eyes"]["stages"]
            )
            response = await client.post(
                "/api/workflows/run",
                json={
                    "workflow": "fresh-eyes",
                    "executor": "claude",
                    "model": "second-fixture",
                },
            )
            assert response.status_code == 200
            completed = await finish(client)
            assert completed["fresh_eyes"]["diversity"]["cross_provider"] is True


@pytest.mark.anyio
async def test_failed_jobs_keep_their_error_and_no_cli_is_an_explicit_refusal(
    repository, database, monkeypatch
):
    class FailedProvider(_DeterministicLifecycleProvider):
        def analyze(self, request):
            raise RuntimeError("Test worker cannot authenticate")

    app = prepare(repository, database, monkeypatch, FailedProvider())
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text())
    policy["semantic"]["max_attempts"] = 1
    policy_path.write_text(yaml.safe_dump(policy))
    RepositoryScanner(database).scan(repository)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = {"workflow": "mapping", "executor": "codex", "model": "fixture"}
            assert (await client.post("/api/workflows/run", json=body)).status_code == 200
            value = await finish(client, expected="waiting")
            assert value["coverage"]["scopes"]["module"]["current"] == 0
            assert "cannot authenticate" in value["coverage"]["failures"][0]["error"]
            monkeypatch.setattr("anaxigraph.api_workflows.shutil.which", lambda _: None)
            refused = await client.post("/api/workflows/run", json=body)
            assert refused.status_code == 400
            assert "installed" in refused.json()["detail"]
