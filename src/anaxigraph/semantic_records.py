"""SQLite helpers for semantic documents, jobs, and current scope state."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.clock import utc_now
from anaxigraph.config import SemanticConfig
from anaxigraph.persistence.semantic_fact_references import semantic_fact_id
from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_freshness import legacy_input_matches
from anaxigraph.semantic_graph import SupersededSemanticJob, _cost
from anaxigraph.semantic_job_state import (
    semantic_job_bulk_transition,
    semantic_job_transition,
    semantic_scope_status,
)

_INSERT_JOB_SQL = """
INSERT INTO semantic_jobs(
    repository_id, snapshot_id, scope_type, scope_key, artifact_id,
    artifact_version_id, file_fact_id, job_kind, reason, status, priority, input_hash,
    provider, model, prompt_version, schema_version, max_attempts,
    estimated_input_tokens, estimated_cost_usd, available_at, metadata_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPSERT_STATE_SQL = """
INSERT INTO semantic_scope_states(
    repository_id, snapshot_id, scope_type, scope_key, artifact_id,
    artifact_version_id, file_fact_id, status, reason, intrinsic_input_hash,
    context_input_hash, interface_hash, relationship_hash, context_fingerprint,
    intrinsic_document_id, context_document_id, last_checked_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(snapshot_id, scope_type, scope_key) DO UPDATE SET
    artifact_id = excluded.artifact_id,
    artifact_version_id = excluded.artifact_version_id,
    file_fact_id = excluded.file_fact_id,
    status = excluded.status,
    reason = excluded.reason,
    intrinsic_input_hash = COALESCE(excluded.intrinsic_input_hash, intrinsic_input_hash),
    context_input_hash = COALESCE(excluded.context_input_hash, context_input_hash),
    interface_hash = COALESCE(excluded.interface_hash, interface_hash),
    relationship_hash = COALESCE(excluded.relationship_hash, relationship_hash),
    context_fingerprint = COALESCE(excluded.context_fingerprint, context_fingerprint),
    intrinsic_document_id = COALESCE(excluded.intrinsic_document_id, intrinsic_document_id),
    context_document_id = COALESCE(excluded.context_document_id, context_document_id),
    last_checked_at = excluded.last_checked_at
"""


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
) -> dict[str, Any] | None:
    rows = connection.execute(
        """
        SELECT * FROM semantic_documents
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
        SELECT * FROM semantic_documents
        WHERE repository_id = ? AND scope_type = ? AND scope_key = ? AND document_kind = ?
        ORDER BY id DESC LIMIT 1
        """,
        (repository_id, scope_type, scope_key, kind),
    ).fetchone()
    return dict(row) if row else None


def _ensure_job(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    scope_type: str,
    scope_key: str,
    artifact_id: int | None,
    artifact_version_id: int | None,
    job_kind: str,
    reason: str,
    priority: int,
    input_hash: str,
    semantic: SemanticConfig,
    estimated_input_tokens: int,
    metadata: dict[str, Any],
    retry_failed: bool,
    file_fact_id: int | None = None,
    force_new: bool = False,
) -> tuple[str, bool, str | None]:
    _supersede_changed_jobs(
        connection,
        repository_id,
        snapshot_id,
        scope_type,
        scope_key,
        job_kind,
        input_hash,
    )
    existing = _existing_job(
        connection,
        repository_id,
        snapshot_id,
        scope_type,
        scope_key,
        job_kind,
        input_hash,
    )
    reused = _reuse_job(connection, existing, job_kind, retry_failed, force_new)
    if reused is not None:
        return reused
    _insert_job(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type=scope_type,
        scope_key=scope_key,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
        file_fact_id=file_fact_id,
        job_kind=job_kind,
        reason=reason,
        priority=priority,
        input_hash=input_hash,
        semantic=semantic,
        estimated_input_tokens=estimated_input_tokens,
        metadata=metadata,
    )
    return semantic_scope_status(job_kind), True, None


