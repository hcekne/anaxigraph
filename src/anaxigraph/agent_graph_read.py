"""Read the projected repository graph and attach current semantic evidence."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from anaxigraph.persistence.group_read import read_group_hierarchy
from anaxigraph.persistence.row_decoding import _decode_json_value
from anaxigraph.persistence.semantic_taxonomy_read import taxonomy_assignments
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection
from anaxigraph.semantic_file_language import semantic_file_explanation


def _projected_graph_maps(
    connection: sqlite3.Connection, snapshot_id: int
) -> tuple[dict[int, dict[str, Any]], dict[int, set[int]], dict[int, set[int]]]:
    install_snapshot_projection(connection, snapshot_id)
    return _graph_maps(connection, snapshot_id)


def _graph_maps(
    connection: sqlite3.Connection, snapshot_id: int
) -> tuple[dict[int, dict[str, Any]], dict[int, set[int]], dict[int, set[int]]]:
    files = _graph_files(connection, snapshot_id)
    _attach_semantic_files(connection, snapshot_id, files)
    outgoing, incoming = _dependency_maps(connection, snapshot_id, files)
    return files, outgoing, incoming


def _graph_files(connection: sqlite3.Connection, snapshot_id: int) -> dict[int, dict[str, Any]]:
    return {
        int(row["artifact_id"]): dict(row)
        for row in connection.execute(
            """
            SELECT fv.*, a.artifact_type FROM projected_file_versions fv
            JOIN artifacts a ON a.id = fv.artifact_id WHERE fv.snapshot_id = ?
            """,
            (snapshot_id,),
        )
    }


def _attach_semantic_files(
    connection: sqlite3.Connection, snapshot_id: int, files: dict[int, dict[str, Any]]
) -> None:
    for row in connection.execute(
        """
        SELECT ss.artifact_id, ss.status, ss.reason, sd.value_json, sd.provider,
               sd.model, sd.confidence, sd.document_kind
        FROM semantic_scope_states ss
        LEFT JOIN semantic_documents sd
          ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
        """,
        (snapshot_id,),
    ):
        artifact_id = int(row["artifact_id"])
        if artifact_id not in files:
            continue
        value = _decode_json_value(row["value_json"] or "{}") or {}
        item = files[artifact_id]
        item["deterministic_summary"] = item["summary"]
        semantic = _semantic_file(row, value, str(item["path"]))
        if value.get("summary"):
            item["summary"] = semantic["plain_language"]["what_this_file_does"]
        item["semantic"] = semantic


def _dependency_maps(
    connection: sqlite3.Connection, snapshot_id: int, files: dict[int, dict[str, Any]]
) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    outgoing: dict[int, set[int]] = defaultdict(set)
    incoming: dict[int, set[int]] = defaultdict(set)
    for row in connection.execute(
        """
        SELECT source_artifact_id, target_artifact_id FROM projected_relationships
        WHERE snapshot_id = ? AND target_artifact_id IS NOT NULL
        """,
        (snapshot_id,),
    ):
        source = int(row["source_artifact_id"])
        target = int(row["target_artifact_id"])
        outgoing[source].add(target)
        incoming[target].add(source)
    for artifact_id in files:
        outgoing.setdefault(artifact_id, set())
        incoming.setdefault(artifact_id, set())
        files[artifact_id]["fan_out"] = len(outgoing[artifact_id])
        files[artifact_id]["fan_in"] = len(incoming[artifact_id])
        files[artifact_id]["outgoing_paths"] = sorted(
            files[target]["path"] for target in outgoing[artifact_id] if target in files
        )
        files[artifact_id]["incoming_paths"] = sorted(
            files[source]["path"] for source in incoming[artifact_id] if source in files
        )
    return outgoing, incoming


def _semantic_file(row: Any, value: dict[str, Any], path: str) -> dict[str, Any]:
    result = {
        "status": row["status"],
        "reason": row["reason"],
        "source": row["document_kind"],
        "provider": row["provider"],
        "model": row["model"],
        "confidence": row["confidence"],
        "summary": _semantic_field(value, "summary", ""),
        "architecture_role": _semantic_field(value, "architecture_role", ""),
        "placement_guidance": _semantic_field(value, "placement_guidance", ""),
        "detailed_summary": _semantic_field(value, "detailed_summary", ""),
        "responsibilities": _semantic_field(value, "responsibilities", []),
        "public_contracts": _semantic_field(value, "public_contracts", []),
        "invariants": _semantic_field(value, "invariants", []),
        "domain_concepts": _semantic_field(value, "domain_concepts", []),
        "extension_points": _semantic_field(value, "extension_points", []),
        "similar_modules": _semantic_field(value, "similar_modules", []),
        "pattern_opportunities": _semantic_field(value, "pattern_opportunities", [])[:5],
        "consolidation_assessment": value.get("consolidation_assessment"),
        "dead_code_candidates": _semantic_field(value, "dead_code_candidates", [])[:5],
        "testing_guidance": _semantic_field(value, "testing_guidance", []),
        "risks": _semantic_field(value, "risks", []),
    }
    result["plain_language"] = semantic_file_explanation(path, {**value, **result})
    return result


def _semantic_field(value: dict[str, Any], key: str, default: Any) -> Any:
    selected = value.get(key)
    return default if selected is None else selected


def _symbols(
    connection: sqlite3.Connection, snapshot_id: int, artifact_ids: list[int]
) -> list[dict[str, Any]]:
    if not artifact_ids:
        return []
    placeholders = ",".join("?" for _ in artifact_ids)
    rows = connection.execute(
        f"""
        SELECT fv.path, s.symbol_type, s.name, s.qualified_name, s.signature,
               s.start_line, s.end_line, s.summary
        FROM projected_symbols s
        JOIN projected_file_versions fv ON fv.id = s.artifact_version_id
        WHERE fv.snapshot_id = ? AND fv.artifact_id IN ({placeholders})
        ORDER BY fv.path, s.start_line LIMIT 1000
        """,
        [snapshot_id, *artifact_ids],
    ).fetchall()
    return [dict(row) for row in rows]


def _public_interfaces(symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kinds = {"class", "api_endpoint", "database_model"}
    return [item for item in symbols if item.get("symbol_type") in kinds][:100]


def _interfaces(
    connection: sqlite3.Connection, snapshot_id: int, artifact_ids: list[int]
) -> list[dict[str, Any]]:
    return _public_interfaces(_symbols(connection, snapshot_id, artifact_ids))


def _attach_architecture_map(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    files: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach the effective area/subsystem path without creating another read model."""

    hierarchy = read_group_hierarchy(connection, repository_id, snapshot_id)
    nodes, parents = _hierarchy_nodes(hierarchy)
    assignments = taxonomy_assignments(connection, snapshot_id)
    for artifact_id, item in files.items():
        assignment = assignments.get(artifact_id)
        if assignment:
            item["semantic_taxonomy"] = assignment
            item["architecture_placement"] = _semantic_placement(assignment)
            continue
        subsystem = str(item.get("declared_group") or item.get("inferred_group") or "ungrouped")
        area = _root_group(subsystem, parents)
        source = (
            "project path rule" if item.get("declared_group") else "standard fallback vocabulary"
        )
        item["architecture_placement"] = {
            "area": area,
            "area_name": _group_label(nodes.get(area), area),
            "subsystem": subsystem,
            "subsystem_name": _group_label(nodes.get(subsystem), subsystem),
            "source": source,
            "why_here": (
                "Repository configuration puts this file in this group."
                if item.get("declared_group")
                else "The standard fallback vocabulary supplies this role; no current AI-created placement exists."
            ),
        }
    return hierarchy


