"""Persist taxonomy candidates, independent reviews, and finalized map records."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_contract import SemanticResult
from anaxigraph.semantic_taxonomy_validation import normalize_taxonomy


def complete_taxonomy_job(
    connection: sqlite3.Connection,
    *,
    job: dict[str, Any],
    result: SemanticResult,
    document_id: int,
    provider: str,
    source: str,
    semantic: SemanticConfig,
    now: str,
) -> None:
    if job["job_kind"] == "taxonomy_proposal":
        _store_candidate(
            connection,
            job=job,
            result=result,
            document_id=document_id,
            provider=provider,
            source=source,
            semantic=semantic,
            now=now,
        )
        return
    _store_review(
        connection,
        job=job,
        result=result,
        document_id=document_id,
        now=now,
    )


def _store_candidate(
    connection: sqlite3.Connection,
    *,
    job: dict[str, Any],
    result: SemanticResult,
    document_id: int,
    provider: str,
    source: str,
    semantic: SemanticConfig,
    now: str,
) -> None:
    normalized = _normalize(connection, job, result.value)
    connection.execute(
        """
        INSERT INTO semantic_taxonomies(
            repository_id, snapshot_id, input_hash, status, source, provider, model,
            executor_id, executor_model, prompt_version, schema_version, confidence,
            candidate_document_id, review_passes, validation_json, created_at, updated_at
        ) VALUES (?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        ON CONFLICT(snapshot_id, input_hash) DO UPDATE SET
            status = 'proposed', source = excluded.source, provider = excluded.provider,
            model = excluded.model, executor_id = excluded.executor_id,
            executor_model = excluded.executor_model, prompt_version = excluded.prompt_version,
            schema_version = excluded.schema_version, confidence = excluded.confidence,
            candidate_document_id = excluded.candidate_document_id, final_document_id = NULL,
            review_passes = 0, validation_json = excluded.validation_json,
            facets_json = '[]', change_json = '[]', updated_at = excluded.updated_at
        """,
        (
            job["repository_id"],
            job["snapshot_id"],
            job["input_hash"],
            source,
            provider,
            semantic.model,
            job.get("executor_id"),
            job.get("executor_model"),
            semantic.prompt_version,
            job["schema_version"],
            result.confidence,
            document_id,
            json.dumps(normalized["validation"], sort_keys=True),
            now,
            now,
        ),
    )
    connection.execute(
        """
        UPDATE semantic_scope_states SET status = 'pending_taxonomy_review',
            context_document_id = ?, reason = ?, last_checked_at = ?
        WHERE snapshot_id = ? AND scope_type = 'taxonomy' AND scope_key = ?
        """,
        (
            document_id,
            "Agent taxonomy candidate awaits independent agent criticism",
            now,
            job["snapshot_id"],
            job["scope_key"],
        ),
    )


def _store_review(
    connection: sqlite3.Connection,
    *,
    job: dict[str, Any],
    result: SemanticResult,
    document_id: int,
    now: str,
) -> None:
    taxonomy = _taxonomy_row(connection, job)
    pass_index = int(job["metadata"].get("review_pass", 1))
    normalized = _normalize(connection, job, result.value["taxonomy"])
    connection.execute(
        """
        INSERT OR REPLACE INTO semantic_taxonomy_reviews(
            taxonomy_id, pass_index, document_id, verdict, issues_json,
            validation_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            taxonomy["id"],
            pass_index,
            document_id,
            result.value["verdict"],
            json.dumps(result.value["issues"], sort_keys=True),
            json.dumps(normalized["validation"], sort_keys=True),
            now,
        ),
    )
    required = int(job["metadata"]["taxonomy_settings"]["review_passes"])
    if pass_index < required:
        connection.execute(
            """
            UPDATE semantic_taxonomies SET status = 'reviewing', review_passes = ?,
                confidence = ?, validation_json = ?, updated_at = ? WHERE id = ?
            """,
            (
                pass_index,
                normalized["confidence"],
                json.dumps(normalized["validation"], sort_keys=True),
                now,
                taxonomy["id"],
            ),
        )
        _set_taxonomy_state(
            connection,
            job,
            document_id,
            "pending_taxonomy_review",
            f"Independent agent review {pass_index} of {required} completed",
            now,
        )
        return
    _finalize(connection, taxonomy, job, normalized, document_id, pass_index, now)


