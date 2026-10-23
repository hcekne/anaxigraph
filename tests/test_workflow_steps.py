"""Per-card settings control real queue claims, provenance and independent proposal slots."""

from __future__ import annotations

import threading

import httpx
import pytest
import yaml
from semantic_support import _DeterministicLifecycleProvider
from test_workflows import finish, prepare

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine
from anaxigraph.workflow_execution import validate_proposal_settings
from anaxigraph.workflow_settings import StepSettingsRequest, WorkflowSettings


def choice(provider="codex", model="gpt-6-luna", workers=1):
    return dict(provider=provider, model=model, workers=workers, reasoning_effort="medium")


async def start(client, workflow="mapping", step=None, expected="complete", **options):
    response = await client.post(
        "/api/workflows/run",
        json={
            "workflow": workflow,
            "step": step,
            "use_step_settings": True,
            **options,
        },
    )
    assert response.status_code == 200, response.text
    return await finish(client, expected)


async def save(client, step, workers):
    response = await client.put("/api/workflows/settings", json={"step": step, "workers": workers})
    assert response.status_code == 200, response.text
    return response.json()


def test_settings_survive_reopening_and_are_repository_specific(database):
    store = WorkflowSettings(database.path)
    request = StepSettingsRequest(step="annotation", workers=[choice(workers=2)])
    store.save(1, request, 4)
    reopened = WorkflowSettings(database.path)
    assert reopened.read(1, 4)["steps"]["annotation"][0]["workers"] == 2
    assert reopened.read(2, 4)["steps"]["annotation"][0]["workers"] == 4
    assert reopened.read(1, 4)["customized"] == ["annotation"]
    assert len(reopened.read(2, 4, review_passes=1)["suggested"]["taxonomy_review"]) == 1


def test_existing_proposal_count_and_pins_must_match_resume_settings():
    fresh = {
        "stages": [
            {"key": "functional:product:proposal:a", "required_executor": "codex"},
            {"key": "functional:product:proposal:b", "required_executor": "claude"},
            {"key": "functional:product:proposal:c", "required_executor": "codex"},
        ]
    }
    validate_proposal_settings(fresh, [choice(), choice("claude", "claude-opus-5-5"), choice()])
    with pytest.raises(ValueError, match="proposal count"):
        validate_proposal_settings(fresh, [choice()])
    with pytest.raises(ValueError, match="another provider"):
        validate_proposal_settings(fresh, [choice(), choice(), choice()])


@pytest.mark.anyio
async def test_two_models_run_distinct_jobs_in_parallel_and_stop_at_the_sample_limit(
    repository, database, monkeypatch
):
    app = prepare(repository, database, monkeypatch)
    path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(path.read_text())
    policy["semantic"]["stage_models"] = {"module": {"model": "must-not-override-card"}}
    path.write_text(yaml.safe_dump(policy))
    RepositoryScanner(database).scan(repository)
    barrier = threading.Barrier(2)
    calls = []

    class Provider(_DeterministicLifecycleProvider):
        def __init__(self, semantic):
            self.semantic = semantic

        def analyze(self, request):
            calls.append((self.semantic.provider, self.semantic.model, request["analysis_kind"]))
            barrier.wait(5)
            return super().analyze(request)

    monkeypatch.setattr("anaxigraph.semantic_runner.create_semantic_provider", Provider)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await save(client, "annotation", [choice(), choice("claude", "claude-opus-5-5")])
            result = await start(client, step="annotation", max_jobs=2, expected="waiting")
            assert result["semantic"]["worker"]["processed"] == 2
            assert sorted(calls) == [
                ("claude", "claude-opus-5-5", "annotation"),
                ("codex", "gpt-6-luna", "annotation"),
            ]
            assert result["coverage"]["scopes"]["module"]["current"] == 2
            with database.connect() as connection:
                rows = connection.execute(
                    "SELECT job_kind, executor_model FROM semantic_jobs WHERE status='completed'"
                ).fetchall()
            assert sorted(tuple(row) for row in rows) == [
                ("annotation", "claude-opus-5-5"),
                ("annotation", "gpt-6-luna"),
            ]


