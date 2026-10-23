from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from anaxigraph.agent import architecture_guidance, impact_analysis
from anaxigraph.api import create_app
from anaxigraph.config import load_config
from anaxigraph.knowledge_annotation_contract import validated_annotation
from anaxigraph.knowledge_detail import entity_detail, neighborhood
from anaxigraph.knowledge_query import entity_page
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


@pytest.fixture
def index(database):
    return database


def _repository(tmp_path):
    root = tmp_path / "graph-source"
    (root / "tests").mkdir(parents=True)
    (root / "service.py").write_text(
        '"""Deliver arithmetic calculations."""\n'
        'def calculate(value):\n    """Double a supplied value."""\n    return value * 2\n'
    )
    (root / "ui.py").write_text(
        "from service import calculate\ndef show():\n    return calculate(2)\n"
    )
    (root / "tests/test_service.py").write_text(
        "from service import calculate\ndef test_result():\n    assert calculate(3) == 6\n"
    )
    return root


def test_global_paging_search_and_direct_navigation_without_source(tmp_path, index):
    root = _repository(tmp_path)
    stats = RepositoryScanner(index).scan(root)
    page = entity_page(
        index, stats.repository_id, kind="module", limit=1, sort="lines_of_code", direction="desc"
    )
    assert page["returned_nodes"] == 1 and page["total_nodes"] == 3
    assert page["nodes"][0]["path"] == "service.py"
    hidden = entity_page(index, stats.repository_id, kind="module", q="ui.py")["nodes"][0]
    (root / "ui.py").unlink()
    assert entity_detail(index, stats.repository_id, hidden["id"])["node"]["path"] == "ui.py"
    assert "detail" not in page["nodes"][0]
    assert page["context"]["snapshot_id"] == stats.snapshot_id


def test_function_callers_interfaces_and_relevant_tests_are_typed(tmp_path, index):
    stats = RepositoryScanner(index).scan(_repository(tmp_path))
    graph = neighborhood(index, stats.repository_id, "function:service.py#service.calculate")
    edges = graph["edges"]
    assert any(
        e["source"] == "function:ui.py#ui.show" and e["relationship_type"] == "calls" for e in edges
    )
    assert any(
        e["source"].startswith("function:tests/") and e["relationship_type"] == "tests"
        for e in edges
    )
    assert any(e["target"] == "interface:service.py#service.calculate" for e in edges)
    assert all(e["resolution"] == "resolved_internal" for e in edges)


def _annotation():
    return {
        "overview": "Calculates doubled values.",
        "detail": "Provides the arithmetic operation used by the presentation layer.",
        "functions": [{"qualified_name": "service.calculate", "overview": "Doubles a value."}],
        "contracts": [
            {
                "name": "pure calculation",
                "statement": "Returns twice the input without mutation.",
                "functions": ["service.calculate"],
                "inputs": ["a numeric value"],
                "outputs": ["twice the value"],
                "errors": [],
                "side_effects": [],
                "invariants": ["input is unchanged"],
                "evidence": ["service.py:2"],
            }
        ],
        "capabilities": [
            {
                "name": "calculate totals",
                "purpose": "Calculate a doubled amount.",
                "inputs": ["amount"],
                "outputs": ["result"],
                "constraints": [],
            }
        ],
        "evidence": ["service.py:2"],
        "confidence": 0.9,
    }


