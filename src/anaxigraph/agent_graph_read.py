"""Read the projected repository graph and attach current semantic evidence."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any

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
        value = _json(row["value_json"] or "{}") or {}
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


def _interfaces(
    connection: sqlite3.Connection, snapshot_id: int, artifact_ids: list[int]
) -> list[dict[str, Any]]:
    if not artifact_ids:
        return []
    placeholders = ",".join("?" for _ in artifact_ids)
    rows = connection.execute(
        f"""
        SELECT fv.path, s.symbol_type, s.name, s.signature, s.summary
        FROM projected_symbols s
        JOIN projected_file_versions fv ON fv.id = s.artifact_version_id
        WHERE fv.snapshot_id = ? AND fv.artifact_id IN ({placeholders})
          AND s.symbol_type IN ('class', 'api_endpoint', 'database_model')
        ORDER BY fv.path, s.start_line LIMIT 100
        """,
        [snapshot_id, *artifact_ids],
    ).fetchall()
    return [dict(row) for row in rows]


def _json(value: str) -> Any:
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None
