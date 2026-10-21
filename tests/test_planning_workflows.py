"""Execute the full planning workflow and the headless publication command."""

from __future__ import annotations

import json

import httpx
import pytest
from planning_support import planning_dossier
from semantic_support import _DeterministicLifecycleProvider
from test_workflows import finish, prepare

from anaxigraph.architecture_plan_read import architecture_plan_status
from anaxigraph.cli import main
from anaxigraph.portable_io import read_record
from anaxigraph.record_publication import RecordPublisher


class PlanningProvider(_DeterministicLifecycleProvider):
    def analyze(self, request):
        from anaxigraph.semantic import SemanticResult

        return SemanticResult(
            value=planning_dossier(request), confidence=0.8, evidence=("fixture",)
        )


@pytest.mark.anyio
async def test_full_planning_runs_mapping_prerequisites_and_saves_git_record(
    repository, database, monkeypatch
):
    app = prepare(repository, database, monkeypatch, PlanningProvider())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/workflows/run", json={"workflow": "architecture", "use_step_settings": True}
            )
            assert response.status_code == 200, response.text
            completed = await finish(client)
            assert completed["architecture_plan"]["ready"], completed
            assert completed["semantic"]["worker"]["record"]["status"] == "saved"
    manifest, tables = read_record(repository)
    assert manifest["format"] == "anaxigraph-record-v1"
    assert any(
        item["value"]["document_kind"] == "architecture_plan"
        for item in tables["semantic_documents"]
    )
    assert (repository / "anaxigraph" / "architecture" / "plan.md").is_file()


def test_headless_refresh_runs_and_reuses_mapping_and_planning(
    repository, database, monkeypatch, capsys
):
    prepare(repository, database, monkeypatch, PlanningProvider())
    arguments = [
        "refresh",
        str(repository),
        "--db",
        str(database.path),
        "--workflows",
        "mapping,architecture",
        "--json",
    ]
    main(arguments)
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "complete"
    assert result["record"]["status"] == "saved"
    assert architecture_plan_status(database, 1)["selection_source"] == "agent"
    _first_manifest, first_rows = read_record(repository)
    main(arguments)
    reused = json.loads(capsys.readouterr().out)
    assert all(item["processed"] == 0 for item in reused["workflows"].values())
    _next_manifest, next_rows = read_record(repository)
    differences = []
    for table, rows in first_rows.items():
        by_key = {row["key"]: row["value"] for row in next_rows[table]}
        differences.extend(
            (table, field, old, by_key[row["key"]].get(field))
            for row in rows
            for field, old in row["value"].items()
            if old != by_key[row["key"]].get(field)
        )
    assert reused["record"]["changed_files"] == 0, differences


def test_record_publication_failure_is_explicit_and_preserves_local_analysis(
    repository, database, monkeypatch
):
    prepare(repository, database, monkeypatch, PlanningProvider())

    def denied(*args):
        raise PermissionError("Record directory is read-only")

    monkeypatch.setattr("anaxigraph.record_publication.save_record", denied)
    receipt = RecordPublisher(database, 1).save()
    assert receipt["status"] == "not_saved"
    assert "local index" in receipt["action"]
    assert database.latest_snapshot(1)


def test_periodic_record_checkpoint_does_not_wait_for_a_long_running_step(
    repository, database, monkeypatch
):
    from threading import Event

    from anaxigraph.scanner import RepositoryScanner

    RepositoryScanner(database).scan(repository)
    saved = Event()
    original = RecordPublisher.save

    def observe(publisher):
        receipt = original(publisher)
        saved.set()
        return receipt

    monkeypatch.setattr(RecordPublisher, "save", observe)
    with RecordPublisher(database, 1, interval=0.01):
        assert saved.wait(3), "completed analysis was not checkpointed while execution was busy"
        manifest, _ = read_record(repository)
        assert manifest["source"]["snapshot"]
    assert original(RecordPublisher(database, 1))["changed_files"] == 0