def _existing_job(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    scope_type: str,
    scope_key: str,
    job_kind: str,
    input_hash: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM semantic_jobs
        WHERE repository_id = ? AND snapshot_id = ? AND scope_type = ? AND scope_key = ?
          AND job_kind = ? AND input_hash = ?
        ORDER BY id DESC LIMIT 1
        """,
        (repository_id, snapshot_id, scope_type, scope_key, job_kind, input_hash),
    ).fetchone()


def _reuse_job(
    connection: sqlite3.Connection,
    existing: sqlite3.Row | None,
    job_kind: str,
    retry_failed: bool,
    force_new: bool,
) -> tuple[str, bool, str | None] | None:
    if existing is None:
        return None
    status = str(existing["status"])
    if status == "completed" and force_new:
        return None
    if status == "failed" and retry_failed:
        _reset_failed_job(connection, int(existing["id"]))
        return semantic_scope_status(job_kind), False, None
    return (
        semantic_scope_status(job_kind, failed=status == "failed"),
        False,
        str(existing["error"] or "") or None,
    )


def _reset_failed_job(connection: sqlite3.Connection, job_id: int) -> None:
    pending = semantic_job_transition("failed", "reset_failed")
    connection.execute(
        """
        UPDATE semantic_jobs SET status = ?, attempts = 0, error = NULL,
            available_at = ?, completed_at = NULL, worker_id = NULL,
            lease_expires_at = NULL, lease_token_hash = NULL WHERE id = ?
        """,
        (pending, utc_now(), job_id),
    )


def _supersede_changed_jobs(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    scope_type: str,
    scope_key: str,
    job_kind: str,
    input_hash: str,
) -> None:
    superseded = semantic_job_bulk_transition(("pending", "retry"), "supersede")
    connection.execute(
        """
        UPDATE semantic_jobs SET status = ?, completed_at = ?, metadata_json = '{}',
            error = 'A newer semantic input replaced this queued job.'
        WHERE repository_id = ? AND snapshot_id = ? AND scope_type = ? AND scope_key = ?
          AND job_kind = ? AND input_hash != ? AND status IN ('pending', 'retry')
        """,
        (
            superseded,
            utc_now(),
            repository_id,
            snapshot_id,
            scope_type,
            scope_key,
            job_kind,
            input_hash,
        ),
    )


def _insert_job(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    scope_type: str,
    scope_key: str,
    artifact_id: int | None,
    artifact_version_id: int | None,
    file_fact_id: int | None,
    job_kind: str,
    reason: str,
    priority: int,
    input_hash: str,
    semantic: SemanticConfig,
    estimated_input_tokens: int,
    metadata: dict[str, Any],
) -> None:
    connection.execute(
        _INSERT_JOB_SQL,
        (
            repository_id,
            snapshot_id,
            scope_type,
            scope_key,
            artifact_id,
            artifact_version_id,
            _resolved_fact_id(connection, snapshot_id, artifact_id, file_fact_id),
            job_kind,
            reason,
            priority,
            input_hash,
            semantic.provider,
            semantic.model,
            semantic.prompt_version,
            SEMANTIC_SCHEMA_VERSION,
            semantic.max_attempts,
            estimated_input_tokens,
            _cost(estimated_input_tokens, semantic.max_output_tokens, semantic),
            utc_now(),
            json.dumps(metadata, sort_keys=True),
        ),
    )


def _active_job(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    scope_type: str,
    scope_key: str,
    job_kind: str,
    input_hash: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT * FROM semantic_jobs
        WHERE repository_id = ? AND snapshot_id = ? AND scope_type = ? AND scope_key = ?
          AND job_kind = ? AND input_hash = ? AND status IN ('pending', 'retry', 'running')
        ORDER BY id DESC LIMIT 1
        """,
        (repository_id, snapshot_id, scope_type, scope_key, job_kind, input_hash),
    ).fetchone()
    return dict(row) if row else None


