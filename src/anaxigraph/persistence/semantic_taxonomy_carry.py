"""Carry an unchanged finalized semantic map into a new snapshot."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.clock import utc_now
from anaxigraph.semantic_freshness import legacy_input_matches


def carry_taxonomy(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    input_hash: str,
    legacy_evidence: dict[str, Any],
    prompt_version: str,
) -> sqlite3.Row | None:
    previous = _matching_taxonomy(
        connection,
        repository_id=repository_id,
        input_hash=input_hash,
        legacy_evidence=legacy_evidence,
        prompt_version=prompt_version,
    )
    if previous is None:
        return None
    if int(previous["snapshot_id"]) == snapshot_id:
        return previous
    now = utc_now()
    cursor = connection.execute(
        """
        INSERT INTO semantic_taxonomies(
            repository_id, snapshot_id, input_hash, status, source, provider, model,
            executor_id, executor_model, prompt_version, schema_version, confidence,
            candidate_document_id, final_document_id, review_passes, validation_json,
            facets_json, change_json, created_at, updated_at
        ) VALUES (?, ?, ?, 'current', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repository_id,
            snapshot_id,
            input_hash,
            "carried_semantic_taxonomy",
            previous["provider"],
            previous["model"],
            previous["executor_id"],
            previous["executor_model"],
            previous["prompt_version"],
            previous["schema_version"],
            previous["confidence"],
            previous["candidate_document_id"],
            previous["final_document_id"],
            previous["review_passes"],
            previous["validation_json"],
            previous["facets_json"],
            previous["change_json"],
            now,
            now,
        ),
    )
    taxonomy_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO semantic_taxonomy_nodes(
            taxonomy_id, node_key, name, level, parent_key, description, responsibility,
            confidence, rationale, evidence_json, counter_evidence_json, display_order
        )
        SELECT ?, node_key, name, level, parent_key, description, responsibility,
               confidence, rationale, evidence_json, counter_evidence_json, display_order
        FROM semantic_taxonomy_nodes WHERE taxonomy_id = ?
        """,
        (taxonomy_id, previous["id"]),
    )
    connection.execute(
        """
        INSERT INTO semantic_taxonomy_memberships(
            taxonomy_id, artifact_id, node_key, confidence, rationale,
            evidence_json, alternatives_json, locked
        )
        SELECT ?, artifact_id, node_key, confidence, rationale,
               evidence_json, alternatives_json, locked
        FROM semantic_taxonomy_memberships WHERE taxonomy_id = ?
        """,
        (taxonomy_id, previous["id"]),
    )
    connection.execute(
        """
        INSERT INTO semantic_taxonomy_reviews(
            taxonomy_id, pass_index, document_id, verdict, issues_json,
            validation_json, created_at
        )
        SELECT ?, pass_index, document_id, verdict, issues_json, validation_json, created_at
        FROM semantic_taxonomy_reviews WHERE taxonomy_id = ?
        """,
        (taxonomy_id, previous["id"]),
    )
    return connection.execute(
        "SELECT * FROM semantic_taxonomies WHERE id = ?", (taxonomy_id,)
    ).fetchone()


def _matching_taxonomy(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    input_hash: str,
    legacy_evidence: dict[str, Any],
    prompt_version: str,
) -> sqlite3.Row | None:
    rows = connection.execute(
        """
        SELECT * FROM semantic_taxonomies
        WHERE repository_id = ? AND status = 'current' AND prompt_version = ?
        ORDER BY snapshot_id DESC, id DESC
        """,
        (repository_id, prompt_version),
    ).fetchall()
    for row in rows:
        taxonomy = dict(row)
        if taxonomy["input_hash"] == input_hash or legacy_input_matches(
            taxonomy,
            legacy_evidence,
            prompt_version=prompt_version,
        ):
            return row
    return None
