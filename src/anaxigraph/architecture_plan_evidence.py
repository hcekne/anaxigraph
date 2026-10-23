"""Source-aware planning evidence projected from the canonical semantic graph."""

from __future__ import annotations

from typing import Any

from anaxigraph.architecture_charter_corrections import declared_context
from anaxigraph.knowledge_sync import sync_knowledge
from anaxigraph.knowledge_values import edge_value, graph_select, node_value
from anaxigraph.persistence.pattern_review_references import expanded_pattern_review
from anaxigraph.semantic_fresh_eyes_functional import semantic_digest


def current_graph_evidence(
    connection: Any, repository_id: int, snapshot_id: int, charter: Any
) -> tuple[dict, dict]:
    sync_knowledge(connection, snapshot_id)
    nodes = _nodes(connection, snapshot_id)
    edges = _edges(connection, snapshot_id, nodes)
    totals = dict(
        connection.execute(
            "SELECT kind,COUNT(*) FROM graph_entities WHERE snapshot_id=? GROUP BY kind",
            (snapshot_id,),
        ).fetchall()
    )
    current = {
        "architecture_charter": charter["value"],
        "semantic_graph": {
            "nodes": nodes,
            "edges": edges,
            "totals_by_kind": totals,
            "returned_nodes": len(nodes),
            "returned_edges": len(edges),
            "selection": "bounded responsibility and dependency witnesses",
        },
        "pattern_reviews": _patterns(connection, snapshot_id),
        "declared_context": declared_context(connection, repository_id, charter["value"]),
    }
    manifest = {
        "snapshot_id": snapshot_id,
        "charter_document_id": charter["id"],
        "graph_node_ids": [node["id"] for node in nodes],
        "graph_edge_ids": [edge["id"] for edge in edges],
        "totals_by_kind": totals,
        "packet_fingerprint": semantic_digest(current),
    }
    return current, manifest


def _nodes(connection: Any, snapshot_id: int) -> list[dict]:
    result = []
    for kinds, limit in (
        ("'capability','area'", 24),
        ("'module'", 32),
        ("'contract','interface'", 40),
        ("'function'", 24),
    ):
        rows = connection.execute(
            graph_select(detail=True) + f" WHERE g.snapshot_id=? AND g.kind IN ({kinds}) "
            "ORDER BY g.fan_in+g.fan_out DESC,g.entity_id LIMIT ?",
            (snapshot_id, limit),
        ).fetchall()
        result.extend(_planning_node(node_value(row, detail=True)) for row in rows)
    return result


def _edges(connection: Any, snapshot_id: int, nodes: list[dict]) -> list[dict]:
    identifiers = [node["id"] for node in nodes]
    if not identifiers:
        return []
    markers = ",".join("?" for _ in identifiers)
    rows = connection.execute(
        f"SELECT * FROM graph_connections WHERE snapshot_id=? AND source_id IN ({markers}) "
        f"AND target_id IN ({markers}) ORDER BY edge_id LIMIT 200",
        (snapshot_id, *identifiers, *identifiers),
    ).fetchall()
    return [edge_value(row) for row in rows]


def _planning_node(node):
    """Keep qualifications once; machine-local storage IDs add no design evidence."""
    return {
        key: value
        for key, value in node.items()
        if key
        in {
            "id",
            "kind",
            "path",
            "label",
            "overview",
            "detail",
            "metrics",
            "placement",
            "readiness",
            "properties",
        }
    }


def _patterns(connection: Any, snapshot_id: int) -> list[dict]:
    rows = connection.execute(
        "SELECT DISTINCT sd.id,sd.repository_id,sd.input_hash,sd.scope_key,sd.value_json FROM semantic_scope_states ss "
        "JOIN semantic_document_values sd ON sd.id=ss.context_document_id "
        "WHERE ss.snapshot_id=? AND ss.scope_type='pattern' AND ss.status='current' "
        "ORDER BY ss.scope_key",
        (snapshot_id,),
    ).fetchall()
    return [
        {
            "document_id": row["id"],
            "scope": row["scope_key"],
            "fingerprint": row["input_hash"],
            "value": _planning_review(expanded_pattern_review(connection, dict(row))),
        }
        for row in rows
    ]


def _planning_review(review):
    evaluation = review.get("evaluation") or {}
    fields = {
        "pattern_key",
        "target_key",
        "summary",
        "presence",
        "recommendation",
        "pros",
        "cons",
        "placements",
        "invariants",
        "prerequisites",
        "invalidation_conditions",
        "counter_evidence",
    }
    return {
        "verdict": review.get("verdict"),
        "summary": review.get("summary"),
        "evaluation": {key: value for key, value in evaluation.items() if key in fields},
        "ratings": {key: score.get("value") for key, score in evaluation.get("scores", {}).items()},
        "issues": review.get("issues", []),
        "full_review_available": True,
    }
