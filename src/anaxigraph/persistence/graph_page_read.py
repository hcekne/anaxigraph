"""Bounded, cursor-based graph reads over one canonical snapshot projection."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Mapping

from anaxigraph.graph_contract import (
    GRAPH_QUERY_VERSION,
    GraphPageRequest,
    next_graph_cursor,
    resolve_graph_cursor,
    with_graph_telemetry,
)
from anaxigraph.persistence.graph_node_detail import read_graph_node_rows
from anaxigraph.persistence.graph_projection import install_graph_projection
from anaxigraph.persistence.graph_query_architecture import install_graph_architecture
from anaxigraph.persistence.graph_query_sql import (
    eligible_nodes_sql,
    relationship_filter_sql,
)
from anaxigraph.persistence.graph_read import (
    graph_node,
    materialize_graph_edges,
    projected_graph_quality,
)


@dataclass(frozen=True, slots=True)
class _PageState:
    matching_nodes: int
    matching_edges: int
    internal_nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    external_nodes: dict[str, dict[str, Any]]
    next_cursor: str | None


def read_graph_page(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot: Mapping[str, Any],
    request: GraphPageRequest | None,
    *,
    include_external: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    request = request or GraphPageRequest(include_external=include_external)
    snapshot_id = int(snapshot["id"])
    cursor = resolve_graph_cursor(request, snapshot_id)
    reconstruction = install_graph_projection(connection, snapshot_id)
    assignments, parents = install_graph_architecture(connection, repository_id, snapshot_id)
    state = _read_page_state(
        connection,
        repository_id,
        snapshot_id,
        request,
        cursor.node_offset,
        cursor.edge_offset,
        assignments,
        parents,
    )
    return _graph_response(
        repository_id,
        snapshot,
        request,
        cursor.node_offset,
        cursor.edge_offset,
        state,
        projected_graph_quality(connection),
        reconstruction.as_dict(),
        started,
    )


def _read_page_state(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    request: GraphPageRequest,
    node_offset: int,
    edge_offset: int,
    assignments: dict[int, dict[str, Any]],
    parents: dict[str, str | None],
) -> _PageState:
    eligible_sql, eligible_parameters = eligible_nodes_sql(request, repository_id, snapshot_id)
    matching_nodes, internal_nodes = _read_nodes(
        connection,
        repository_id,
        snapshot_id,
        eligible_sql,
        eligible_parameters,
        request,
        node_offset,
        assignments,
        parents,
    )
    matching_edges, edge_rows = _edge_rows(
        connection,
        eligible_sql,
        eligible_parameters,
        request,
        edge_offset,
    )
    _validate_cursor_position(node_offset, edge_offset, matching_nodes, matching_edges)
    edges, external_nodes = materialize_graph_edges(edge_rows)
    next_cursor = _next_cursor(
        request,
        snapshot_id,
        (node_offset, edge_offset),
        (len(internal_nodes), len(edges)),
        (matching_nodes, matching_edges),
    )
    return _PageState(
        matching_nodes,
        matching_edges,
        internal_nodes,
        edges,
        external_nodes,
        next_cursor,
    )


def empty_graph_page(repository_id: int) -> dict[str, Any]:
    started = time.perf_counter()
    response = {
        "contract_version": GRAPH_QUERY_VERSION,
        "repository_id": repository_id,
        "snapshot": None,
        "query": GraphPageRequest().filter_payload(),
        "counts": {"matching_nodes": 0, "matching_edges": 0},
        "page": {"node_offset": 0, "edge_offset": 0},
        "next_cursor": None,
        "nodes": [],
        "edges": [],
        "quality": {},
        "reconstruction": {},
    }
    return with_graph_telemetry(response, started)


def _graph_response(
    repository_id: int,
    snapshot: Mapping[str, Any],
    request: GraphPageRequest,
    node_offset: int,
    edge_offset: int,
    state: _PageState,
    quality: dict[str, Any],
    reconstruction: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    response = {
        "contract_version": GRAPH_QUERY_VERSION,
        "repository_id": repository_id,
        "snapshot": dict(snapshot),
        "query": request.filter_payload(),
        "counts": {
            "matching_nodes": state.matching_nodes,
            "matching_edges": state.matching_edges,
            "page_internal_nodes": len(state.internal_nodes),
            "page_external_nodes": len(state.external_nodes),
            "page_edges": len(state.edges),
        },
        "page": {
            "node_offset": node_offset,
            "edge_offset": edge_offset,
            "node_limit": request.node_limit,
            "edge_limit": request.edge_limit,
        },
        "next_cursor": state.next_cursor,
        "nodes": [*state.internal_nodes, *state.external_nodes.values()],
        "edges": state.edges,
        "quality": quality,
        "reconstruction": reconstruction,
    }
    return with_graph_telemetry(response, started)


def _read_nodes(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    eligible_sql: str,
    eligible_parameters: list[Any],
    request: GraphPageRequest,
    offset: int,
    assignments: dict[int, dict[str, Any]],
    parents: dict[str, str | None],
) -> tuple[int, list[dict[str, Any]]]:
    total = _node_count(connection, eligible_sql, eligible_parameters)
    rows = _node_rows(
        connection,
        repository_id,
        snapshot_id,
        eligible_sql,
        eligible_parameters,
        request,
        offset,
    )
    nodes = [
        graph_node(
            dict(row),
            incoming=int(row["fan_in"]),
            outgoing=int(row["fan_out"]),
            coverage=row["line_coverage"],
            changes=int(row["change_count"]),
            assignment=assignments.get(int(row["artifact_id"])),
            parents=parents,
        )
        for row in rows
    ]
    return total, nodes


def _node_count(
    connection: sqlite3.Connection,
    eligible_sql: str,
    parameters: list[Any],
) -> int:
    row = connection.execute(
        f"WITH {eligible_sql} SELECT COUNT(*) FROM eligible", parameters
    ).fetchone()
    return int(row[0])


def _node_rows(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    eligible_sql: str,
    parameters: list[Any],
    request: GraphPageRequest,
    offset: int,
) -> list[sqlite3.Row]:
    selection = f"{eligible_sql}, selected AS (SELECT artifact_id, 0 AS depth FROM eligible)"
    return read_graph_node_rows(
        connection,
        repository_id,
        snapshot_id,
        selection_sql=selection,
        selection_parameters=parameters,
        limit=request.node_limit,
        offset=offset,
    )


def _edge_rows(
    connection: sqlite3.Connection,
    eligible_sql: str,
    eligible_parameters: list[Any],
    request: GraphPageRequest,
    offset: int,
) -> tuple[int, list[sqlite3.Row]]:
    relationship_filter, relationship_parameters = relationship_filter_sql(request)
    target = (
        "(r.target_artifact_id IS NULL OR target.artifact_id IS NOT NULL)"
        if request.include_external
        else "target.artifact_id IS NOT NULL"
    )
    parameters = [*eligible_parameters, *relationship_parameters]
    total = int(
        connection.execute(
            f"""
            WITH {eligible_sql}
            SELECT COUNT(*) FROM projected_relationships r
            JOIN eligible source ON source.artifact_id = r.source_artifact_id
            LEFT JOIN eligible target ON target.artifact_id = r.target_artifact_id
            WHERE {target} AND {relationship_filter}
            """,
            parameters,
        ).fetchone()[0]
    )
    rows = connection.execute(
        f"""
        WITH {eligible_sql}
        SELECT r.* FROM projected_relationships r
        JOIN eligible source ON source.artifact_id = r.source_artifact_id
        LEFT JOIN eligible target ON target.artifact_id = r.target_artifact_id
        WHERE {target} AND {relationship_filter}
        ORDER BY r.source_artifact_id, COALESCE(r.target_artifact_id, -1),
                 COALESCE(r.target_external, ''), r.relationship_type, r.source_line, r.id
        LIMIT ? OFFSET ?
        """,
        [*parameters, request.edge_limit, offset],
    ).fetchall()
    return total, rows


def _next_cursor(
    request: GraphPageRequest,
    snapshot_id: int,
    offsets: tuple[int, int],
    returned: tuple[int, int],
    totals: tuple[int, int],
) -> str | None:
    node_offset, edge_offset = offsets
    returned_nodes, returned_edges = returned
    matching_nodes, matching_edges = totals
    next_node_offset = min(matching_nodes, node_offset + returned_nodes)
    next_edge_offset = min(matching_edges, edge_offset + returned_edges)
    if next_node_offset < matching_nodes or next_edge_offset < matching_edges:
        return next_graph_cursor(
            request,
            snapshot_id,
            node_offset=next_node_offset,
            edge_offset=next_edge_offset,
        )
    return None


def _validate_cursor_position(
    node_offset: int,
    edge_offset: int,
    matching_nodes: int,
    matching_edges: int,
) -> None:
    if node_offset > matching_nodes or edge_offset > matching_edges:
        raise ValueError("graph cursor is outside the matching result set")
    if (
        node_offset == matching_nodes
        and edge_offset == matching_edges
        and (matching_nodes or matching_edges)
    ):
        raise ValueError("graph cursor is already at the end of the matching result set")
