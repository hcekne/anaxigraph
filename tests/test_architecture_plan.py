from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fresh_eyes_support import TwoExecutorReview, baseline_review
from planning_support import planning_dossier
from starlette.testclient import TestClient
from test_portable_record import publish_and_clone

from anaxigraph.api import create_app
from anaxigraph.architecture_plan import request_plan
from anaxigraph.architecture_plan_contract import (
    DEFAULT_DIRECTION,
    PLAN_SCHEMA,
    validate_plan_structure,
)
from anaxigraph.architecture_plan_read import architecture_plan_status, steer_plan
from anaxigraph.config import load_config
from anaxigraph.knowledge_mcp import KnowledgeMcpTools
from anaxigraph.planning_mcp import planning_journey
from anaxigraph.portable_record import save_record
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine


def complete_plan(repository, database, direction=""):
    review = baseline_review(repository, database)
    snapshot = database.latest_snapshot(review.repository_id)
    with database.transaction() as connection:
        request_plan(connection, review.repository_id, snapshot["id"], direction)
    worker = TwoExecutorReview(
        review.engine,
        review.repository_id,
        repository,
        review.config,
        dossier_factory=planning_dossier,
    )
    kinds = worker.run_until_complete()
    assert any(kind == "architecture_plan" for _, kind in kinds)
    return review, architecture_plan_status(database, review.repository_id)


def test_blank_direction_lets_agent_choose_target_without_approval(repository, database):
    review, plan = complete_plan(repository, database)
    assert plan["ready"]
    assert plan["direction"] == DEFAULT_DIRECTION
    assert plan["selection_source"] == "agent"
    assert plan["selected_option"] == "evolve"
    assert plan["selection_rationale"]
    assert plan["target"]["milestones"][0]["verification"] == ["Run tests/test_core.py"]
    assert plan["diagrams"]["changes"] == [{"key": "domain", "status": "retained"}]
    assert "flowchart LR" in plan["diagrams"]["target_mermaid"]
    assert review.engine.plan(review.repository_id, repository, review.config).enqueued == 0


def test_user_can_select_option_and_agent_reports_milestone_evidence(repository, database):
    review, plan = complete_plan(repository, database, "Preserve arithmetic behavior")
    assert plan["direction"] == "Preserve arithmetic behavior"
    changed = steer_plan(database, review.repository_id, option="preserve")
    assert changed["selected_option"] == "preserve"
    assert changed["selection_source"] == "user"
    steer_plan(database, review.repository_id, option="evolve", actor="agent")
    with pytest.raises(ValueError, match="verification evidence"):
        steer_plan(database, review.repository_id, milestone="reuse-owner", status="verified")
    changed = steer_plan(
        database,
        review.repository_id,
        milestone="reuse-owner",
        status="verified",
        evidence=["tests/test_core.py: passed"],
        actor="agent",
    )
    assert changed["progress"]["reuse-owner"]["reported_by"] == "agent"
    compact = architecture_plan_status(database, review.repository_id, details=False)
    assert "evidence" not in compact["progress"]["reuse-owner"]
    assert compact["progress"]["reuse-owner"]["status"] == "verified"


def test_blank_direction_resets_a_previous_custom_goal_and_manual_selection(repository, database):
    review, _ = complete_plan(repository, database, "Scale the compute boundary")
    steer_plan(database, review.repository_id, option="preserve")
    snapshot = database.latest_snapshot(review.repository_id)
    with database.transaction() as connection:
        request_plan(connection, review.repository_id, snapshot["id"], "")
    review.engine.plan(review.repository_id, repository, review.config)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT metadata_json FROM semantic_jobs WHERE job_kind = 'architecture_plan' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        controls = connection.execute(
            "SELECT interface_hash FROM semantic_scope_states WHERE scope_type = 'architecture_plan' AND snapshot_id = ?",
            (snapshot["id"],),
        ).fetchone()
    packet = json.loads(row[0])["planning_packet"]
    assert packet["direction"] == DEFAULT_DIRECTION
    assert packet["direction_source"] == "suggested_default"
    assert "selected_option" not in json.loads(controls[0])


def test_plan_rest_and_mcp_share_target_and_default_budget(repository, database):
    review, plan = complete_plan(repository, database)
    large = {**plan["value"], "summary": "s" * 4000, "direction": "d" * 4000}
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_documents SET value_json = ? WHERE document_kind = 'architecture_plan'",
            (json.dumps(large),),
        )
    with TestClient(
        create_app(database=database, repository=repository, enable_mcp=False)
    ) as client:
        response = client.get("/api/architecture-plan")
        assert response.status_code == 200
        assert response.json()["selected_option"] == plan["selected_option"]
        assert "value" not in response.json()
        assert len(response.content) <= 8000
        assert "value" in client.get("/api/architecture-plan?details=true").json()
        changed = client.post("/api/architecture-plan", json={"option": "preserve"})
        assert changed.status_code == 200
        workflow = client.get("/api/workflows").json()
        assert workflow["architecture_plan"]["ready"]
        assert "value" not in workflow["architecture_plan"]
    result = planning_journey(database, database.repository(review.repository_id), review.config)
    assert result["selected_option"] == "preserve"
    assert len(json.dumps(result, separators=(",", ":")).encode()) <= 8000


