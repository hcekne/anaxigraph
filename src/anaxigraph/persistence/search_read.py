"""Canonical current-snapshot module search."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.persistence.semantic_taxonomy_read import taxonomy_assignments
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection
from anaxigraph.semantic_file_language import semantic_file_explanation


def search_modules(
    connection: sqlite3.Connection,
    snapshot_id: int,
    query: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    terms = [term.lower() for term in query.split() if len(term) > 1]
    if not terms:
        return []
    install_snapshot_projection(connection, snapshot_id)
    semantics = _semantic_documents(connection, snapshot_id)
    assignments = taxonomy_assignments(connection, snapshot_id)
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in _search_rows(connection):
        item = dict(row)
        semantic = semantics.get(int(item["artifact_id"]))
        semantic_value = semantic["value"] if semantic else {}
        _apply_semantic(
            item,
            semantic,
            semantic_value,
            assignments.get(int(item["artifact_id"])),
        )
        score = _score(item, semantic_value, terms)
        if score:
            item["score"] = score
            scored.append((score, item))
    return [
        item for _, item in sorted(scored, key=lambda pair: (-pair[0], pair[1]["path"]))[:limit]
    ]


def _search_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT a.id AS artifact_id, fv.path, fv.language, fv.summary,
               fv.declared_group, fv.inferred_group, fv.lines_of_code,
               GROUP_CONCAT(s.name, ' ') AS symbol_names
        FROM projected_file_versions fv JOIN artifacts a ON a.id = fv.artifact_id
        LEFT JOIN projected_symbols s ON s.artifact_version_id = fv.id
        GROUP BY fv.id
        """
    ).fetchall()


def _semantic_documents(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> dict[int, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT ss.artifact_id, ss.status, sd.value_json, sd.provider,
               sd.model, sd.confidence, sd.document_kind
        FROM semantic_scope_states ss
        LEFT JOIN semantic_documents sd
          ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
        """,
        (snapshot_id,),
    ).fetchall()
    return {
        int(row["artifact_id"]): {
            **dict(row),
            "value": json.loads(row["value_json"] or "{}"),
        }
        for row in rows
        if row["artifact_id"] is not None
    }


def _apply_semantic(
    item: dict[str, Any],
    semantic: dict[str, Any] | None,
    value: dict[str, Any],
    assignment: dict[str, Any] | None,
) -> None:
    if semantic:
        semantic_payload = {
            "status": semantic["status"],
            "source": semantic["document_kind"],
            "provider": semantic["provider"],
            "model": semantic["model"],
            "confidence": semantic["confidence"],
            "summary": value.get("summary") or "",
        }
        semantic_payload["plain_language"] = semantic_file_explanation(
            str(item["path"]), {**value, **semantic_payload}
        )
        item["semantic"] = semantic_payload
        if value.get("summary"):
            item["deterministic_summary"] = item["summary"]
            item["summary"] = semantic_payload["plain_language"]["what_this_file_does"]
    if assignment:
        item["semantic_taxonomy"] = assignment
        item["architecture_area"] = assignment["area"]
        item["architecture_subsystem"] = assignment["subsystem"]


def _score(item: dict[str, Any], semantic: dict[str, Any], terms: list[str]) -> float:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("path", "summary", "declared_group", "inferred_group", "symbol_names")
    )
    haystack += " " + " ".join(
        str(value)
        for value in (
            semantic.get("detailed_summary"),
            semantic.get("architecture_role"),
            semantic.get("placement_guidance"),
            *(semantic.get("responsibilities") or []),
            *(semantic.get("domain_concepts") or []),
        )
        if value
    )
    taxonomy = item.get("semantic_taxonomy") or {}
    haystack += " " + " ".join(
        str(taxonomy.get(key) or "")
        for key in ("area", "area_name", "subsystem", "subsystem_name", "rationale")
    )
    lowered = haystack.lower()
    path = item["path"].lower()
    return sum(
        8 * path.count(term) + 3 * lowered.count(term) + (10 if path == term else 0)
        for term in terms
    )