def _finalize(
    connection: sqlite3.Connection,
    taxonomy: sqlite3.Row,
    job: dict[str, Any],
    normalized: dict[str, Any],
    document_id: int,
    pass_index: int,
    now: str,
) -> None:
    taxonomy_id = int(taxonomy["id"])
    connection.execute(
        "DELETE FROM semantic_taxonomy_memberships WHERE taxonomy_id = ?", (taxonomy_id,)
    )
    connection.execute("DELETE FROM semantic_taxonomy_nodes WHERE taxonomy_id = ?", (taxonomy_id,))
    for node in normalized["nodes"]:
        connection.execute(
            """
            INSERT INTO semantic_taxonomy_nodes(
                taxonomy_id, node_key, name, level, parent_key, description,
                responsibility, confidence, rationale, evidence_json,
                counter_evidence_json, display_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                taxonomy_id,
                node["node_key"],
                node["name"],
                node["level"],
                node["parent_key"],
                node["description"],
                node["responsibility"],
                node["confidence"],
                node["rationale"],
                json.dumps(node["evidence"]),
                json.dumps(node["counter_evidence"]),
                node["display_order"],
            ),
        )
    for membership in normalized["memberships"]:
        connection.execute(
            """
            INSERT INTO semantic_taxonomy_memberships(
                taxonomy_id, artifact_id, node_key, confidence, rationale,
                evidence_json, alternatives_json, locked
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                taxonomy_id,
                membership["artifact_id"],
                membership["node_key"],
                membership["confidence"],
                membership["rationale"],
                json.dumps(membership["evidence"]),
                json.dumps(membership["alternatives"]),
                int(membership["locked"]),
            ),
        )
    connection.execute(
        """
        UPDATE semantic_taxonomies SET status = 'superseded'
        WHERE snapshot_id = ? AND id != ? AND status = 'current'
        """,
        (job["snapshot_id"], taxonomy_id),
    )
    connection.execute(
        """
        UPDATE semantic_taxonomies SET status = 'current', final_document_id = ?,
            review_passes = ?, confidence = ?, validation_json = ?, facets_json = ?,
            change_json = ?, updated_at = ? WHERE id = ?
        """,
        (
            document_id,
            pass_index,
            normalized["confidence"],
            json.dumps(normalized["validation"], sort_keys=True),
            json.dumps(normalized["facets"], sort_keys=True),
            json.dumps(normalized["events"], sort_keys=True),
            now,
            taxonomy_id,
        ),
    )
    _set_taxonomy_state(
        connection,
        job,
        document_id,
        "current",
        "Agent-proposed taxonomy passed agent criticism and deterministic validation",
        now,
    )


def _normalize(
    connection: sqlite3.Connection,
    job: dict[str, Any],
    value: dict[str, Any],
) -> dict[str, Any]:
    return normalize_taxonomy(
        connection,
        repository_id=int(job["repository_id"]),
        snapshot_id=int(job["snapshot_id"]),
        value=value,
        eligible_paths=[str(path) for path in job["metadata"].get("eligible_paths", [])],
        settings=dict(job["metadata"].get("taxonomy_settings") or {}),
        locked_memberships=dict(job["metadata"].get("locked_memberships") or {}),
    )


def _taxonomy_row(connection: sqlite3.Connection, job: dict[str, Any]) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT * FROM semantic_taxonomies
        WHERE snapshot_id = ? AND input_hash = ? ORDER BY id DESC LIMIT 1
        """,
        (job["snapshot_id"], job["metadata"]["taxonomy_input_hash"]),
    ).fetchone()
    if row is None:
        raise RuntimeError("Taxonomy review lost its candidate record")
    return row


def _set_taxonomy_state(
    connection: sqlite3.Connection,
    job: dict[str, Any],
    document_id: int,
    status: str,
    reason: str,
    now: str,
) -> None:
    connection.execute(
        """
        UPDATE semantic_scope_states SET status = ?, context_document_id = ?,
            reason = ?, last_checked_at = ?
        WHERE snapshot_id = ? AND scope_type = 'taxonomy' AND scope_key = ?
        """,
        (status, document_id, reason, now, job["snapshot_id"], job["scope_key"]),
    )
