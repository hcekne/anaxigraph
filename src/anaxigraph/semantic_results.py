"""Persist semantic results and update durable job/scope lifecycle state."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from anaxigraph.clock import utc_now
from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION, SemanticResult
from anaxigraph.semantic_graph import _cost, _intent_fingerprint
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_job_state import (
    PATTERN_METADATA_RETENTION,
    semantic_job_transition,
    semantic_scope_status,
)
from anaxigraph.semantic_pattern_results import complete_pattern_job
from anaxigraph.semantic_taxonomy_results import complete_taxonomy_job

_DOCUMENT_SQL = """
INSERT INTO semantic_documents(
    repository_id, snapshot_id, scope_type, scope_key, artifact_id,
    artifact_version_id, file_fact_id, previous_document_id, document_kind, input_hash,
    intent_fingerprint, value_json, source, provider, model, executor_id, executor_model,
    prompt_version, schema_version, confidence, supporting_evidence_json, input_tokens,
    output_tokens, estimated_cost_usd, actual_cost_usd, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


@dataclass(frozen=True, slots=True)
class _Completion:
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    actual_cost: float | None
    intent: str
    source: str
    now: str
    target_status: str


class SemanticPersistenceService:
    def __init__(self, database: SemanticIndex) -> None:
        self._database = database

    def complete_job(
        self,
        job: dict[str, Any],
        result: SemanticResult,
        provider: str,
        semantic: SemanticConfig,
    ) -> None:
        completion = _completion(job, result, provider, semantic)
        with self._database.transaction() as connection:
            document_id = _insert_document(
                connection,
                job=job,
                result=result,
                provider=provider,
                semantic=semantic,
                completion=completion,
            )
            _finish_job(connection, job, completion)
            if job["job_kind"] in {"taxonomy_proposal", "taxonomy_review"}:
                complete_taxonomy_job(
                    connection,
                    job=job,
                    result=result,
                    document_id=document_id,
                    provider=provider,
                    source=completion.source,
                    semantic=semantic,
                    now=completion.now,
                )
                return
            if job["job_kind"] in {"pattern_assessment", "pattern_review"}:
                complete_pattern_job(
                    connection,
                    job=job,
                    result=result,
                    document_id=document_id,
                    semantic=semantic,
                    now=completion.now,
                )
                return
            self._complete_scope(connection, job, result, document_id, provider, completion)

    def _complete_scope(
        self,
        connection: sqlite3.Connection,
        job: dict[str, Any],
        result: SemanticResult,
        document_id: int,
        provider: str,
        completion: _Completion,
    ) -> None:
        intrinsic = job["job_kind"] == "intrinsic"
        state = "intrinsic_current" if intrinsic else "current"
        column = "intrinsic_document_id" if intrinsic else "context_document_id"
        reason = (
            "Intrinsic dossier generated from current source"
            if intrinsic
            else "Contextual understanding matches current evidence"
        )
        connection.execute(
            f"""
            UPDATE semantic_scope_states SET status = ?, {column} = ?,
                reason = ?, last_checked_at = ?
            WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
            """,
            (
                state,
                document_id,
                reason,
                completion.now,
                job["snapshot_id"],
                job["scope_type"],
                job["scope_key"],
            ),
        )
        if job["scope_type"] == "module":
            claim_type = "module_analysis" if intrinsic else "module_context"
            self._write_inventory_claim(
                connection, job, result, claim_type, provider, completion.source
            )

    def _write_inventory_claim(
        self,
        connection: sqlite3.Connection,
        job: dict[str, Any],
        result: SemanticResult,
        claim_type: str,
        provider: str,
        source: str,
    ) -> None:
        if not job.get("file_fact_id"):
            return
        connection.execute(
            "DELETE FROM semantic_claims WHERE file_fact_id = ? AND claim_type = ?",
            (job["file_fact_id"], claim_type),
        )
        connection.execute(
            """
            INSERT INTO semantic_claims(
                artifact_version_id, file_fact_id, claim_type, value_json, source, provider, model,
                prompt_version, created_at, confidence, supporting_evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                None,
                job["file_fact_id"],
                claim_type,
                json.dumps(result.value, sort_keys=True),
                source,
                provider,
                job["model"],
                job["prompt_version"],
                utc_now(),
                result.confidence,
                json.dumps(result.evidence),
            ),
        )

    def fail_job(
        self,
        job: dict[str, Any],
        exc: Exception,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> bool:
        error = f"{type(exc).__name__}: {exc}"[:4_000]
        retry = int(job["attempts"]) < int(job["max_attempts"])
        status = semantic_job_transition(str(job["status"]), "retry" if retry else "fail")
        available = datetime.now(UTC) + timedelta(seconds=min(300, 2 ** int(job["attempts"])))
        with self._database.transaction() as connection:
            connection.execute(
                """
                UPDATE semantic_jobs SET status = ?, available_at = ?, completed_at = ?, error = ?,
                    input_tokens = input_tokens + ?, output_tokens = output_tokens + ?,
                    worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL
                WHERE id = ?
                """,
                (
                    status,
                    available.isoformat(),
                    None if retry else utc_now(),
                    error,
                    max(0, int(input_tokens)),
                    max(0, int(output_tokens)),
                    job["id"],
                ),
            )
            state = semantic_scope_status(str(job["job_kind"]), failed=not retry)
            connection.execute(
                """
                UPDATE semantic_scope_states SET status = ?, reason = ?, last_checked_at = ?
                WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
                """,
                (state, error, utc_now(), job["snapshot_id"], job["scope_type"], job["scope_key"]),
            )
        return retry

    def mark_superseded(self, job_id: int, reason: str) -> None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM semantic_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] == "superseded":
                return
            target_status = semantic_job_transition(str(row["status"]), "supersede")
            connection.execute(
                """
                UPDATE semantic_jobs SET status = ?, completed_at = ?, error = ?,
                    worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL,
                    metadata_json = '{}' WHERE id = ?
                """,
                (target_status, utc_now(), reason[:4_000], job_id),
            )


def _insert_document(
    connection: sqlite3.Connection,
    *,
    job: dict[str, Any],
    result: SemanticResult,
    provider: str,
    semantic: SemanticConfig,
    completion: _Completion,
) -> int:
    cursor = connection.execute(
        _DOCUMENT_SQL,
        (
            job["repository_id"],
            job["snapshot_id"],
            job["scope_type"],
            job["scope_key"],
            job["artifact_id"],
            None,
            job["file_fact_id"],
            job["metadata"].get("previous_document_id"),
            job["job_kind"],
            job["input_hash"],
            completion.intent,
            json.dumps(result.value, sort_keys=True),
            completion.source,
            provider,
            semantic.model,
            job.get("executor_id"),
            job.get("executor_model"),
            semantic.prompt_version,
            SEMANTIC_SCHEMA_VERSION,
            result.confidence,
            json.dumps(result.evidence),
            completion.input_tokens,
            completion.output_tokens,
            completion.estimated_cost,
            completion.actual_cost,
            completion.now,
        ),
    )
    return int(cursor.lastrowid)


def _completion(
    job: dict[str, Any],
    result: SemanticResult,
    provider: str,
    semantic: SemanticConfig,
) -> _Completion:
    usage_reported = result.input_tokens > 0 or result.output_tokens > 0
    agent_funded = provider == "agent"
    input_tokens = (
        result.input_tokens
        if usage_reported or agent_funded
        else max(1, int(job["estimated_input_tokens"]))
    )
    output_tokens = (
        result.output_tokens
        if usage_reported or agent_funded
        else max(1, len(json.dumps(result.value)) // 4)
    )
    estimated_cost = _cost(input_tokens, output_tokens, semantic)
    return _Completion(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
        actual_cost=estimated_cost if usage_reported else None,
        intent=_intent_fingerprint(result.value),
        source="coding_agent" if agent_funded else "llm",
        now=utc_now(),
        target_status=semantic_job_transition(str(job["status"]), "complete"),
    )


def _finish_job(
    connection: sqlite3.Connection,
    job: dict[str, Any],
    completion: _Completion,
) -> None:
    retained_metadata = {}
    if job["job_kind"] == "pattern_assessment":
        retained_metadata = {
            "retention": PATTERN_METADATA_RETENTION,
            "candidate": job["metadata"].get("candidate"),
        }
    connection.execute(
        """
        UPDATE semantic_jobs SET status = ?, completed_at = ?,
            input_tokens = input_tokens + ?, output_tokens = output_tokens + ?, estimated_cost_usd = ?,
            actual_cost_usd = ?, worker_id = NULL, lease_expires_at = NULL,
            error = NULL, metadata_json = ? WHERE id = ?
        """,
        (
            completion.target_status,
            completion.now,
            completion.input_tokens,
            completion.output_tokens,
            completion.estimated_cost,
            completion.actual_cost,
            json.dumps(retained_metadata, sort_keys=True),
            job["id"],
        ),
    )
