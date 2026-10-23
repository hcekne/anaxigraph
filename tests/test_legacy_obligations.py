"""Legacy strings stay available without fabricated named graph contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from anaxigraph.api import create_app
from anaxigraph.config import load_config
from anaxigraph.knowledge_detail import entity_detail, neighborhood
from anaxigraph.knowledge_legacy import attach_legacy
from anaxigraph.knowledge_query import entity_page
from anaxigraph.persistence.semantic_payloads import migrate_semantic_payloads
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_records import _upsert_state


def _legacy(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    statements = [
        "Return the doubled input without changing caller-owned state.",
        "Preserve the public numeric argument and result contract.",
        "Do not write application configuration while calculating a value.",
        "Return the same result when the same input is supplied again.",
    ]
    value = {
        "summary": "Double supplied values.",
        "public_contracts": statements,
        "evidence": ["pkg/util.py:3"],
        "original": "Preserve résumé provenance. " * 50,
    }
    with database.transaction() as connection:
        fact = connection.execute(
            "SELECT f.id,f.artifact_id FROM file_facts f JOIN artifacts a ON a.id=f.artifact_id WHERE a.canonical_path='pkg/util.py'"
        ).fetchone()
        row = {
            "repository_id": stats.repository_id,
            "snapshot_id": stats.snapshot_id,
            "scope_type": "module",
            "scope_key": "pkg/util.py",
            "artifact_id": fact["artifact_id"],
            "file_fact_id": fact["id"],
            "document_kind": "intrinsic",
            "input_hash": "legacy-input",
            "intent_fingerprint": "legacy-intent",
            "value_json": json.dumps(value),
            "source": "agent",
            "provider": "codex",
            "model": "original-model",
            "prompt_version": load_config(repository).semantic.prompt_version,
            "schema_version": "module-dossier-v4",
            "confidence": 0.8,
            "created_at": datetime.now(UTC).isoformat(),
        }
        columns = ",".join(row)
        identifier = connection.execute(
            f"INSERT INTO semantic_documents({columns}) VALUES ({','.join('?' for _ in row)})",
            list(row.values()),
        ).lastrowid
        _upsert_state(
            connection,
            repository_id=stats.repository_id,
            snapshot_id=stats.snapshot_id,
            scope_type="module",
            scope_key="pkg/util.py",
            artifact_id=fact["artifact_id"],
            file_fact_id=fact["id"],
            artifact_version_id=None,
            status="current",
            reason="Reused",
            intrinsic_document_id=identifier,
            context_document_id=identifier,
        )
        document = dict(
            connection.execute(
                "SELECT * FROM semantic_document_values WHERE id=?", (identifier,)
            ).fetchone()
        )
        migrate_semantic_payloads(connection)
        attach_legacy(connection, stats.snapshot_id, "pkg/util.py", document)
    return stats, statements, document


def test_legacy_obligations_page_and_direct_lookup_keep_original_statements(repository, database):
    stats, statements, original = _legacy(repository, database)
    detail = entity_detail(database, stats.repository_id, "module:pkg/util.py", legacy_limit=2)
    legacy = detail["legacy_obligations"]
    assert detail["contracts"] == []
    assert legacy["total"] == 4 and legacy["returned"] == legacy["next_offset"] == 2
    assert legacy["readiness"] == "legacy_reused" and legacy["function_scope"] == "unknown"
    assert detail["counts"]["legacy_obligations_total"] == 4
    for index, item in enumerate(legacy["items"]):
        assert item["id"] == f"contract:pkg/util.py#legacy-{index}"
        assert not item["label"].startswith("Saved contract")
        expanded = entity_detail(database, stats.repository_id, item["id"])
        assert expanded["node"]["properties"]["statement"] == statements[index]
        assert expanded["node"]["provenance"]["annotation"]["document_id"] == original["id"]
        assert expanded["counts"]["connections_total"] == 1
    assert entity_page(database, stats.repository_id, kind="contract")["total_nodes"] == 0
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM graph_entities WHERE kind='contract'"
            ).fetchone()[0]
            == 0
        )
        assert (
            dict(
                connection.execute(
                    "SELECT * FROM semantic_document_values WHERE id=?", (original["id"],)
                ).fetchone()
            )
            == original
        )


def test_owner_neighborhood_lazily_reaches_obligations_without_inventing_function_bindings(
    repository, database
):
    stats, statements, _original = _legacy(repository, database)
    graph = neighborhood(
        database,
        stats.repository_id,
        "module:pkg/util.py",
        direction="outgoing",
        relationship_type="owns_contract",
    )
    assert len(graph["nodes"]) == 5 and len(graph["edges"]) == 4
    assert graph["counts_are_complete"] and not graph["bounded"]
    assert {node["id"] for node in graph["nodes"] if node["kind"] == "contract"} == {
        f"contract:pkg/util.py#legacy-{index}" for index in range(len(statements))
    }
    owner = neighborhood(
        database, stats.repository_id, "contract:pkg/util.py#legacy-0", direction="incoming"
    )
    assert {node["id"] for node in owner["nodes"]} == {
        "module:pkg/util.py",
        "contract:pkg/util.py#legacy-0",
    }
    function = entity_detail(database, stats.repository_id, "function:pkg/util.py#pkg.util.double")
    assert not function["contracts"] and not function["legacy_obligations"]["total"]


def test_legacy_obligation_paging_route_is_bounded_and_readable_after_cold_storage(
    repository, database
):
    stats, statements, _original = _legacy(repository, database)
    with TestClient(create_app(database=database, enable_mcp=False)) as client:
        result = client.get(
            "/api/graph/entity",
            params={
                "repository_id": stats.repository_id,
                "entity_id": "module:pkg/util.py",
                "legacy_offset": 2,
                "legacy_limit": 2,
            },
        )
        assert result.status_code == 200
        page = result.json()["legacy_obligations"]
        assert page["offset"] == 2 and page["next_offset"] is None
        assert [item["overview"] for item in page["items"]] == statements[2:]
        assert (
            client.get(
                "/api/graph/entity", params={"entity_id": "module:pkg/util.py", "legacy_limit": 101}
            ).status_code
            == 422
        )
