"""Persist semantic results and update durable job/scope lifecycle state."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from anaxigraph.clock import utc_now
from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION, SemanticResult
from anaxigraph.semantic_graph import _cost, _intent_fingerprint

_DOCUMENT_SQL = """
INSERT INTO semantic_documents(
    repository_id, snapshot_id, scope_type, scope_key, artifact_id,
    artifact_version_id, file_fact_id, previous_document_id, document_kind, input_hash,
    intent_fingerprint, value_json, source, provider, model, executor_id, executor_model,
    prompt_version, schema_version, confidence, supporting_evidence_json, input_tokens,
    output_tokens, estimated_cost_usd, actual_cost_usd, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class SemanticResultMixin:
    def _complete_job(
        self,
        job: dict[str, Any],
        result: SemanticResult,
        provider: str,
        semantic: SemanticConfig,
    ) -> None:
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
        actual_cost = estimated_cost if usage_reported else None
        intent = _intent_fingerprint(result.value)
        source = "coding_agent" if agent_funded else "llm"
        now = utc_now()
        with self.database.transaction() as connection:
            document_id = _insert_document(
                connection,
                job=job,
                result=result,
                provider=provider,
                semantic=semantic,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=estimated_cost,
                actual_cost=actual_cost,
                intent=intent,
                source=source,
                now=now,
            )
            connection.execute(
                """
                UPDATE semantic_jobs SET status = 'completed', completed_at = ?,
                    input_tokens = ?, output_tokens = ?, estimated_cost_usd = ?,
                    actual_cost_usd = ?, worker_id = NULL, lease_expires_at = NULL,
                    error = NULL WHERE id = ?
                """,
                (now, input_tokens, output_tokens, estimated_cost, actual_cost, job["id"]),
            )
            if job["job_kind"] == "intrinsic":
                connection.execute(
                    """
                    UPDATE semantic_scope_states SET status = 'intrinsic_current',
                        intrinsic_document_id = ?, reason = ?, last_checked_at = ?
                    WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
                    """,
                    (
                        document_id,
                        "Intrinsic dossier generated from current source",
                        now,
                        job["snapshot_id"],
                        job["scope_type"],
                        job["scope_key"],
                    ),
                )
                self._write_inventory_claim(
                    connection, job, result, "module_analysis", provider, source
                )
            else:
                connection.execute(
                    """
                    UPDATE semantic_scope_states SET status = 'current',
                        context_document_id = ?, reason = ?, last_checked_at = ?
                    WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
                    """,
                    (
                        document_id,
                        "Contextual understanding matches current evidence",
                        now,
                        job["snapshot_id"],
                        job["scope_type"],
                        job["scope_key"],
                    ),
                )
                if job["scope_type"] == "module":
                    self._write_inventory_claim(
                        connection, job, result, "module_context", provider, source
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

    def _fail_job(self, job: dict[str, Any], exc: Exception) -> bool:
        error = f"{type(exc).__name__}: {exc}"[:4_000]
        retry = int(job["attempts"]) < int(job["max_attempts"])
        status = "retry" if retry else "failed"
        available = datetime.now(UTC) + timedelta(seconds=min(300, 2 ** int(job["attempts"])))
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE semantic_jobs SET status = ?, available_at = ?, completed_at = ?, error = ?
                    , worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL
                WHERE id = ?
                """,
                (
                    status,
                    available.isoformat(),
                    None if retry else utc_now(),
                    error,
                    job["id"],
                ),
            )
            state = {
                "intrinsic": "pending_intrinsic" if retry else "failed_intrinsic",
                "context": "pending_context" if retry else "failed_context",
                "synthesis": "pending_synthesis" if retry else "failed_synthesis",
            }[job["job_kind"]]
            connection.execute(
                """
                UPDATE semantic_scope_states SET status = ?, reason = ?, last_checked_at = ?
                WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
                """,
                (state, error, utc_now(), job["snapshot_id"], job["scope_type"], job["scope_key"]),
            )
        return retry

    def _mark_superseded(self, job_id: int, reason: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE semantic_jobs SET status = 'superseded', completed_at = ?, error = ?,
                    worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL WHERE id = ?
                """,
                (utc_now(), reason[:4_000], job_id),
            )


def _insert_document(
    connection: sqlite3.Connection,
    *,
    job: dict[str, Any],
    result: SemanticResult,
    provider: str,
    semantic: SemanticConfig,
    input_tokens: int,
    output_tokens: int,
    estimated_cost: float,
    actual_cost: float | None,
    intent: str,
    source: str,
    now: str,
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
            intent,
            json.dumps(result.value, sort_keys=True),
            source,
            provider,
            semantic.model,
            job.get("executor_id"),
            job.get("executor_model"),
            semantic.prompt_version,
            SEMANTIC_SCHEMA_VERSION,
            result.confidence,
            json.dumps(result.evidence),
            input_tokens,
            output_tokens,
            estimated_cost,
            actual_cost,
            now,
        ),
    )
    return int(cursor.lastrowid)