def test_plan_rejects_dangling_diagrams_and_unverifiable_milestones():
    value = planning_dossier({"analysis_kind": "architecture_plan", "direction": DEFAULT_DIRECTION})
    value["options"][1]["target"]["edges"] = [
        {"source": "domain", "target": "missing", "label": "calls", "evidence": []}
    ]
    with pytest.raises(ValueError, match="dangling"):
        validate_plan_structure(value)


def test_changed_options_do_not_attribute_an_agent_fallback_to_the_user(repository, database):
    review, plan = complete_plan(repository, database)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_scope_states SET interface_hash = ? WHERE scope_type = 'architecture_plan'",
            (
                json.dumps(
                    {
                        "selected_option": "retired-option",
                        "selection_source": "user",
                        "selection_rationale": "An earlier choice",
                    }
                ),
            ),
        )
    current = architecture_plan_status(database, review.repository_id)
    assert current["selected_option"] == plan["selected_option"]
    assert current["selection_source"] == "agent"
    assert current["selection_rationale"] == plan["selection_rationale"]


def test_plan_schema_requires_every_property_for_strict_model_output():
    def inspect(schema):
        if schema.get("type") == "object":
            assert set(schema["required"]) == set(schema["properties"])
            assert schema["additionalProperties"] is False
            for child in schema["properties"].values():
                inspect(child)
        if schema.get("type") == "array":
            inspect(schema["items"])

    inspect(PLAN_SCHEMA)


def test_plan_milestones_remain_usable_after_source_changes(repository, database):
    review, plan = complete_plan(repository, database)
    (repository / "pkg" / "core.py").write_text(
        (repository / "pkg" / "core.py").read_text() + "\nNEW_BEHAVIOR = True\n"
    )
    updated = RepositoryScanner(database).scan(repository)
    stale = architecture_plan_status(database, review.repository_id)
    assert stale["state"] == "stale"
    assert stale["selected_option"] == plan["selected_option"]
    reported = steer_plan(
        database,
        review.repository_id,
        milestone="reuse-owner",
        status="verified",
        evidence=["Focused behavior checks passed"],
        actor="agent",
    )
    assert (
        reported["progress"]["reuse-owner"]["verified_against_snapshot_id"] == updated.snapshot_id
    )
    assert reported["source_snapshot_id"] == plan["source_snapshot_id"]
    guidance = planning_journey(database, database.repository(review.repository_id), review.config)
    assert guidance["state"] == "stale"
    assert guidance["next_action"].startswith("Use the selected target")
    assert "value" not in guidance


def test_selected_plan_and_progress_travel_with_git_without_new_model_work(
    repository, database, tmp_path
):
    review, plan = complete_plan(repository, database)
    steer_plan(
        database,
        review.repository_id,
        milestone="reuse-owner",
        status="verified",
        evidence=["Focused tests passed"],
        actor="agent",
    )
    save_record(database, review.repository_id)
    assert (repository / "anaxigraph" / "architecture" / "target.mmd").is_file()
    local_root = publish_and_clone(repository, tmp_path / "local")
    local = AnaxiIndex(tmp_path / "local.db")
    stats = RepositoryScanner(local).scan(local_root)
    restored = architecture_plan_status(local, stats.repository_id)
    assert restored["selected_option"] == plan["selected_option"]
    assert restored["progress"]["reuse-owner"]["status"] == "verified"
    assert (
        SemanticEngine(local)
        .plan(stats.repository_id, local_root, load_config(local_root))
        .enqueued
        == 0
    )


def test_coding_agent_can_navigate_retained_proposed_graphs_without_source(repository, database):
    review, _ = complete_plan(repository, database)
    context = SimpleNamespace(
        database=database, select=lambda _: (database.repository(review.repository_id), repository)
    )
    tools = KnowledgeMcpTools(context)
    subjects = tools.graph(list_subjects=True)["subjects"]
    target = next(item for item in subjects if item["graph_kind"] == "planning_target")
    graph = tools.graph(graph_subject=target["id"], kind="")
    assert graph["context"]["revision"] == target["revision"]
    node = graph["nodes"][0]
    selected = tools.entity(node["id"], graph_subject=target["id"])
    assert selected["node"]["id"] == node["id"]
    assert selected["node"]["path"] == "" and selected["node"]["metrics"] == {}
    assert selected["node"]["provenance"]["observed_implementation"] is False
    assert (
        tools.graph(graph_subject=target["id"], kind="", evidence_state="extracted")["total_nodes"]
        == 0
    )
