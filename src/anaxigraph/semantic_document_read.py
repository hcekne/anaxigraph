"""Canonical semantic document reads, compatibility matching and value projections."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_freshness import legacy_input_matches
from anaxigraph.semantic_graph import SupersededSemanticJob


def _matching_document(
    connection: sqlite3.Connection,
    repository_id: int,
    scope_type: str,
    scope_key: str,
    kind: str,
    input_hash: str,
    semantic: SemanticConfig,
    *,
    legacy_evidence: Any | None = None,
    intrinsic_document_id: int | None = None,
) -> dict[str, Any] | None:
    rows = connection.execute(
        """
        SELECT * FROM semantic_document_values
        WHERE repository_id = ? AND scope_type = ? AND scope_key = ?
          AND document_kind = ? AND prompt_version = ?
        ORDER BY id DESC
        """,
        (
            repository_id,
            scope_type,
            scope_key,
            kind,
            semantic.prompt_version,
        ),
    ).fetchall()
    for row in rows:
        document = dict(row)
        if str(document["input_hash"]) == input_hash:
            return document
        if legacy_evidence is not None and legacy_input_matches(
            document,
            legacy_evidence,
            prompt_version=semantic.prompt_version,
        ):
            if kind == "context" and document["schema_version"] == "repository-understanding-v5":
                # 0.5.x hashed intrinsic intent, not its source. A same-role edit
                # must not reuse old context merely because that intent survived.
                source = connection.execute(
                    "SELECT file_fact_id FROM semantic_document_values WHERE id = ?",
                    (intrinsic_document_id,),
                ).fetchone()
                if source is None or not source[0] or source[0] != document["file_fact_id"]:
                    continue
            return document
    return None


def _latest_document(
    connection: sqlite3.Connection,
    repository_id: int,
    scope_type: str,
    scope_key: str,
    kind: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT * FROM semantic_document_values
        WHERE repository_id = ? AND scope_type = ? AND scope_key = ? AND document_kind = ?
        ORDER BY id DESC LIMIT 1
        """,
        (repository_id, scope_type, scope_key, kind),
    ).fetchone()
    return dict(row) if row else None


def _document_by_id(connection: sqlite3.Connection, document_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM semantic_document_values WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise SupersededSemanticJob("A required semantic document no longer exists")
    result = dict(row)
    result["value"] = json.loads(result.pop("value_json") or "{}")
    if result["document_kind"] == "pattern_review":
        from anaxigraph.persistence.pattern_review_references import expanded_pattern_review

        result["value"] = expanded_pattern_review(connection, result)
    if result["document_kind"] == "annotation":
        from anaxigraph.knowledge_values import annotation_compatibility

        result["value"] = annotation_compatibility(result["value"])
    result["supporting_evidence"] = json.loads(result.pop("supporting_evidence_json") or "[]")
    return result
