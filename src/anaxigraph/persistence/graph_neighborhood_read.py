"""Depth-capped graph expansion around one selected repository module."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Mapping

from anaxigraph.graph_contract import (
    GRAPH_NEIGHBORHOOD_VERSION,
    GraphNeighborhoodRequest,
    with_graph_telemetry,
)
from anaxigraph.persistence.graph_node_detail import read_graph_node_rows
from anaxigraph.persistence.graph_projection import install_graph_projection
from anaxigraph.persistence.graph_query_architecture import install_graph_architecture
from anaxigraph.persistence.graph_read import (
    graph_node,
    materialize_graph_edges,
    projected_graph_quality,
)


def read_graph_neighborhood(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot: Mapping[str, Any],
    request: GraphNeighborhoodRequest,
) -> dict[str, Any]:
    started = time.perf_counter()
    snapshot_id = int(snapshot["id"])
    reconstruction = install_graph_projection(connection, snapshot_id)
    assignments, parents, _frame = install_graph_architecture(
        connection, repository_id, snapshot_id
    )
    seed = _resolve_seed(connection, request.node)
    walk_sql, walk_parameters = _walk_sql(request, seed)
    total_nodes, node_rows = _neighborhood_nodes(
        connection,
        repository_id,
        snapshot_id,
        request,
        walk_sql,
        walk_parameters,
    )
    nodes = _materialize_nodes(node_rows, assignments, parents, seed)
    total_edges, edge_rows = _neighborhood_edges(connection, request, nodes)
    edges, external = materialize_graph_edges(edge_rows)
    response = _response(
        repository_id,
        snapshot,
        request,
        seed,
        total_nodes,
        total_edges,
        nodes,
        edges,
        external,
        projected_graph_quality(connection),
        reconstruction.as_dict(),
    )
    return with_graph_telemetry(response, started)


def empty_graph_neighborhood(repository_id: int) -> dict[str, Any]:
    started = time.perf_counter()
    response = {
        "contract_version": GRAPH_NEIGHBORHOOD_VERSION,
        "repository_id": repository_id,
        "snapshot": None,
        "seed": None,
        "counts": {"matching_nodes": 0, "matching_edges": 0},
        "nodes": [],
        "edges": [],
        "quality": {},
        "reconstruction": {},
    }
    return with_graph_telemetry(response, started)


def _resolve_seed(connection: sqlite3.Connection, value: str) -> int:
    row = connection.execute(
        "SELECT artifact_id FROM projected_file_versions WHERE path = ?",
        (value,),
    ).fetchone()
    if row is None and value.isdigit():
        row = connection.execute(
            "SELECT artifact_id FROM projected_file_versions WHERE artifact_id = ?",
            (int(value),),
        ).fetchone()
    if row is None:
        raise ValueError(f"graph node is not present in the snapshot: {value}")
    return int(row["artifact_id"])


def _walk_sql(
    request: GraphNeighborhoodRequest,
    seed: int,
) -> tuple[str, list[Any]]:
    neighbor = {
        "outgoing": "r.target_artifact_id",
        "incoming": "r.source_artifact_id",
        "both": (
            "CASE WHEN r.source_artifact_id = walk.artifact_id "
            "THEN r.target_artifact_id ELSE r.source_artifact_id END"
        ),
    }[request.direction]
    join = {
        "outgoing": "r.source_artifact_id = walk.artifact_id",
        "incoming": "r.target_artifact_id = walk.artifact_id",
        "both": (
            "r.source_artifact_id = walk.artifact_id OR r.target_artifact_id = walk.artifact_id"
        ),
    }[request.direction]
    relationship, parameters = _relationship_condition(request)
    sql = f"""
        walk(artifact_id, depth) AS (
            SELECT ?, 0
            UNION
            SELECT {neighbor}, walk.depth + 1
            FROM walk JOIN projected_relationships r ON {join}
            WHERE walk.depth < ? AND {neighbor} IS NOT NULL AND {relationship}
        )
    """
    return sql, [seed, request.depth, *parameters]


def _neighborhood_nodes(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    request: GraphNeighborhoodRequest,
    walk_sql: str,
    walk_parameters: list[Any],
) -> tuple[int, list[sqlite3.Row]]:
    total = int(
        connection.execute(
            f"WITH RECURSIVE {walk_sql} SELECT COUNT(DISTINCT artifact_id) FROM walk",
            walk_parameters,
        ).fetchone()[0]
    )
    selection = f"""
        RECURSIVE {walk_sql},
        selected AS (
            SELECT artifact_id, MIN(depth) AS depth FROM walk
            GROUP BY artifact_id ORDER BY depth, artifact_id LIMIT ?
        )
    """
    rows = read_graph_node_rows(
        connection,
        repository_id,
        snapshot_id,
        selection_sql=selection,
        selection_parameters=[*walk_parameters, request.node_limit],
        limit=request.node_limit,
        order_by="selected.depth, fv.path, fv.artifact_id",
    )
    return total, rows


def _materialize_nodes(
    rows: list[sqlite3.Row],
    assignments: dict[int, dict[str, Any]],
    parents: dict[str, str | None],
    seed: int,
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        artifact_id = int(row["artifact_id"])
        node = graph_node(
            dict(row),
            incoming=int(row["fan_in"]),
            outgoing=int(row["fan_out"]),
            coverage=row["line_coverage"],
            changes=int(row["change_count"]),
            assignment=assignments.get(artifact_id),
            parents=parents,
        )
        node.update(graph_depth=int(row["graph_depth"]), selected=artifact_id == seed)
        result.append(node)
    return result


def _neighborhood_edges(
    connection: sqlite3.Connection,
    request: GraphNeighborhoodRequest,
    nodes: list[dict[str, Any]],
) -> tuple[int, list[sqlite3.Row]]:
    ids = [int(node["id"]) for node in nodes]
    markers = ",".join("?" for _value in ids)
    relationship, relationship_parameters = _relationship_condition(request)
    target = (
        f"(target_artifact_id IN ({markers}) OR target_artifact_id IS NULL)"
        if request.include_external
        else f"target_artifact_id IN ({markers})"
    )
    where = f"source_artifact_id IN ({markers}) AND {target} AND {relationship}"
    parameters = [*ids, *ids, *relationship_parameters]
    total = int(
        connection.execute(
            f"SELECT COUNT(*) FROM projected_relationships r WHERE {where}", parameters
        ).fetchone()[0]
    )
    rows = connection.execute(
        f"""
        SELECT * FROM projected_relationships r WHERE {where}
        ORDER BY source_artifact_id, COALESCE(target_artifact_id, -1),
                 relationship_type, source_line, id LIMIT ?
        """,
        [*parameters, request.edge_limit],
    ).fetchall()
    return total, rows


def _relationship_condition(request: GraphNeighborhoodRequest) -> tuple[str, list[str]]:
    if not request.relationship_types:
        return "1 = 1", []
    markers = ",".join("?" for _value in request.relationship_types)
    return f"r.relationship_type IN ({markers})", list(request.relationship_types)


def _response(
    repository_id: int,
    snapshot: Mapping[str, Any],
    request: GraphNeighborhoodRequest,
    seed: int,
    total_nodes: int,
    total_edges: int,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    external: dict[str, dict[str, Any]],
    quality: dict[str, Any],
    reconstruction: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": GRAPH_NEIGHBORHOOD_VERSION,
        "repository_id": repository_id,
        "snapshot": dict(snapshot),
        "seed": seed,
        "query": {
            "node": request.node,
            "depth": request.depth,
            "direction": request.direction,
            "node_limit": request.node_limit,
            "edge_limit": request.edge_limit,
            "include_external": request.include_external,
            "relationship_types": list(request.relationship_types),
        },
        "counts": {
            "matching_nodes": total_nodes,
            "selected_edges": total_edges,
            "returned_internal_nodes": len(nodes),
            "returned_external_nodes": len(external),
            "returned_edges": len(edges),
            "omitted_nodes": total_nodes - len(nodes),
            "omitted_edges": total_edges - len(edges),
        },
        "nodes": [*nodes, *external.values()],
        "edges": edges,
        "quality": quality,
        "reconstruction": reconstruction,
    }
