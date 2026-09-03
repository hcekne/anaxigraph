"""Queue or reuse one fresh-eyes stage job against the durable semantic queue."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.semantic_fresh_eyes_evidence import parsed_document
from anaxigraph.semantic_records import (
    _ensure_job,
    _latest_document,
    _matching_document,
    _upsert_state,
)

upsert_state = _upsert_state


def document_or_job(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    scope_key: str,
    job_kind: str,
    reason: str,
    priority: int,
    input_hash: str,
    scope: str,
    metadata: dict[str, Any],
    semantic: Any,
    retry_failed: bool,
) -> tuple[dict[str, Any] | None, int]:
    document = _matching_document(
        connection,
        repository_id,
        scope,
        scope_key,
        job_kind,
        input_hash,
        semantic,
    )
    if document is not None:
        upsert_stage(connection, scope, repository_id, snapshot_id, scope_key, input_hash, document)
        return parsed_document(document), 0
    return queue_stage_job(
        connection,
        scope=scope,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_key=scope_key,
        job_kind=job_kind,
        reason=reason,
        priority=priority,
        input_hash=input_hash,
        metadata=metadata,
        semantic=semantic,
        retry_failed=retry_failed,
    )


def queue_stage_job(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    scope: str,
    scope_key: str,
    job_kind: str,
    reason: str,
    priority: int,
    input_hash: str,
    metadata: dict[str, Any],
    semantic: Any,
    retry_failed: bool,
) -> tuple[None, int]:
    previous = _latest_document(connection, repository_id, scope, scope_key, job_kind)
    scope_status, created, error = _ensure_job(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type=scope,
        scope_key=scope_key,
        artifact_id=None,
        artifact_version_id=None,
        job_kind=job_kind,
        reason=reason,
        priority=priority,
        input_hash=input_hash,
        semantic=semantic,
        estimated_input_tokens=max(400, len(json.dumps(metadata, default=str)) // 4),
        metadata={**metadata, "previous_document_id": previous["id"] if previous else None},
        retry_failed=retry_failed,
    )
    _upsert_state(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type=scope,
        scope_key=scope_key,
        status=scope_status,
        reason=error or reason,
        context_input_hash=input_hash,
        context_fingerprint=input_hash,
    )
    return None, int(created)


def upsert_stage(
    connection: sqlite3.Connection,
    scope: str,
    repository_id: int,
    snapshot_id: int,
    scope_key: str,
    input_hash: str,
    document: dict[str, Any],
) -> None:
    _upsert_state(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type=scope,
        scope_key=scope_key,
        status="current",
        reason="Fresh-eyes stage matches its versioned evidence",
        context_input_hash=input_hash,
        context_fingerprint=input_hash,
        context_document_id=int(document["id"]),
    )
