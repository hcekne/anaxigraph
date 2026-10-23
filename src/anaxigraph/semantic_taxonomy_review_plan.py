"""Checkpoint large review passes as independent jobs before global reconciliation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from anaxigraph.semantic_taxonomy_partition import module_batches, needs_partition, partition_limit
from anaxigraph.semantic_taxonomy_requests import review_plan_inputs


def plan_review_jobs(
    connection: Any,
    *,
    repository_id: int,
    snapshot_id: int,
    input_hash: str,
    metadata: dict[str, Any],
    semantic: Any,
    enqueue: Any,
) -> tuple[str, int, str | None]:
    _retire_obsolete_batches(connection, snapshot_id, repository_id, input_hash)
    modules, candidate = review_plan_inputs(connection, metadata)
    batches = _review_batches(
        connection, snapshot_id, input_hash, modules, candidate, metadata, semantic
    )
    if not batches:
        state, created, error = _review_job(
            enqueue,
            scope_key=str(repository_id),
            input_hash=input_hash,
            metadata={**metadata, "review_phase": "reconciliation"},
        )
        return state, int(created), error
    _retire_whole_review(connection, snapshot_id, repository_id, input_hash)
    completed, enqueued, errors = _plan_batches(
        connection, snapshot_id, repository_id, input_hash, metadata, batches, enqueue
    )
    if len(completed) != len(batches):
        return (
            "failed_taxonomy" if errors else "pending_taxonomy_review",
            enqueued,
            errors[0] if errors else None,
        )
    state, created, error = _review_job(
        enqueue,
        scope_key=str(repository_id),
        input_hash=input_hash,
        metadata={
            **metadata,
            "review_phase": "reconciliation",
            "review_group_hash": input_hash,
            "review_batches": completed,
        },
    )
    return state, enqueued + int(created), error


def _plan_batches(
    connection: Any,
    snapshot_id: int,
    repository_id: int,
    input_hash: str,
    metadata: Any,
    batches: Any,
    enqueue: Any,
) -> Any:
    completed, enqueued, errors = [], 0, []
    for index, batch in enumerate(batches, start=1):
        saved, created, error = _plan_batch(
            connection,
            snapshot_id,
            repository_id,
            input_hash,
            metadata,
            batch,
            index,
            len(batches),
            enqueue,
        )
        enqueued += int(created)
        if error:
            errors.append(error)
        if saved:
            completed.append(saved)
    return completed, enqueued, errors


def _review_batches(
    connection: Any,
    snapshot_id: int,
    input_hash: str,
    modules: Any,
    candidate: Any,
    metadata: Any,
    semantic: Any,
) -> Any:
    running = connection.execute(
        """SELECT 1 FROM semantic_jobs WHERE snapshot_id = ? AND input_hash = ?
           AND job_kind = 'taxonomy_review' AND status = 'running'
           AND json_extract(metadata_json, '$.review_phase') IS NOT 'batch'
           AND json_extract(metadata_json, '$.review_batches') IS NULL LIMIT 1""",
        (snapshot_id, input_hash),
    ).fetchone()
    if running:
        return []
    saved_batches = connection.execute(
        """SELECT metadata_json FROM semantic_jobs WHERE snapshot_id = ?
           AND job_kind = 'taxonomy_review'
           AND json_extract(metadata_json, '$.review_group_hash') = ?
           AND json_extract(metadata_json, '$.review_phase') = 'batch'
           AND status != 'superseded'
           ORDER BY json_extract(metadata_json, '$.batch_index')""",
        (snapshot_id, input_hash),
    ).fetchall()
    if saved_batches:
        by_id = {item["document_id"]: item for item in modules}
        batches = [
            [by_id[identifier] for identifier in json.loads(row[0])["document_ids"]]
            for row in saved_batches
        ]
        return batches
    base = {"constraints": metadata["taxonomy_settings"], "hints": metadata["map_hints"]}
    batches = module_batches(modules, semantic.max_source_chars, base, partition_limit(semantic))
    request = {"modules": modules, "candidate_taxonomy": candidate}
    return batches if len(batches) > 1 or needs_partition(request, semantic, len(modules)) else []


def _retire_whole_review(
    connection: Any, snapshot_id: int, repository_id: int, input_hash: str
) -> None:
    # A pending whole-map review from an older planner must not bypass the batches.
    connection.execute(
        """UPDATE semantic_jobs SET status = 'superseded', completed_at = ?, metadata_json = '{}'
           WHERE snapshot_id = ? AND scope_key = ? AND job_kind = 'taxonomy_review'
           AND input_hash = ? AND status IN ('pending', 'retry')
           AND json_extract(metadata_json, '$.review_batches') IS NULL""",
        (datetime.now(UTC).isoformat(), snapshot_id, str(repository_id), input_hash),
    )


def _retire_obsolete_batches(
    connection: Any, snapshot_id: int, repository_id: int, input_hash: str
) -> None:
    connection.execute(
        """UPDATE semantic_jobs SET status = 'superseded', completed_at = ?, metadata_json = '{}',
           worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL,
           error = 'New review evidence replaced this batch.'
           WHERE repository_id = ? AND snapshot_id = ? AND job_kind = 'taxonomy_review'
           AND status IN ('pending', 'retry', 'running')
           AND json_extract(metadata_json, '$.review_phase') = 'batch'
           AND json_extract(metadata_json, '$.review_group_hash') != ?""",
        (datetime.now(UTC).isoformat(), repository_id, snapshot_id, input_hash),
    )


def _plan_batch(
    connection: Any,
    snapshot_id: int,
    repository_id: int,
    input_hash: str,
    metadata: Any,
    batch: Any,
    index: int,
    total: int,
    enqueue: Any,
) -> Any:
    batch_hash = sha256(
        json.dumps(
            {"review": input_hash, "paths": [item["path"] for item in batch]}, sort_keys=True
        ).encode()
    ).hexdigest()
    scope_key = f"{repository_id}:review:{input_hash}:batch:{index}"
    state, created, error = _review_job(
        enqueue,
        scope_key=scope_key,
        input_hash=batch_hash,
        metadata={
            **metadata,
            "document_ids": [item["document_id"] for item in batch],
            "review_phase": "batch",
            "review_group_hash": input_hash,
            "batch_index": index,
            "batch_total": total,
        },
    )
    saved = connection.execute(
        """SELECT d.id FROM semantic_jobs j JOIN semantic_document_values d
           ON d.snapshot_id = j.snapshot_id AND d.scope_key = j.scope_key
           AND d.input_hash = j.input_hash AND d.document_kind = j.job_kind
           WHERE j.snapshot_id = ? AND j.scope_key = ? AND j.input_hash = ?
           AND j.status = 'completed' ORDER BY d.id DESC LIMIT 1""",
        (snapshot_id, scope_key, batch_hash),
    ).fetchone()
    checkpoint = (
        {"document_id": int(saved[0]), "paths": [item["path"] for item in batch]} if saved else None
    )
    return checkpoint, created, error


def _review_job(enqueue: Any, *, scope_key: str, input_hash: str, metadata: Any) -> Any:
    return enqueue(
        scope_key=scope_key,
        input_hash=input_hash,
        metadata=metadata,
        estimated_input_tokens=max(900, len(metadata["document_ids"]) * 160),
    )
