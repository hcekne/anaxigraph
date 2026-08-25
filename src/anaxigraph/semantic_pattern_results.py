"""Advance pattern assessment through durable independent critique."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.semantic import SemanticResult
from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_pattern_identity import pattern_review_input_hash
from anaxigraph.semantic_pattern_state import estimated_tokens, upsert_pattern_state
from anaxigraph.semantic_records import _ensure_job, _latest_document


def complete_pattern_job(
    connection: sqlite3.Connection,
    *,
    job: dict[str, Any],
    result: SemanticResult,
    document_id: int,
    semantic: SemanticConfig,
    now: str,
) -> None:
    if job["job_kind"] == "pattern_assessment":
        _queue_review(connection, job, result, document_id, semantic)
        return
    connection.execute(
        """
        UPDATE semantic_scope_states SET status = 'current', context_document_id = ?,
            reason = ?, last_checked_at = ?
        WHERE snapshot_id = ? AND scope_type = 'pattern' AND scope_key = ?
        """,
        (
            document_id,
            "Pattern evaluation passed independent agent critique",
            now,
            job["snapshot_id"],
            job["scope_key"],
        ),
    )


def _queue_review(
    connection: sqlite3.Connection,
    job: dict[str, Any],
    result: SemanticResult,
    document_id: int,
    semantic: SemanticConfig,
) -> None:
    candidate = job["metadata"]["candidate"]
    review_hash = pattern_review_input_hash(candidate, result.value, semantic.prompt_version)
    previous = _latest_document(
        connection,
        int(job["repository_id"]),
        "pattern",
        str(job["scope_key"]),
        "pattern_review",
    )
    metadata = {
        **job["metadata"],
        "assessment_document_id": document_id,
        "previous_document_id": previous["id"] if previous else None,
    }
    status, _, error = _ensure_job(
        connection,
        repository_id=int(job["repository_id"]),
        snapshot_id=int(job["snapshot_id"]),
        scope_type="pattern",
        scope_key=str(job["scope_key"]),
        artifact_id=job.get("artifact_id"),
        artifact_version_id=None,
        job_kind="pattern_review",
        reason="pattern_assessment_requires_independent_critique",
        priority=int(candidate["priority"]),
        input_hash=review_hash,
        semantic=semantic,
        estimated_input_tokens=estimated_tokens(metadata),
        metadata=metadata,
        retry_failed=False,
    )
    upsert_pattern_state(
        connection,
        int(job["repository_id"]),
        int(job["snapshot_id"]),
        str(job["scope_key"]),
        candidate,
        status="failed_pattern" if status == "failed" else "pending_pattern_review",
        reason=error or "Assessment awaits independent agent critique",
        assessment_hash=str(job["input_hash"]),
        review_hash=review_hash,
        assessment_document_id=document_id,
    )
