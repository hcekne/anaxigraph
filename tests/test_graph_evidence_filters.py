"""Evidence selection is applied before neighborhood limits and global page counts."""

import pytest
from fastapi.testclient import TestClient
from test_knowledge_graph import _repository

from anaxigraph.api import create_app
from anaxigraph.knowledge_detail import neighborhood
from anaxigraph.knowledge_edges import insert_edge
from anaxigraph.knowledge_query import entity_page
from anaxigraph.knowledge_sync import refresh_degrees
from anaxigraph.knowledge_values import classify_evidence
from anaxigraph.scanner import RepositoryScanner


def test_neighborhood_evidence_filter_applies_before_bounded_expansion(tmp_path, database):
    stats = RepositoryScanner(database).scan(_repository(tmp_path))
    entity_page(database, stats.repository_id)
    center = "function:service.py#service.calculate"
    target = "function:ui.py#ui.show"
    with database.transaction() as connection:
        insert_edge(
            connection,
            stats.snapshot_id,
            center,
            target,
            "inferred_relationship",
            method="inferred",
        )
        insert_edge(
            connection,
            stats.snapshot_id,
            center,
            target,
            "unresolved_relationship",
            resolution="unresolved",
            confidence=0,
        )
    for state, expected in (
        ("inferred", "inferred_relationship"),
        ("unresolved", "unresolved_relationship"),
    ):
        graph = neighborhood(database, stats.repository_id, center, limit=2, evidence_state=state)
        assert graph["returned_nodes"] == 2
        assert graph["returned_edges"] == 1
        assert graph["edges"][0]["relationship_type"] == expected
        assert classify_evidence(graph["edges"][0]) == state
        assert graph["scope"]["evidence_state"] == state
        assert graph["counts_are_complete"] is True
    extracted = neighborhood(database, stats.repository_id, center, evidence_state="extracted")
    assert extracted["edges"]
    assert all(classify_evidence(edge) == "extracted" for edge in extracted["edges"])
    with pytest.raises(ValueError, match="evidence state"):
        neighborhood(database, stats.repository_id, center, evidence_state="verified")


def test_rest_evidence_filter_and_invalid_values_share_graph_contract(tmp_path, database):
    stats = RepositoryScanner(database).scan(_repository(tmp_path))
    with TestClient(create_app(database=database, enable_mcp=False)) as client:
        params = {
            "repository_id": stats.repository_id,
            "kind": "function",
            "evidence_state": "extracted",
            "limit": 1,
        }
        result = client.get("/api/graph/entities", params=params)
        assert result.status_code == 200
        assert result.json()["total_nodes"] == 3 and result.json()["returned_nodes"] == 1
        identifier = result.json()["nodes"][0]["id"]
        neighbors = client.get(
            "/api/graph/neighborhood",
            params={"entity_id": identifier, "evidence_state": "extracted"},
        )
        assert neighbors.status_code == 200
        assert all(classify_evidence(edge) == "extracted" for edge in neighbors.json()["edges"])
        assert (
            client.get(
                "/api/graph/neighborhood",
                params={"entity_id": identifier, "evidence_state": "pretend"},
            ).status_code
            == 400
        )
        assert (
            client.get(
                "/api/graph/entities", params={**params, "evidence_state": "pretend"}
            ).status_code
            == 400
        )


def test_documentation_relationships_stay_visible_without_inflating_code_coupling(
    tmp_path, database
):
    root = _repository(tmp_path)
    (root / "README.md").write_text("See [the implementation](service.py).\n")
    stats = RepositoryScanner(database).scan(root)
    before = {
        item["id"]: item["metrics"]
        for item in entity_page(
            database, stats.repository_id, kind="module", include_reference=True
        )["nodes"]
    }
    with database.transaction() as connection:
        insert_edge(
            connection, stats.snapshot_id, "module:service.py", "module:README.md", "references"
        )
        refresh_degrees(connection, stats.snapshot_id)
    after = {
        item["id"]: item["metrics"]
        for item in entity_page(
            database, stats.repository_id, kind="module", include_reference=True
        )["nodes"]
    }
    assert before["module:service.py"]["fan_in"] == 2
    assert after["module:service.py"]["fan_in"] == 2
    assert after["module:service.py"]["fan_out"] == before["module:service.py"]["fan_out"]
    assert after["module:README.md"]["fan_in"] == 0
    assert after["module:README.md"]["fan_out"] == 0
    graph = neighborhood(database, stats.repository_id, "module:service.py")
    assert any(
        edge["source"] == "module:service.py" and edge["target"] == "module:README.md"
        for edge in graph["edges"]
    )