def _upsert_state(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    scope_type: str,
    scope_key: str,
    status: str,
    reason: str,
    artifact_id: int | None = None,
    artifact_version_id: int | None = None,
    file_fact_id: int | None = None,
    intrinsic_input_hash: str | None = None,
    context_input_hash: str | None = None,
    interface_hash: str | None = None,
    relationship_hash: str | None = None,
    context_fingerprint: str | None = None,
    intrinsic_document_id: int | None = None,
    context_document_id: int | None = None,
) -> None:
    resolved_fact_id = _resolved_fact_id(connection, snapshot_id, artifact_id, file_fact_id)
    connection.execute(
        _UPSERT_STATE_SQL,
        (
            repository_id,
            snapshot_id,
            scope_type,
            scope_key,
            artifact_id,
            artifact_version_id,
            resolved_fact_id,
            status,
            reason,
            intrinsic_input_hash,
            context_input_hash,
            interface_hash,
            relationship_hash,
            context_fingerprint,
            intrinsic_document_id,
            context_document_id,
            utc_now(),
        ),
    )


def _resolved_fact_id(
    connection: sqlite3.Connection,
    snapshot_id: int,
    artifact_id: int | None,
    file_fact_id: int | None,
) -> int | None:
    if file_fact_id is not None or artifact_id is None:
        return file_fact_id
    # Compatibility fallback for non-inventory callers. Repository planning passes the
    # canonical fact directly and therefore never reconstructs a snapshot per module.
    return semantic_fact_id(connection, snapshot_id, artifact_id)


def _states(
    connection: sqlite3.Connection, snapshot_id: int, scope_type: str
) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ?",
        (snapshot_id, scope_type),
    ).fetchall()
    return {str(row["scope_key"]): dict(row) for row in rows}


def _state_intents(
    connection: sqlite3.Connection, states: dict[str, dict[str, Any]]
) -> dict[str, str]:
    result = {}
    for key, state in states.items():
        document_id = state.get("intrinsic_document_id")
        if document_id:
            row = connection.execute(
                "SELECT intent_fingerprint FROM semantic_documents WHERE id = ?", (document_id,)
            ).fetchone()
            if row:
                result[key] = str(row["intent_fingerprint"])
    return result


def _member_documents(
    connection: sqlite3.Connection,
    states: dict[str, dict[str, Any]],
    keys: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    documents = []
    missing = []
    for key in keys:
        state = states.get(key)
        if state is None:
            missing.append(key)
            continue
        document_id = state.get("context_document_id") or state.get("intrinsic_document_id")
        if not document_id:
            missing.append(key)
            continue
        documents.append(_document_by_id(connection, int(document_id)))
    return documents, missing


def _document_by_id(connection: sqlite3.Connection, document_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM semantic_documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise SupersededSemanticJob("A required semantic document no longer exists")
    result = dict(row)
    result["value"] = json.loads(result.pop("value_json") or "{}")
    result["supporting_evidence"] = json.loads(result.pop("supporting_evidence_json") or "[]")
    return result


def _has_active_module_stage(connection: sqlite3.Connection, snapshot_id: int, stage: str) -> bool:
    statuses = (
        ("pending_intrinsic",)
        if stage == "intrinsic"
        else ("pending_intrinsic", "pending_context", "intrinsic_current")
    )
    placeholders = ",".join("?" for _ in statuses)
    count = connection.execute(
        f"""
        SELECT COUNT(*) FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = 'module' AND status IN ({placeholders})
        """,
        (snapshot_id, *statuses),
    ).fetchone()[0]
    return bool(count)


def _has_active_scope(connection: sqlite3.Connection, snapshot_id: int, scope_type: str) -> bool:
    count = connection.execute(
        """
        SELECT COUNT(*) FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = ? AND status = 'pending_synthesis'
        """,
        (snapshot_id, scope_type),
    ).fetchone()[0]
    return bool(count)


def _supersede_duplicate_jobs(
    connection: sqlite3.Connection,
    snapshot_id: int,
    scope_type: str,
    scope_key: str,
    job_kind: str,
) -> None:
    superseded = semantic_job_bulk_transition(("pending", "retry"), "supersede")
    connection.execute(
        """
        UPDATE semantic_jobs SET status = ?, completed_at = ?, metadata_json = '{}',
            error = 'A matching semantic document already exists.'
        WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ? AND job_kind = ?
          AND status IN ('pending', 'retry')
        """,
        (superseded, utc_now(), snapshot_id, scope_type, scope_key, job_kind),
    )