def _semantic_placement(assignment: dict[str, Any]) -> dict[str, Any]:
    language = assignment.get("plain_language") or {}
    return {
        "area": assignment["area"],
        "area_name": language.get("area_name") or assignment.get("area_name"),
        "subsystem": assignment["subsystem"],
        "subsystem_name": language.get("subsystem_name") or assignment.get("subsystem_name"),
        "source": assignment["source"],
        "why_here": language.get("why_this_file_is_here") or assignment.get("rationale"),
    }


def _hierarchy_nodes(
    hierarchy: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str | None]]:
    nodes: dict[str, dict[str, Any]] = {}
    parents: dict[str, str | None] = {}

    def visit(item: dict[str, Any], parent: str | None) -> None:
        key = str(item.get("name") or "")
        nodes[key] = item
        parents[key] = parent
        for child in item.get("children") or []:
            visit(child, key)

    for root in hierarchy:
        visit(root, None)
    return nodes, parents


def _root_group(group: str, parents: dict[str, str | None]) -> str:
    result = group
    seen: set[str] = set()
    while parents.get(result) and result not in seen:
        seen.add(result)
        result = str(parents[result])
    return result


def _group_label(node: dict[str, Any] | None, fallback: str) -> str:
    if not node:
        return fallback.replace("-", " ").replace("_", " ").title()
    language = node.get("plain_language") or {}
    label = language.get("display_name") or node.get("label")
    return str(label or fallback.replace("-", " ").replace("_", " ").title())