@pytest.mark.anyio
async def test_card_routing_runs_all_flows_and_keeps_ordered_reviews_and_proposal_pins(
    repository, database, monkeypatch
):
    app = prepare(repository, database, monkeypatch)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            mapped = await start(client)
            assert mapped["semantic"]["taxonomy"]["current"]["stored_reviews"] == 2
            with database.connect() as connection:
                reviews = connection.execute(
                    "SELECT executor_model FROM semantic_jobs WHERE job_kind='taxonomy_review' AND status='completed' ORDER BY id"
                ).fetchall()
                file_documents = list(
                    connection.execute(
                        "SELECT intrinsic_document_id, context_document_id FROM semantic_scope_states WHERE scope_type='module' ORDER BY scope_key"
                    )
                )
            assert [row[0] for row in reviews] == ["gpt-6.1-sol", "claude-opus-5-5"]
            assessed = await start(client, "patterns", "pattern_assessment")
            assert assessed["coverage"]["scopes"]["pattern"]["intrinsic"] > 0
            assert assessed["coverage"]["scopes"]["pattern"]["current"] == 0
            patterned = await start(client, "patterns")
            assert patterned["coverage"]["scopes"]["pattern"]["current"] > 0
            proposals = await start(client, "fresh-eyes", "proposals")
            saved = [
                stage
                for stage in proposals["fresh_eyes"]["stages"]
                if ":proposal:" in stage["key"] and stage["state"] == "current"
            ]
            assert len(saved) == 9
            expected_models = {"a": "gpt-6.1-sol", "b": "claude-opus-5-5", "c": "gpt-6.1-sol"}
            assert all(
                stage["provenance"]["executor_model"] == expected_models[stage["key"][-1]]
                for stage in saved
            )
            reviewed = await start(client, "fresh-eyes")
            assert reviewed["fresh_eyes"]["ready"]
            assert reviewed["fresh_eyes"]["diversity"]["cross_provider"]
            remapped = await start(client)
            assert remapped["semantic"]["worker"]["processed"] == 0
            assert remapped["fresh_eyes"]["ready"]
            assert (
                remapped["coverage"]["scopes"]["pattern"]["current"]
                == patterned["coverage"]["scopes"]["pattern"]["current"]
            )
            assert (
                reviewed["coverage"]["scopes"]["pattern"]["current"]
                == patterned["coverage"]["scopes"]["pattern"]["current"]
            )
            with database.connect() as connection:
                assert (
                    list(
                        connection.execute(
                            "SELECT intrinsic_document_id, context_document_id FROM semantic_scope_states WHERE scope_type='module' ORDER BY scope_key"
                        )
                    )
                    == file_documents
                )


@pytest.mark.anyio
async def test_empty_claim_filter_cannot_fall_back_to_the_shared_queue(
    repository, database, monkeypatch
):
    prepare(repository, database, monkeypatch)
    from dataclasses import replace

    config = load_config(repository)
    engine = SemanticEngine(database)
    row = database.repository(repository)
    engine.plan(row["id"], repository, config)
    execution = replace(config.semantic, provider="codex", model="test-model")
    result = engine.run_jobs(
        row["id"], repository, config, execution_semantic=execution, job_ids=()
    )
    assert result["processed"] == 0
    assert result["semantic"]["pending"] > 0


@pytest.mark.anyio
async def test_settings_validation_and_step_membership(repository, database, monkeypatch):
    app = prepare(repository, database, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for step, workers in [
            ("annotation", [choice(workers=2), choice()]),
            ("charter", [choice(), choice()]),
            ("proposals", [choice()]),
            ("proposals", [choice(), choice()]),
            ("proposals", [choice(workers=2)]),
            ("scan", [choice()]),
        ]:
            response = await client.put(
                "/api/workflows/settings", json={"step": step, "workers": workers}
            )
            assert response.status_code == 400, response.text
        response = await client.post(
            "/api/workflows/run",
            json={"workflow": "mapping", "step": "proposals", "use_step_settings": True},
        )
        assert response.status_code == 400
        monkeypatch.setattr("anaxigraph.api_workflows.shutil.which", lambda _: None)
        response = await client.post(
            "/api/workflows/run",
            json={"workflow": "mapping", "step": "annotation", "use_step_settings": True},
        )
        assert response.status_code == 400


@pytest.mark.anyio
async def test_failed_step_keeps_errors_and_never_runs_another_stage(
    repository, database, monkeypatch
):
    class FailedProvider(_DeterministicLifecycleProvider):
        def analyze(self, request):
            raise RuntimeError("The selected model is unavailable to this account")

    app = prepare(repository, database, monkeypatch, FailedProvider())
    path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(path.read_text())
    policy["semantic"]["max_attempts"] = 1
    path.write_text(yaml.safe_dump(policy))
    RepositoryScanner(database).scan(repository)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await start(client, step="annotation", max_jobs=2, expected="waiting")
            assert result["semantic"]["worker"]["processed"] == 2
            assert "unavailable to this account" in result["coverage"]["failures"][0]["error"]
            assert result["coverage"]["scopes"]["module"]["intrinsic"] == 0
            with database.connect() as connection:
                assert not connection.execute(
                    "SELECT id FROM semantic_jobs WHERE job_kind != 'annotation' AND executor_id IS NOT NULL"
                ).fetchall()
