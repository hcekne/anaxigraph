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

GRAPH_QUALITY_LANGUAGE_VERSION = "graph-quality-explanation-v1"


def projected_graph_quality(connection: sqlite3.Connection) -> dict[str, Any]:
    """Summarize an installed snapshot projection without materializing every edge."""

    quality = {
        **_projected_resolution_quality(connection),
        **_projected_analyzer_quality(connection),
    }
    quality["plain_language"] = graph_quality_explanation(quality)
    return quality


def graph_quality_explanation(quality: dict[str, Any]) -> dict[str, Any]:
    """Explain graph completeness without requiring resolver or analyzer vocabulary."""

    internal = _count(quality.get("internal_references"))
    resolved = _count(quality.get("resolved_internal"))
    ambiguous = _count(quality.get("ambiguous_internal"))
    unresolved = _count(quality.get("unresolved_internal"))
    fallback = _count(quality.get("fallback_files"))
    parse_errors = _count(quality.get("parse_error_files"))
    return {
        "version": GRAPH_QUALITY_LANGUAGE_VERSION,
        "conclusion": _quality_conclusion(internal, ambiguous, unresolved, fallback, parse_errors),
        "what_was_checked": _resolution_sentence(internal, resolved, ambiguous, unresolved),
        "what_this_limits": _quality_limits(ambiguous, unresolved, fallback, parse_errors),
        "what_to_do": _quality_actions(ambiguous, unresolved, fallback, parse_errors),
    }


def _quality_conclusion(
    internal: int,
    ambiguous: int,
    unresolved: int,
    fallback: int,
    parse_errors: int,
) -> str:
    reasons = []
    if ambiguous + unresolved:
        reasons.append(
            _items(
                ambiguous + unresolved,
                "likely internal reference did",
                "likely internal references did",
            )
            + " not link to exactly one indexed file"
        )
    if fallback:
        reasons.append(_items(fallback, "file was", "files were") + " read only as plain text")
    if parse_errors:
        reasons.append(_items(parse_errors, "file could", "files could") + " not be parsed")
    if reasons:
        return f"The map may miss connections because {_join(reasons)}."
    if not internal:
        return "AnaxiGraph found no likely links between files in this repository to check."
    return "AnaxiGraph linked every extracted internal code reference to one indexed file."


def _resolution_sentence(internal: int, resolved: int, ambiguous: int, unresolved: int) -> str:
    if not internal:
        return (
            "No extracted source reference looked like a link to another file in this repository."
        )
    return (
        f"AnaxiGraph checked {_items(internal, 'likely link', 'likely links')} between files. "
        f"{resolved} pointed to exactly one indexed file, {ambiguous} could point to more than one "
        f"file, and {unresolved} looked internal but had no matching file."
    )


def _quality_limits(ambiguous: int, unresolved: int, fallback: int, parse_errors: int) -> list[str]:
    limits = []
    if ambiguous + unresolved:
        limits.append(
            "Dependency, change-impact, and unused-code advice may be incomplete. AnaxiGraph will "
            "not recommend deleting code when these missing links make that unsafe."
        )
    if fallback:
        limits.append(
            f"For {_items(fallback, 'file', 'files')}, AnaxiGraph could read words but not code "
            "structure, so it may have missed functions, classes, or imports."
        )
    if parse_errors:
        limits.append(
            f"AnaxiGraph could not reliably read code structure from {_items(parse_errors, 'file', 'files')} with parsing errors."
        )
    limits.append(
        "Connections created only while the program runs, such as plugin registration or generated "
        "imports, may not appear in a source-code map."
    )
    return limits


def _quality_actions(
    ambiguous: int, unresolved: int, fallback: int, parse_errors: int
) -> list[str]:
    actions = []
    if ambiguous + unresolved:
        actions.append(
            "Inspect the unclear or missing links before acting on dependency, impact, or deletion advice."
        )
    if fallback:
        actions.append(
            "Use a code-structure analyzer for these file types when exact functions and dependencies matter."
        )
    if parse_errors:
        actions.append(
            "Fix the parsing errors and scan again before relying on those files' links."
        )
    return actions or ["No graph-quality action is needed from this check."]


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _items(value: int, singular: str, plural: str) -> str:
    return f"{value} {singular if value == 1 else plural}"


def _join(values: list[str]) -> str:
    if len(values) < 2:
        return values[0] if values else "the available evidence is incomplete"
    if len(values) == 2:
        return " and ".join(values)
    return ", ".join(values[:-1]) + f", and {values[-1]}"


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
            "This check sees references written in source files. Connections created only while "
            "the program runs may be missing."
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
            "Python files are read from parsed code structure. JavaScript and TypeScript are read "
            "from names and code tokens. Other recognized text formats are read as plain text, so "
            "their relationships are less complete."
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
    historical_policy = file.get("declared_group")
    historical_inferred = file.get("inferred_group") or "ungrouped"
    policy = file.get("architecture_declared_group")
    inferred = file.get("architecture_inferred_group") or "ungrouped"
    area = file.get("area") or root_group(str(policy or inferred), parents)
    subsystem = file.get("subsystem") or policy or inferred
    return {
        "id": file["artifact_id"],
        "path": file["path"],
        "language": file["language"],
        "lines_of_code": file["lines_of_code"],
        "complexity": file["complexity"],
        "summary": file["summary"],
        "declared_group": policy,
        "inferred_group": inferred,
        "architecture_area": area,
        "architecture_subsystem": subsystem,
        "architecture_source": file.get("architecture_source"),
        "architecture_layer": "semantic" if assignment else "effective",
        "architecture_layers": {
            "semantic": assignment,
            "policy": architecture_placement(policy, inferred, parents) if policy else None,
            "inferred": architecture_placement(None, inferred, parents),
        },
        "historical_architecture": {
            **architecture_placement(historical_policy, historical_inferred, parents),
            "declared_group": historical_policy,
            "inferred_group": historical_inferred,
        },
        "analysis_status": file["analysis_status"],
        "last_changed_at": file["last_changed_at"],
        "fan_in": incoming,
        "fan_out": outgoing,
        "line_coverage": coverage,
        "change_count": changes,
    }


def architecture_placement(
    declared: Any, inferred: str, parents: dict[str, str | None]
) -> dict[str, Any]:
    group = str(declared or inferred)
    return {
        "area": root_group(group, parents),
        "subsystem": group,
        "source": "project path rule" if declared else "standard fallback vocabulary",
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
