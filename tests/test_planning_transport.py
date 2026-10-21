"""Exact service authority and bounded shared-plan handoff to ordinary coding guidance."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient
from test_architecture_plan import complete_plan

from anaxigraph.api import create_app
from anaxigraph.architecture_plan_read import planning_guidance, steer_plan
from anaxigraph.cli import main
from anaxigraph.cli_planning_service import planning_service
from anaxigraph.portable_record import save_record
from anaxigraph.semantic_service import SemanticServiceTarget
from anaxigraph.workflow_settings import StepSettingsRequest, WorkflowSettings


def test_planning_and_record_cli_use_matching_service_without_creating_another_index(
    repository, database, monkeypatch, capsys
):
    review, _ = complete_plan(repository, database)
    service = SemanticServiceTarget("http://test", review.repository_id, "fixture", str(repository))
    monkeypatch.setattr(
        "anaxigraph.cli_planning_service.discover_semantic_service", lambda *a, **kw: service
    )
    with TestClient(
        create_app(database=database, repository=repository, enable_mcp=False)
    ) as client:

        def request(url, *, method, body, **kwargs):
            return client.request(method, url, json=body).raise_for_status().json()

        monkeypatch.setattr("anaxigraph.cli_planning_service._request_json", request)
        main(["plan", str(repository), "--select", "preserve", "--json"])
        plan = json.loads(capsys.readouterr().out)
        assert plan["index"]["authority"] == "service"
        assert plan["selected_option"] == "preserve"
        main(["record", "save", str(repository), "--json"])
        assert json.loads(capsys.readouterr().out)["status"] == "saved"
        main(["record", "status", str(repository), "--json"])
        assert json.loads(capsys.readouterr().out)["status"] == "loaded"
        response = client.post("/api/record/load")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "unchanged"


def test_explicit_database_does_not_discover_service(repository, database, monkeypatch):
    monkeypatch.setattr(
        "anaxigraph.cli_planning_service.discover_semantic_service",
        lambda *a, **kw: pytest.fail("local authority must be explicit"),
    )
    args = SimpleNamespace(db=database.path, service_url=None, repository=repository)
    assert planning_service(args) is None
    args.service_url = "http://localhost:8765"
    with pytest.raises(ValueError, match="either"):
        planning_service(args)


def test_planning_handoff_is_bounded_and_option_plus_progress_uses_selected_target(
    repository, database
):
    review, _ = complete_plan(repository, database)
    steer_plan(database, review.repository_id, option="preserve")
    result = steer_plan(
        database,
        review.repository_id,
        option="evolve",
        milestone="reuse-owner",
        status="in_progress",
        actor="agent",
    )
    assert result["progress"]["reuse-owner"]["status"] == "in_progress"
    guidance = planning_guidance(database, review.repository_id)
    assert guidance["next_milestone"]["key"] == "reuse-owner"
    assert len(json.dumps(guidance, separators=(",", ":")).encode()) <= 1200


def test_workflow_preferences_travel_but_local_choices_win(repository, database, tmp_path):
    from test_portable_record import publish_and_clone

    from anaxigraph.scanner import RepositoryScanner
    from anaxigraph.storage import AnaxiIndex

    RepositoryScanner(database).scan(repository)
    settings = WorkflowSettings(database.path)
    request = StepSettingsRequest(
        step="architecture_plan", workers=[{"provider": "codex", "model": "gpt-6.1-sol"}]
    )
    settings.save(1, request, 16)
    save_record(database, 1)
    clone = publish_and_clone(repository, tmp_path / "clone")
    restored = AnaxiIndex(tmp_path / "other.db")
    RepositoryScanner(restored).scan(clone)
    shared = WorkflowSettings(restored.path)
    assert shared.portable_choices(1)["architecture_plan"][0]["model"] == "gpt-6.1-sol"
    shared.save(
        1,
        StepSettingsRequest(
            step="architecture_plan", workers=[{"provider": "claude", "model": "claude-opus-5-5"}]
        ),
        16,
    )
    shared.restore_choices(1, settings.portable_choices(1))
    assert shared.portable_choices(1)["architecture_plan"][0]["provider"] == "claude"
    assert save_record(restored, 1)["status"] == "saved"
