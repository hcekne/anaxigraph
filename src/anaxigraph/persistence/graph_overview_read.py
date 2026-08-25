"""Architecture-first graph aggregates for large-repository entry views."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Mapping
from urllib.parse import quote

from anaxigraph.graph_contract import (
    GRAPH_OVERVIEW_VERSION,
    MAX_GRAPH_AGGREGATE_EDGE_LIMIT,
    MAX_GRAPH_GROUP_LIMIT,
    with_graph_telemetry,
)
from anaxigraph.persistence.graph_projection import install_graph_projection
from anaxigraph.persistence.graph_query_architecture import install_graph_architecture
from anaxigraph.persistence.graph_read import projected_graph_quality


def empty_graph_overview(repository_id: int, level: str) -> dict[str, Any]:
    started = time.perf_counter()
    response = {
        "contract_version": GRAPH_OVERVIEW_VERSION,
        "repository_id": repository_id,
        "snapshot": None,
        "level": level,
        "counts": {"groups": 0, "aggregate_edges": 0},
        "nodes": [],
        "edges": [],
        "quality": {},
        "reconstruction": {},
    }
    return with_graph_telemetry(response, started)


def read_graph_overview(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot: Mapping[str, Any],
    *,
    level: str,
    group_limit: int,
    edge_limit: int,
    include_external: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    _validate_overview_request(level, group_limit, edge_limit)
    snapshot_id = int(snapshot["id"])
    reconstruction = install_graph_projection(connection, snapshot_id)
    install_graph_architecture(connection, repository_id, snapshot_id)
    total_groups, groups = _group_rows(connection, level, group_limit)
    total_edges, edges = _aggregate_edge_rows(
        connection,
        level,
        edge_limit,
        include_external=include_external,
    )
    response = {
        "contract_version": GRAPH_OVERVIEW_VERSION,
        "repository_id": repository_id,
        "snapshot": dict(snapshot),
        "level": level,
        "counts": {
            "groups": total_groups,
            "aggregate_edges": total_edges,
            "returned_groups": len(groups),
            "returned_aggregate_edges": len(edges),
            "omitted_groups": total_groups - len(groups),
            "omitted_aggregate_edges": total_edges - len(edges),
        },
        "nodes": [_group_node(row, level) for row in groups],
        "edges": [_aggregate_edge(row, level) for row in edges],
        "quality": projected_graph_quality(connection),
        "reconstruction": reconstruction.as_dict(),
    }
    return with_graph_telemetry(response, started)


def _validate_overview_request(level: str, group_limit: int, edge_limit: int) -> None:
    if level not in {"area", "subsystem"}:
        raise ValueError("graph overview level must be area or subsystem")
    if not 1 <= group_limit <= MAX_GRAPH_GROUP_LIMIT:
        raise ValueError(f"group_limit must be between 1 and {MAX_GRAPH_GROUP_LIMIT}")
    if not 1 <= edge_limit <= MAX_GRAPH_AGGREGATE_EDGE_LIMIT:
        raise ValueError(f"edge_limit must be between 1 and {MAX_GRAPH_AGGREGATE_EDGE_LIMIT}")


def _group_rows(
    connection: sqlite3.Connection,
    level: str,
    limit: int,
) -> tuple[int, list[sqlite3.Row]]:
    total = int(
        connection.execute(f"SELECT COUNT(DISTINCT {level}) FROM graph_architecture").fetchone()[0]
    )
    rows = connection.execute(
        f"""
        SELECT {level} AS name, COUNT(*) AS files,
               COALESCE(SUM(fv.lines_of_code), 0) AS lines_of_code,
               COALESCE(SUM(fv.complexity), 0) AS complexity,
               COUNT(DISTINCT ga.source) AS source_count,
               MIN(ga.source) AS source
        FROM graph_architecture ga
        JOIN projected_file_versions fv ON fv.artifact_id = ga.artifact_id
        GROUP BY {level}
        ORDER BY lines_of_code DESC, files DESC, name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return total, rows


def _aggregate_edge_rows(
    connection: sqlite3.Connection,
    level: str,
    limit: int,
    *,
    include_external: bool,
) -> tuple[int, list[sqlite3.Row]]:
    target = f"COALESCE(target.{level}, 'external')" if include_external else f"target.{level}"
    condition = "1 = 1" if include_external else "r.target_artifact_id IS NOT NULL"
    grouped = f"""
        SELECT source.{level} AS source, {target} AS target,
               r.relationship_type, COUNT(*) AS edge_count,
               COALESCE(SUM(r.weight), 0) AS weight
        FROM projected_relationships r
        JOIN graph_architecture source ON source.artifact_id = r.source_artifact_id
        LEFT JOIN graph_architecture target ON target.artifact_id = r.target_artifact_id
        WHERE {condition}
        GROUP BY source.{level}, {target}, r.relationship_type
    """
    total = int(connection.execute(f"SELECT COUNT(*) FROM ({grouped})").fetchone()[0])
    rows = connection.execute(
        f"""
        SELECT * FROM ({grouped})
        ORDER BY edge_count DESC, weight DESC, source, target, relationship_type
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return total, rows


def _group_node(row: sqlite3.Row, level: str) -> dict[str, Any]:
    name = str(row["name"])
    return {
        "id": f"{level}:{quote(name, safe='._-')}",
        "name": name,
        "level": level,
        "files": int(row["files"]),
        "lines_of_code": int(row["lines_of_code"]),
        "complexity": float(row["complexity"]),
        "source": "mixed" if int(row["source_count"]) > 1 else str(row["source"]),
    }


def _aggregate_edge(row: sqlite3.Row, level: str) -> dict[str, Any]:
    source = str(row["source"])
    target = str(row["target"])
    relationship = str(row["relationship_type"])
    return {
        "id": (f"{level}:{quote(source, safe='._-')}->{quote(target, safe='._-')}:{relationship}"),
        "source": f"{level}:{quote(source, safe='._-')}",
        "target": f"{level}:{quote(target, safe='._-')}",
        "type": relationship,
        "count": int(row["edge_count"]),
        "weight": float(row["weight"]),
    }
