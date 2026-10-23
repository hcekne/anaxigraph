"""Indexed, revision-qualified entity pages and global graph search."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.knowledge_schema import KNOWLEDGE_VERSION
from anaxigraph.knowledge_sync import graph_read
from anaxigraph.knowledge_unresolved_query import unresolved_page
from anaxigraph.knowledge_values import (
    EVIDENCE_STATES,
    edge_value,
    evidence_predicate,
    graph_select,
    node_value,
)
from anaxigraph.persistence.git_metrics import git_metrics_context

_SORTS = {
    "path": "g.path",
    "label": "canonical_label",
    "summary": "canonical_overview",
    "overview": "canonical_overview",
    "lines_of_code": "g.lines_of_code",
    "function_count": "g.function_count",
    "interface_count": "interface_count",
    "contract_count": "contract_count",
    "complexity": "g.complexity",
    "fan_in": "g.fan_in",
    "fan_out": "g.fan_out+COALESCE(json_extract(g.properties_json,'$.unresolved_target_count'),0)",
    "coupling": "g.fan_in+g.fan_out+COALESCE(json_extract(g.properties_json,'$.unresolved_target_count'),0)",
    "architecture_area": "canonical_area",
    "line_coverage": "g.line_coverage",
    "change_count": "g.change_count",
    "first_changed_at": "g.first_changed_at",
    "last_commit_at": "g.last_commit_at",
}


def graph_context(connection, repository_id, snapshot_id, map_layer="current"):
    snapshot = dict(
        connection.execute(
            "SELECT * FROM snapshots WHERE id=? AND repository_id=?", (snapshot_id, repository_id)
        ).fetchone()
    )
    metadata = json.loads(snapshot.pop("metadata_json", None) or "{}")
    repository = connection.execute(
        "SELECT path FROM repositories WHERE id=?", (repository_id,)
    ).fetchone()
    semantic = connection.execute(
        "SELECT COUNT(*),COALESCE(MAX(last_checked_at),''),COALESCE(MAX(context_document_id),0) "
        "FROM semantic_scope_states WHERE snapshot_id=?",
        (snapshot_id,),
    ).fetchone()
    return {
        **_structural_context(metadata),
        "semantic_revision": list(semantic),
        "git_metrics": git_metrics_context(connection, repository_id),
        "virtual_entity_kinds": ["unresolved"],
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "snapshot": snapshot,
        "checkout_path": repository[0],
        "graph_kind": "observed",
        "graph_subject": "observed",
        "map_layer": map_layer,
        "revision": snapshot["content_fingerprint"],
        "contract_version": KNOWLEDGE_VERSION,
    }


def _structural_context(metadata):
    reindex = metadata.get("structural_cache_reindex")
    if not reindex:
        return {}
    return {
        "structural_analysis": {
            "reindexed": True,
            "scope": "matching_files",
            "reindexed_files": reindex["reindexed_files"],
            "interpretation": "Matching source files reanalyzed with current extractor.",
        }
    }


def entity_page(database, repository_id, snapshot_id=None, **filters) -> dict[str, Any]:
    limit = min(1000, max(1, int(filters.get("limit", 100))))
    offset = max(0, int(filters.get("offset", 0)))
    sort = filters.get("sort", "path")
    if sort not in _SORTS:
        raise ValueError("Unsupported entity sort")
    direction = str(filters.get("direction", "asc")).lower()
    if direction not in {"asc", "desc"}:
        raise ValueError("Sort direction must be asc or desc")
    map_layer = filters.get("map_layer", "current")
    if map_layer not in {"current", "responsibility", "declared", "path"}:
        raise ValueError("Unsupported graph grouping layer")
    with graph_read(database, repository_id, snapshot_id) as (connection, snapshot_id):
        where, parameters = _where(snapshot_id, filters)
        if filters.get("kind") == "unresolved" or filters.get("evidence_state") == "unresolved":
            return unresolved_page(
                connection,
                graph_context(connection, repository_id, snapshot_id, map_layer),
                **filters,
            )
        select = graph_select(map_layer=map_layer)
        total = connection.execute(
            f"SELECT COUNT(*) FROM ({select} WHERE {where})", parameters
        ).fetchone()[0]
        order = _SORTS[sort]
        rows = connection.execute(
            f"{select} WHERE {where} ORDER BY {order} IS NULL,{order} {direction},g.entity_id "
            "LIMIT ? OFFSET ?",
            (*parameters, limit, offset),
        ).fetchall()
        nodes = [node_value(row) for row in rows]
        edges, total_edges = _page_edges(
            connection, snapshot_id, nodes, limit * 2, filters.get("evidence_state", "")
        )
        return {
            "context": graph_context(connection, repository_id, snapshot_id, map_layer),
            "nodes": nodes,
            "edges": edges,
            "total_nodes": total,
            "returned_nodes": len(nodes),
            "total_edges": total_edges,
            "returned_edges": len(edges),
            "next_offset": offset + limit if offset + limit < total else None,
            "facets": _facets(connection, snapshot_id, map_layer),
        }


def _where(snapshot, filters):
    clauses, parameters = ["g.snapshot_id=?"], [snapshot]
    evidence_state = filters.get("evidence_state", "")
    if evidence_state not in EVIDENCE_STATES:
        raise ValueError("Unsupported graph evidence state")
    if evidence_state:
        clauses.append("(" + evidence_predicate("g") + ")=?")
        parameters.append(evidence_state)
    for key in ("kind", "area", "subsystem", "language"):
        if filters.get(key):
            column = f"canonical_{key}" if key in {"area", "subsystem"} else f"g.{key}"
            clauses.append(f"{column}=?")
            parameters.append(filters[key])
    if not filters.get("include_reference", False):
        clauses.append("g.reference=0")
    if filters.get("scope"):
        clauses.append("(g.parent_id=? OR g.path=? OR canonical_area=?)")
        parameters.extend([filters["scope"]] * 3)
    if filters.get("q"):
        clauses.append(
            "(g.label LIKE ? OR g.path LIKE ? OR g.entity_id LIKE ? OR canonical_overview LIKE ?)"
        )
        parameters.extend(["%" + filters["q"] + "%"] * 4)
    return " AND ".join(clauses), parameters


def _page_edges(connection, snapshot, nodes, limit, evidence_state=""):
    if not nodes:
        return [], 0
    ids = [node["id"] for node in nodes]
    selected = "WITH page_nodes AS (SELECT node_id FROM graph_entities WHERE snapshot_id=? AND entity_id IN (SELECT value FROM json_each(?))) "
    where = "snapshot_id=? AND source_node IN (SELECT node_id FROM page_nodes) AND target_node IN (SELECT node_id FROM page_nodes)"
    if evidence_state:
        where += " AND (" + evidence_predicate(edges=True, physical=True) + ")=?"
    parameters = (snapshot, json.dumps(ids), snapshot)
    parameters += (evidence_state,) if evidence_state else ()
    total = connection.execute(
        selected + "SELECT COUNT(*) FROM graph_links WHERE " + where, parameters
    ).fetchone()[0]
    rows = connection.execute(
        selected
        + "SELECT * FROM graph_connections WHERE snapshot_id=? AND edge_id IN (SELECT edge_id FROM graph_links WHERE "
        + where
        + " ORDER BY edge_id LIMIT ?) ORDER BY edge_id",
        (*parameters[:2], snapshot, *parameters[2:], limit),
    ).fetchall()
    return [edge_value(row) for row in rows], total


def _facets(connection, snapshot, map_layer):
    fallback_area = "area" if map_layer == "current" else "'unconfigured'"
    fallback_subsystem = "subsystem" if map_layer == "current" else "'unconfigured'"
    area = (
        "COALESCE(json_extract(properties_json,'$.architecture_layers."
        + map_layer
        + ".area'),"
        + fallback_area
        + ")"
    )
    subsystem = (
        "COALESCE(json_extract(properties_json,'$.architecture_layers."
        + map_layer
        + ".subsystem'),"
        + fallback_subsystem
        + ")"
    )
    return {
        plural: [
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT {column} FROM graph_entities WHERE snapshot_id=? AND kind='module' "
                f"AND {column}!='' ORDER BY {column}",
                (snapshot,),
            )
        ]
        for plural, column in (
            ("areas", area),
            ("subsystems", subsystem),
            ("languages", "language"),
        )
    }
