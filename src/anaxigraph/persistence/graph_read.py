"""Canonical graph read model for dashboard, REST, and MCP consumers."""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any, Mapping

from anaxigraph.persistence.semantic_taxonomy_read import taxonomy_assignments
from anaxigraph.persistence.temporal_reads import (
    snapshot_files_with_diagnostics,
    snapshot_relationship_edges_with_diagnostics,
)
from anaxigraph.relationships import (
    EXTERNAL,
    RESOLUTION_STATUSES,
    RESOLVED_INTERNAL,
    relationship_metadata,
    relationship_quality,
    resolution_status,
)


def read_graph(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot: Mapping[str, Any],
    *,
    include_external: bool,
) -> dict[str, Any]:
    snapshot_id = int(snapshot["id"])
    files, file_diagnostics = snapshot_files_with_diagnostics(
        connection,
        snapshot_id,
        expand_metadata=False,
    )
    relationships, relationship_diagnostics = snapshot_relationship_edges_with_diagnostics(
        connection, snapshot_id
    )
    relationships = [_annotated_relationship(edge) for edge in relationships]
    nodes = _nodes(connection, repository_id, snapshot_id, files, relationships)
    edges, external_nodes = _materialize_edges(
        relationships,
        include_external=include_external,
    )
    if include_external:
        nodes.extend(
            _external_node(node_id, label, status)
            for node_id, (label, status) in external_nodes.items()
        )
    return {
        "snapshot": dict(snapshot),
        "nodes": nodes,
        "edges": edges,
        "quality": _quality(files, relationships),
        "reconstruction": {
            "snapshot_id": snapshot_id,
            "files": file_diagnostics.as_dict(),
            "relationships": relationship_diagnostics.as_dict(),
            "symbol_count": 0,
        },
    }


def graph_quality(
    connection: sqlite3.Connection,
    relationship_rows: list[dict[str, Any]] | list[sqlite3.Row],
) -> dict[str, Any]:
    files = [
        dict(row)
        for row in connection.execute(
            "SELECT analyzer, parse_error FROM projected_file_versions"
        ).fetchall()
    ]
    return _quality(files, [dict(row) for row in relationship_rows])


def decode_relationship(value: dict[str, Any]) -> dict[str, Any]:
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        metadata = relationship_metadata(value)
    status = value.get("resolution_status")
    if status not in RESOLUTION_STATUSES:
        status = resolution_status(value)
    value["resolution_status"] = status
    value["candidate_paths"] = metadata.get("candidate_paths", [])
    value["metadata"] = metadata
    value.pop("metadata_json", None)
    return value


