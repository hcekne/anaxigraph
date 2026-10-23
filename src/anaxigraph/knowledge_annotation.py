"""One compact semantic graph annotation per changed source module."""

from __future__ import annotations

import json

from anaxigraph.knowledge_edges import insert_edge
from anaxigraph.knowledge_nodes import entity_id, insert_entity
from anaxigraph.persistence.search_read import refresh_search_projection


def attach_annotation(connection, job, document_id, value) -> None:
    snapshot, path = int(job["snapshot_id"]), str(job["scope_key"])
    _retire_previous_links(connection, snapshot, path)
    _attach(connection, snapshot, entity_id("module", path), document_id, "$")
    for index, function in enumerate(value.get("functions", [])):
        _attach(
            connection,
            snapshot,
            entity_id("function", path, function["qualified_name"]),
            document_id,
            f"$.functions[{index}]",
        )
    for index, contract in enumerate(value.get("contracts", [])):
        _contract(connection, snapshot, path, document_id, index, contract)
    for index, capability in enumerate(value.get("capabilities", [])):
        _capability(connection, snapshot, path, document_id, index, capability)


def _retire_previous_links(connection, snapshot, path):
    connection.execute(
        "DELETE FROM graph_entities WHERE snapshot_id=? AND path=? AND kind IN ('contract','capability')",
        (snapshot, path),
    )


def complete_annotation(connection, job, document_id, value, now):
    attach_annotation(connection, job, document_id, value)
    connection.execute(
        """UPDATE semantic_scope_states SET status='current',
        intrinsic_document_id=?,context_document_id=?,reason=?,last_checked_at=?
        WHERE snapshot_id=? AND scope_type='module' AND scope_key=?""",
        (
            document_id,
            document_id,
            "Graph annotation matches current source",
            now,
            job["snapshot_id"],
            job["scope_key"],
        ),
    )
    refresh_search_projection(
        connection,
        int(job["repository_id"]),
        int(job["snapshot_id"]),
        artifact_ids=(int(job["artifact_id"]),),
    )


def _attach(connection, snapshot, identifier, document_id, selector):
    connection.execute(
        """UPDATE graph_entities SET annotation_id=?,annotation_selector=?
        WHERE snapshot_id=? AND entity_id=?""",
        (document_id, selector, snapshot, identifier),
    )


def _contract(connection, snapshot, path, document, index, contract):
    identifier = entity_id("contract", path, contract["name"])
    insert_entity(
        connection,
        snapshot,
        {
            "entity_id": identifier,
            "kind": "contract",
            "label": contract["name"],
            "path": path,
            "parent_id": entity_id("module", path),
            "annotation_id": document,
            "annotation_selector": f"$.contracts[{index}]",
            "provenance_json": json.dumps({"method": "inferred", "verification": "unverified"}),
        },
    )
    owners = contract.get("functions") or []
    for name in owners:
        owner = entity_id("function", path, name)
        if connection.execute(
            "SELECT 1 FROM graph_entities WHERE snapshot_id=? AND entity_id=?", (snapshot, owner)
        ).fetchone():
            insert_edge(
                connection,
                snapshot,
                owner,
                identifier,
                "requires_contract",
                evidence=contract.get("evidence"),
                method="inferred",
            )
    insert_edge(
        connection,
        snapshot,
        entity_id("module", path),
        identifier,
        "owns_contract",
        method="inferred",
    )


def _capability(connection, snapshot, path, document, index, capability):
    identifier = entity_id("capability", path, capability["name"])
    insert_entity(
        connection,
        snapshot,
        {
            "entity_id": identifier,
            "kind": "capability",
            "label": capability["name"],
            "path": path,
            "annotation_id": document,
            "annotation_selector": f"$.capabilities[{index}]",
            "provenance_json": json.dumps({"method": "inferred", "verification": "unverified"}),
        },
    )
    insert_edge(
        connection,
        snapshot,
        entity_id("module", path),
        identifier,
        "fulfills_capability",
        method="inferred",
    )
