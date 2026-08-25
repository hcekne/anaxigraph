"""Durable state helpers for sparse pattern work."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.clock import utc_now
from anaxigraph.semantic_freshness import semantic_record_expired
from anaxigraph.semantic_job_state import semantic_job_bulk_transition
from anaxigraph.semantic_records import _reset_failed_job, _upsert_state

PATTERN_PLAN_SCOPE = "default"


def baseline_documents(connection: sqlite3.Connection, snapshot_id: int) -> list[tuple[Any, ...]]:
    rows = connection.execute(
        """
        SELECT scope_type, scope_key, status, intrinsic_document_id, context_document_id
        FROM semantic_scope_states WHERE snapshot_id = ?
          AND scope_type IN ('module', 'taxonomy', 'group', 'repository')
        ORDER BY scope_type, scope_key
        """,
        (snapshot_id,),
    ).fetchall()
    return [tuple(row) for row in rows]


def cached_plan_size(
    connection: sqlite3.Connection,
    snapshot_id: int,
    plan_hash: str,
    max_age_days: int,
) -> int | None:
    row = connection.execute(
        """
        SELECT context_input_hash, interface_hash FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = 'pattern_plan' AND scope_key = ?
        """,
        (snapshot_id, PATTERN_PLAN_SCOPE),
    ).fetchone()
    if row is None or row["context_input_hash"] != plan_hash:
        return None
    expected = int(row["interface_hash"] or 0)
    actual = connection.execute(
        "SELECT COUNT(*) FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = 'pattern'",
        (snapshot_id,),
    ).fetchone()[0]
    if actual != expected or _has_expired_result(connection, snapshot_id, max_age_days):
        return None
    return expected


def _has_expired_result(
    connection: sqlite3.Connection, snapshot_id: int, max_age_days: int
) -> bool:
    if max_age_days <= 0:
        return False
    rows = connection.execute(
        """
        SELECT sd.created_at FROM semantic_scope_states ss
        JOIN semantic_documents sd
          ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'pattern' AND ss.status = 'current'
        """,
        (snapshot_id,),
    ).fetchall()
    return any(semantic_record_expired(str(row["created_at"]), max_age_days) for row in rows)


def patterns_complete(connection: sqlite3.Connection, snapshot_id: int, expected: int) -> bool:
    incomplete = connection.execute(
        """
        SELECT COUNT(*) FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = 'pattern' AND status != 'current'
        """,
        (snapshot_id,),
    ).fetchone()[0]
    actual = connection.execute(
        "SELECT COUNT(*) FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = 'pattern'",
        (snapshot_id,),
    ).fetchone()[0]
    return actual == expected and incomplete == 0


def retry_failed_patterns(connection: sqlite3.Connection, snapshot_id: int) -> None:
    rows = connection.execute(
        """
        SELECT id, job_kind, scope_key FROM semantic_jobs
        WHERE snapshot_id = ? AND scope_type = 'pattern' AND status = 'failed'
        """,
        (snapshot_id,),
    ).fetchall()
    for row in rows:
        _reset_failed_job(connection, int(row["id"]))
        pending = (
            "pending_pattern_assessment"
            if row["job_kind"] == "pattern_assessment"
            else "pending_pattern_review"
        )
        connection.execute(
            """
            UPDATE semantic_scope_states SET status = ?, reason = ?, last_checked_at = ?
            WHERE snapshot_id = ? AND scope_type = 'pattern' AND scope_key = ?
            """,
            (pending, "Retrying failed pattern work", utc_now(), snapshot_id, row["scope_key"]),
        )


def reset_changed_candidate(
    connection: sqlite3.Connection, snapshot_id: int, scope_key: str, assessment_hash: str
) -> None:
    row = connection.execute(
        """
        SELECT intrinsic_input_hash FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = 'pattern' AND scope_key = ?
        """,
        (snapshot_id, scope_key),
    ).fetchone()
    if row is None or row["intrinsic_input_hash"] == assessment_hash:
        return
    supersede_scope_jobs(connection, snapshot_id, {scope_key})
    connection.execute(
        "DELETE FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = 'pattern' AND scope_key = ?",
        (snapshot_id, scope_key),
    )


def remove_obsolete_candidates(
    connection: sqlite3.Connection, snapshot_id: int, selected: set[str]
) -> None:
    rows = connection.execute(
        "SELECT scope_key FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = 'pattern'",
        (snapshot_id,),
    ).fetchall()
    obsolete = {str(row["scope_key"]) for row in rows} - selected
    if not obsolete:
        return
    supersede_scope_jobs(connection, snapshot_id, obsolete)
    placeholders = ",".join("?" for _ in obsolete)
    connection.execute(
        f"DELETE FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = 'pattern' AND scope_key IN ({placeholders})",
        (snapshot_id, *sorted(obsolete)),
    )


def supersede_scope_jobs(
    connection: sqlite3.Connection, snapshot_id: int, scope_keys: set[str]
) -> None:
    placeholders = ",".join("?" for _ in scope_keys)
    superseded = semantic_job_bulk_transition(("pending", "retry", "running"), "supersede")
    connection.execute(
        f"""
        UPDATE semantic_jobs SET status = ?, completed_at = ?, worker_id = NULL,
            lease_expires_at = NULL, lease_token_hash = NULL,
            error = 'The sparse candidate plan no longer selects this pattern pair.'
        WHERE snapshot_id = ? AND scope_type = 'pattern'
          AND scope_key IN ({placeholders}) AND status IN ('pending', 'retry', 'running')
        """,
        (superseded, utc_now(), snapshot_id, *sorted(scope_keys)),
    )


def supersede_running_mismatch(
    connection: sqlite3.Connection,
    snapshot_id: int,
    scope_key: str,
    job_kind: str,
    input_hash: str,
) -> None:
    superseded = semantic_job_bulk_transition(("running",), "supersede")
    connection.execute(
        """
        UPDATE semantic_jobs SET status = ?, completed_at = ?, worker_id = NULL,
            lease_expires_at = NULL, lease_token_hash = NULL,
            error = 'A newer pattern input replaced this leased job.'
        WHERE snapshot_id = ? AND scope_type = 'pattern' AND scope_key = ?
          AND job_kind = ? AND input_hash != ? AND status = 'running'
        """,
        (superseded, utc_now(), snapshot_id, scope_key, job_kind, input_hash),
    )


def artifact_id(
    connection: sqlite3.Connection, repository_id: int, candidate: dict[str, Any]
) -> int | None:
    path = str((candidate.get("target") or {}).get("path") or "")
    if not path:
        return None
    row = connection.execute(
        "SELECT id FROM artifacts WHERE repository_id = ? AND canonical_path = ?",
        (repository_id, path),
    ).fetchone()
    return int(row["id"]) if row else None


def estimated_tokens(metadata: dict[str, Any]) -> int:
    return max(600, min(20_000, len(json.dumps(metadata, default=str)) // 4))


def upsert_pattern_state(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    scope_key: str,
    candidate: dict[str, Any],
    **values: Any,
) -> None:
    _upsert_state(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type="pattern",
        scope_key=scope_key,
        artifact_id=artifact_id(connection, repository_id, candidate),
        status=values["status"],
        reason=values["reason"],
        intrinsic_input_hash=values["assessment_hash"],
        context_input_hash=values.get("review_hash"),
        intrinsic_document_id=values.get("assessment_document_id"),
        context_document_id=values.get("review_document_id"),
    )
