"""Durable semantic job admission, leases, release, and expiry recovery."""

from __future__ import annotations

import contextlib
import hmac
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator

from anaxigraph.clock import utc_now
from anaxigraph.semantic_agent_protocol import agent_token_hash
from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_contract import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_job_state import (
    semantic_job_bulk_transition,
    semantic_job_transition,
)
from anaxigraph.semantic_lease_claim import claim_next_job
from anaxigraph.semantic_ports import SemanticPersistencePort


class SemanticLeaseService:
    def __init__(
        self,
        database: SemanticIndex,
        persistence: SemanticPersistencePort,
    ) -> None:
        self._database = database
        self._persistence = persistence

    def claim_job(
        self,
        repository_id: int,
        semantic: SemanticConfig,
        *,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
        lease_token_hash: str | None = None,
        executor_id: str | None = None,
        executor_model: str | None = None,
    ) -> dict[str, Any] | None:
        return claim_next_job(
            self._database,
            repository_id,
            semantic,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            lease_token_hash=lease_token_hash,
            executor_id=executor_id,
            executor_model=executor_model,
        )

    @contextlib.contextmanager
    def job_lease(self, job: dict[str, Any], semantic: SemanticConfig) -> Iterator[None]:
        stopped = threading.Event()
        lease_seconds = max(90, semantic.timeout_seconds + 60)

        def heartbeat() -> None:
            while not stopped.wait(min(30, max(10, lease_seconds // 3))):
                expires = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
                with self._database.connect() as connection:
                    connection.execute(
                        """
                        UPDATE semantic_jobs SET lease_expires_at = ?
                        WHERE id = ? AND status = 'running' AND worker_id = ?
                        """,
                        (expires, job["id"], job["worker_id"]),
                    )

        thread = threading.Thread(
            target=heartbeat,
            name=f"anaxigraph-semantic-lease-{job['id']}",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=1)

    def leased_agent_job(
        self,
        job_id: int,
        lease_token: str,
        *,
        repository_id: int,
        allow_completed: bool = False,
    ) -> dict[str, Any]:
        if job_id < 1:
            raise ValueError("A positive semantic job id is required")
        if not lease_token or len(lease_token) > 512:
            raise ValueError("A valid semantic lease token is required")
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM semantic_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Semantic job does not exist")
        job = dict(row)
        _validate_agent_lease(job, lease_token, repository_id, allow_completed)
        job["metadata"] = json.loads(job.pop("metadata_json") or "{}")
        return job

    def validate_current_agent_job(
        self,
        job: dict[str, Any],
        repository_id: int,
        semantic: SemanticConfig,
    ) -> None:
        with self._database.connect() as connection:
            repository = connection.execute(
                "SELECT current_snapshot_id FROM repositories WHERE id = ?",
                (repository_id,),
            ).fetchone()
        matches = (
            int(job["repository_id"]) == repository_id
            and repository is not None
            and int(job["snapshot_id"]) == int(repository["current_snapshot_id"] or 0)
            and job["provider"] == "agent"
            and job["prompt_version"] == semantic.prompt_version
            and job["schema_version"] == SEMANTIC_SCHEMA_VERSION
        )
        if not matches:
            self._persistence.mark_superseded(
                int(job["id"]), "Repository or semantic policy changed"
            )
            raise ValueError("Semantic job was superseded by a newer snapshot or policy")

    def release_agent_job(self, job: dict[str, Any], reason: str) -> None:
        message = (reason.strip() or "Coding agent released this work item")[:2_000]
        job_status = semantic_job_transition(str(job["status"]), "release")
        state = {
            "intrinsic": "pending_intrinsic",
            "context": "pending_context",
            "synthesis": "pending_synthesis",
            "taxonomy_proposal": "pending_taxonomy_proposal",
            "taxonomy_review": "pending_taxonomy_review",
            "pattern_assessment": "pending_pattern_assessment",
            "pattern_review": "pending_pattern_review",
        }[job["job_kind"]]
        now = utc_now()
        with self._database.transaction() as connection:
            connection.execute(
                """
                UPDATE semantic_jobs SET status = ?, attempts = MAX(0, attempts - 1),
                    available_at = ?, worker_id = NULL, lease_expires_at = NULL,
                    lease_token_hash = NULL, error = ?
                WHERE id = ? AND status = 'running'
                """,
                (job_status, now, f"Released by coding agent: {message}", job["id"]),
            )
            connection.execute(
                """
                UPDATE semantic_scope_states SET status = ?, reason = ?, last_checked_at = ?
                WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
                """,
                (
                    state,
                    f"Released by coding agent: {message}",
                    now,
                    job["snapshot_id"],
                    job["scope_type"],
                    job["scope_key"],
                ),
            )

    def reconcile(
        self,
        connection: sqlite3.Connection,
        repository_id: int,
        snapshot_id: int,
        semantic: SemanticConfig,
    ) -> None:
        now = utc_now()
        stale_before = (
            datetime.now(UTC) - timedelta(seconds=max(90, semantic.timeout_seconds + 60))
        ).isoformat()
        retry = semantic_job_transition("running", "lease_expired")
        superseded = semantic_job_bulk_transition(("pending", "retry", "running"), "supersede")
        connection.execute(
            """
            UPDATE semantic_jobs SET status = ?, available_at = ?,
                worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL,
                error = 'The previous worker lease expired; this job was safely requeued.'
            WHERE repository_id = ? AND status = 'running'
              AND (lease_expires_at < ? OR (lease_expires_at IS NULL AND started_at < ?))
            """,
            (retry, now, repository_id, now, stale_before),
        )
        connection.execute(
            """
            UPDATE semantic_jobs SET status = ?, completed_at = ?,
                worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL,
                error = 'A newer repository snapshot replaced this job.'
            WHERE repository_id = ? AND snapshot_id != ?
              AND status IN ('pending', 'retry', 'running')
            """,
            (superseded, now, repository_id, snapshot_id),
        )


def _validate_agent_lease(
    job: dict[str, Any],
    lease_token: str,
    repository_id: int,
    allow_completed: bool,
) -> None:
    if int(job["repository_id"]) != repository_id:
        raise ValueError("Semantic job does not belong to the selected repository")
    expected = str(job.get("lease_token_hash") or "")
    if not expected or not hmac.compare_digest(expected, agent_token_hash(lease_token)):
        raise ValueError("Semantic lease token is invalid")
    if allow_completed and job["status"] == "completed":
        return
    if job["status"] != "running" or not str(job["worker_id"] or "").startswith("mcp:"):
        raise ValueError("Semantic job is not leased to a coding agent")
    expires = datetime.fromisoformat(str(job["lease_expires_at"]))
    if expires < datetime.now(UTC):
        raise ValueError("Semantic work lease expired; claim the job again")