def _nodes(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    files: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    incoming = Counter(
        int(edge["target_artifact_id"])
        for edge in relationships
        if edge["target_artifact_id"] is not None
    )
    outgoing = Counter(int(edge["source_artifact_id"]) for edge in relationships)
    coverage = _coverage_by_artifact(connection, snapshot_id)
    changes = _changes_by_path(connection, repository_id)
    assignments = taxonomy_assignments(connection, snapshot_id)
    parents = _group_parents(connection, repository_id)
    return [
        _node(
            file,
            incoming=incoming[int(file["artifact_id"])],
            outgoing=outgoing[int(file["artifact_id"])],
            coverage=coverage.get(int(file["artifact_id"])),
            changes=changes.get(str(file["path"]), 0),
            assignment=assignments.get(int(file["artifact_id"])),
            parents=parents,
        )
        for file in files
    ]


def _node(
    file: dict[str, Any],
    *,
    incoming: int,
    outgoing: int,
    coverage: float | None,
    changes: int,
    assignment: dict[str, Any] | None,
    parents: dict[str, str | None],
) -> dict[str, Any]:
    policy = file.get("declared_group")
    inferred = file.get("inferred_group") or "ungrouped"
    fallback = policy or inferred
    fallback_area = _root_group(str(fallback), parents)
    return {
        "id": file["artifact_id"],
        "path": file["path"],
        "language": file["language"],
        "lines_of_code": file["lines_of_code"],
        "complexity": file["complexity"],
        "summary": file["summary"],
        "declared_group": policy,
        "inferred_group": inferred,
        "architecture_area": assignment["area"] if assignment else fallback_area,
        "architecture_subsystem": assignment["subsystem"] if assignment else fallback,
        "architecture_layer": "semantic" if assignment else "effective",
        "architecture_layers": {
            "semantic": assignment,
            "policy": (
                {
                    "area": _root_group(str(policy), parents),
                    "subsystem": policy,
                    "source": "configured policy",
                }
                if policy
                else None
            ),
            "inferred": {
                "area": inferred,
                "subsystem": inferred,
                "source": "deterministic fallback",
            },
        },
        "analysis_status": file["analysis_status"],
        "last_changed_at": file["last_changed_at"],
        "fan_in": incoming,
        "fan_out": outgoing,
        "line_coverage": coverage,
        "change_count": changes,
    }


def _group_parents(connection: sqlite3.Connection, repository_id: int) -> dict[str, str | None]:
    rows = connection.execute(
        """
        SELECT name, parent_name FROM groups WHERE repository_id = ?
        ORDER BY CASE source WHEN 'declared' THEN 0 ELSE 1 END
        """,
        (repository_id,),
    ).fetchall()
    result: dict[str, str | None] = {}
    for row in rows:
        result.setdefault(str(row["name"]), row["parent_name"])
    return result


def _root_group(group: str, parents: dict[str, str | None]) -> str:
    result = group
    seen: set[str] = set()
    while parents.get(result) and result not in seen:
        seen.add(result)
        result = str(parents[result])
    return result


def _coverage_by_artifact(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> dict[int, float | None]:
    rows = connection.execute(
        """
        SELECT artifact_id, MAX(line_coverage) AS line_coverage
        FROM coverage_measurements
        WHERE snapshot_id = ? AND artifact_id IS NOT NULL
        GROUP BY artifact_id
        """,
        (snapshot_id,),
    ).fetchall()
    return {int(row["artifact_id"]): row["line_coverage"] for row in rows}


def _changes_by_path(
    connection: sqlite3.Connection,
    repository_id: int,
) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT path, COUNT(*) AS change_count FROM git_changes
        WHERE repository_id = ? GROUP BY path
        """,
        (repository_id,),
    ).fetchall()
    return {str(row["path"]): int(row["change_count"]) for row in rows}


def _quality(
    files: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    result = relationship_quality(relationships)
    analyzers = Counter(str(file["analyzer"]) for file in files)
    result.update(
        {
            "analyzers": dict(sorted(analyzers.items())),
            "ast_files": analyzers["builtin-python-ast"],
            "lexical_files": analyzers["builtin-js-lexer"],
            "fallback_files": analyzers["builtin-text"],
            "parse_error_files": sum(file.get("parse_error") is not None for file in files),
            "extraction_caveat": (
                "Python uses an AST parser; JavaScript and TypeScript use lexical extraction; "
                "other supported text formats use fallback analysis."
            ),
        }
    )
    return result


def _annotated_relationship(edge: dict[str, Any]) -> dict[str, Any]:
    metadata = relationship_metadata(edge)
    status = metadata.get("resolution_status")
    if status not in RESOLUTION_STATUSES:
        status = RESOLVED_INTERNAL if edge.get("target_artifact_id") is not None else EXTERNAL
    edge["metadata"] = metadata
    edge["resolution_status"] = status
    return edge


def _materialize_edges(
    rows: list[dict[str, Any]],
    *,
    include_external: bool,
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
    edges: list[dict[str, Any]] = []
    external_nodes: dict[str, tuple[str, str]] = {}
    for row in rows:
        edge = _graph_edge(row)
        if edge["target"] is None:
            if not include_external:
                continue
            label = edge["target_external"]
            external_id = f"{edge['resolution_status']}:{label}"
            external_nodes.setdefault(external_id, (str(label), edge["resolution_status"]))
            edge["target"] = external_id
        edges.append(edge)
    return edges, external_nodes


def _graph_edge(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source": row["source_artifact_id"],
        "target": row["target_artifact_id"],
        "target_external": row["target_external"],
        "type": row["relationship_type"],
        "evidence_source": row["source"],
        "confidence": row["confidence"],
        "weight": row["weight"],
        "evidence": row["evidence"],
        "source_line": row["source_line"],
        "metadata": row.get("metadata", {}),
        "resolution_status": row.get("resolution_status"),
        "candidate_paths": row.get("metadata", {}).get("candidate_paths", []),
    }


def _external_node(node_id: str, label: str, status: str) -> dict[str, Any]:
    external = status == "external"
    return {
        "id": node_id,
        "path": label,
        "language": "external" if external else "unresolved",
        "lines_of_code": 0,
        "complexity": 0,
        "summary": (
            f"External dependency {label}"
            if external
            else f"{status.replace('_', ' ').title()} reference {label}"
        ),
        "declared_group": "external" if external else "unresolved",
        "inferred_group": "external" if external else "unresolved",
        "analysis_status": status,
        "fan_in": 0,
        "fan_out": 0,
        "line_coverage": None,
    }