def test_one_annotation_populates_graph_properties_and_linked_contracts(tmp_path, index):
    root = _repository(tmp_path)
    stats = RepositoryScanner(index).scan(root)
    config = load_config(root)
    config = replace(config, semantic=replace(config.semantic, enabled=True, provider="agent"))
    engine = SemanticEngine(index)
    engine.plan(stats.repository_id, root, config)
    with index.connect() as connection:
        target_job = connection.execute(
            "SELECT id FROM semantic_jobs WHERE scope_key='service.py' AND job_kind='annotation'"
        ).fetchone()[0]
    job = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, job_ids=(target_job,)
    )
    assert job["job_kind"] == "annotation"
    request = engine._services.evidence.job_request(job, root, config.semantic)
    assert request["analysis_kind"] == "annotation"
    value = _annotation()
    engine._services.persistence.complete_job(
        job, validated_annotation(value), "agent", config.semantic
    )
    selected = entity_detail(index, stats.repository_id, "module:" + job["scope_key"])
    assert selected["node"]["overview"] == value["overview"]
    assert selected["node"]["detail"] == value["detail"]
    with index.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_claims").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_jobs WHERE job_kind IN ('intrinsic','context')"
            ).fetchone()[0]
            == 0
        )
    contract = selected["contracts"][0]
    assert contract["properties"]["invariants"] == ["input is unchanged"]
    assert contract["provenance"]["annotation"]["verification"] == "unverified"
    function = entity_detail(index, stats.repository_id, "function:service.py#service.calculate")
    assert [item["id"] for item in function["contracts"]] == [contract["id"]]
    assert not function["functions"]


def test_function_impact_follows_its_consumers_without_unrelated_module_callers(tmp_path, index):
    root = _repository(tmp_path)
    with (root / "service.py").open("a") as file:
        file.write("\ndef unrelated():\n    return 'different behavior'\n")
    (root / "other_view.py").write_text(
        "from service import unrelated\ndef display():\n    return unrelated()\n"
    )
    stats = RepositoryScanner(index).scan(root)
    config = load_config(root)
    selected = "function:service.py#service.calculate"
    result = impact_analysis(
        index, repository_id=stats.repository_id, target=selected, config=config
    )
    consumers = {item["path"] for item in result["direct_dependants"]}
    assert "ui.py" in consumers and "other_view.py" not in consumers
    assert "tests/test_service.py" in result["tests_relevant"]
    assert result["entity_context"]["id"] == selected
    assert "Preserve caller obligations" in result["entity_context"]["change_rule"]
    guide = architecture_guidance(
        index,
        repository_id=stats.repository_id,
        goal="Improve calculation internals",
        focus=selected,
        config=config,
    )
    assert [item["path"] for item in guide["primary_files"]] == ["service.py"]
    assert guide["entity_context"]["id"] == selected


def test_unchanged_scans_do_not_append_graph_rows_and_wrong_revisions_fail(tmp_path, index):
    root = _repository(tmp_path)
    stats = RepositoryScanner(index).scan(root)
    first = entity_page(index, stats.repository_id)
    for _ in range(3):
        unchanged = RepositoryScanner(index).scan(root)
        assert unchanged.snapshot_id == stats.snapshot_id
        assert entity_page(index, stats.repository_id)["total_nodes"] == first["total_nodes"]
    with pytest.raises(ValueError, match="Snapshot"):
        entity_page(index, stats.repository_id, snapshot_id=987654)


def test_graph_routes_accept_stable_ids_and_reject_bad_filters(tmp_path, index):
    stats = RepositoryScanner(index).scan(_repository(tmp_path))
    with TestClient(create_app(database=index, enable_mcp=False)) as client:
        query = {"repository_id": stats.repository_id, "kind": "function", "limit": 1}
        response = client.get("/api/graph/entities", params=query)
        assert response.status_code == 200 and response.json()["total_nodes"] == 3
        identifier = response.json()["nodes"][0]["id"]
        detail = client.get("/api/graph/entity", params={"entity_id": identifier})
        assert detail.status_code == 200 and detail.json()["node"]["id"] == identifier
        assert (
            client.get("/api/graph/entities", params={"sort": "sql injection"}).status_code == 400
        )


def test_module_count_matches_logical_function_bindings(tmp_path, index):
    root = tmp_path / "overloads"
    root.mkdir()
    (root / "overloads.py").write_text(
        "from typing import overload\n"
        "@overload\ndef parse(value: str) -> str: ...\n"
        "@overload\ndef parse(value: int) -> int: ...\n"
        "def parse(value):\n    return value\n"
    )
    stats = RepositoryScanner(index).scan(root)
    module = entity_page(index, stats.repository_id, kind="module")["nodes"][0]
    functions = entity_page(index, stats.repository_id, kind="function")
    assert module["metrics"]["function_count"] == functions["total_nodes"] == 1
