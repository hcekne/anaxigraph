"""Canonical graph read model for dashboard, REST, and MCP consumers."""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from anaxigraph.relationships import (
    EXTERNAL,
    RESOLUTION_STATUSES,
    RESOLVED_INTERNAL,
    relationship_metadata,
    resolution_status,
)


def projected_graph_quality(connection: sqlite3.Connection) -> dict[str, Any]:
    """Summarize an installed snapshot projection without materializing every edge."""

    return {
        **_projected_resolution_quality(connection),
        **_projected_analyzer_quality(connection),
    }


def _projected_resolution_quality(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT CASE
                 WHEN json_extract(metadata_json, '$.resolution_status') IN
                      ('resolved_internal', 'ambiguous_internal', 'unresolved_internal', 'external')
                 THEN json_extract(metadata_json, '$.resolution_status')
                 WHEN target_artifact_id IS NOT NULL THEN 'resolved_internal'
                 ELSE 'external'
               END AS resolution_status,
               COUNT(*) AS count
        FROM projected_relationships GROUP BY resolution_status
        """
    ).fetchall()
    counts = Counter({str(row["resolution_status"]): int(row["count"]) for row in rows})
    internal = (
        counts[RESOLVED_INTERNAL] + counts["ambiguous_internal"] + counts["unresolved_internal"]
    )
    unresolved = counts["ambiguous_internal"] + counts["unresolved_internal"]
    return {
        "status": "unavailable" if not internal else "complete" if not unresolved else "partial",
        "resolution_rate": counts[RESOLVED_INTERNAL] / internal if internal else None,
        "total_relationships": sum(counts.values()),
        "internal_references": internal,
        "resolved_internal": counts[RESOLVED_INTERNAL],
        "ambiguous_internal": counts["ambiguous_internal"],
        "unresolved_internal": counts["unresolved_internal"],
        "external": counts[EXTERNAL],
        "caveat": (
            "Resolution measures extracted references only; dynamic runtime wiring can still be absent."
        ),
    }


def _projected_analyzer_quality(connection: sqlite3.Connection) -> dict[str, Any]:
    analyzers = Counter(
        {
            str(row["analyzer"]): int(row["count"])
            for row in connection.execute(
                "SELECT analyzer, COUNT(*) AS count FROM projected_file_versions GROUP BY analyzer"
            ).fetchall()
        }
    )
    return {
        "analyzers": dict(sorted(analyzers.items())),
        "ast_files": analyzers["builtin-python-ast"],
        "lexical_files": analyzers["builtin-js-lexer"],
        "fallback_files": analyzers["builtin-text"],
        "parse_error_files": int(
            connection.execute(
                "SELECT COUNT(*) FROM projected_file_versions WHERE parse_error IS NOT NULL"
            ).fetchone()[0]
        ),
        "extraction_caveat": (
            "Python uses an AST parser; JavaScript and TypeScript use lexical extraction; "
            "other supported text formats use fallback analysis."
        ),
    }


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


def graph_node(
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
    fallback_area = root_group(str(fallback), parents)
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
                    "area": root_group(str(policy), parents),
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


def group_parents(connection: sqlite3.Connection, repository_id: int) -> dict[str, str | None]:
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


def root_group(group: str, parents: dict[str, str | None]) -> str:
    result = group
    seen: set[str] = set()
    while parents.get(result) and result not in seen:
        seen.add(result)
        result = str(parents[result])
    return result


def graph_edge(row: dict[str, Any]) -> dict[str, Any]:
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


def materialize_graph_edges(
    rows: list[sqlite3.Row],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    edges = []
    external: dict[str, dict[str, Any]] = {}
    for row in rows:
        edge = graph_edge(decode_relationship(dict(row)))
        if edge["target"] is None:
            label = str(edge["target_external"])
            node_id = f"{edge['resolution_status']}:{label}"
            external.setdefault(
                node_id,
                external_node(node_id, label, str(edge["resolution_status"])),
            )
            edge["target"] = node_id
        edges.append(edge)
    return edges, external


def external_node(node_id: str, label: str, status: str) -> dict[str, Any]:
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
