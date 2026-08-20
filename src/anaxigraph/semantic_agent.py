"""Agent-funded semantic work packets and validated AnaxiIndex write-back."""

from __future__ import annotations

import hmac
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.semantic_agent_protocol import (
    agent_no_work_message,
    agent_no_work_status,
    agent_semantic,
    agent_token_hash,
    agent_worker_fragment,
    clean_agent_identity,
    packetize_agent_request,
)
from anaxigraph.semantic_contract import (
    DOSSIER_SCHEMA,
    SEMANTIC_SCHEMA_VERSION,
    SemanticAnalysisError,
    validated_agent_result,
)
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.storage import utc_now

_MAX_SUBMISSION_BYTES = 1_000_000


class SemanticAgentMixin:
    """Let a connected coding agent execute durable semantic jobs with its own model."""

    def claim_agent_work(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        agent_id: str,
        agent_model: str = "",
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        semantic = agent_semantic(config)
        executor_id = clean_agent_identity(agent_id, "agent_id")
        executor_model = clean_agent_identity(agent_model, "agent_model", required=False)
        root = Path(repository).expanduser().resolve()

        for _ in range(3):
            plan = self.plan(
                repository_id,
                root,
                config,
                retry_failed=retry_failed,
            )
            token = secrets.token_urlsafe(32)
            token_hash = agent_token_hash(token)
            worker_id = f"mcp:{agent_worker_fragment(executor_id)}:{token_hash[:12]}"
            job = self._claim_job(
                repository_id,
                semantic,
                worker_id=worker_id,
                lease_seconds=semantic.agent_lease_seconds,
                lease_token_hash=token_hash,
                executor_id=executor_id,
                executor_model=executor_model or None,
            )
            if job is None:
                status = self.status(repository_id, semantic)
                return {
                    "status": agent_no_work_status(status),
                    "message": agent_no_work_message(status),
                    "plan_stage": plan.stage,
                    "semantic": status,
                }
            try:
                request = self._job_request(job, root, semantic)
            except SupersededSemanticJob as exc:
                self._mark_superseded(int(job["id"]), str(exc))
                continue

            bounded_request, manifest, _ = packetize_agent_request(request, semantic)
            status = self.status(repository_id, semantic)
            return {
                "status": "work",
                "message": (
                    "Analyze this evidence with the coding agent already running in the "
                    "repository. Do not modify source as part of semantic mapping."
                ),
                "job": {
                    "id": int(job["id"]),
                    "kind": job["job_kind"],
                    "scope_type": job["scope_type"],
                    "scope_key": job["scope_key"],
                    "reason": job["reason"],
                    "attempt": int(job["attempts"]),
                },
                "lease": {
                    "token": token,
                    "expires_at": job["lease_expires_at"],
                    "seconds": semantic.agent_lease_seconds,
                },
                "analysis_request": bounded_request,
                "evidence_manifest": manifest,
                "response_contract": {
                    "schema_version": SEMANTIC_SCHEMA_VERSION,
                    "schema_tool": "ANAXIGRAPH_SEMANTIC_SCHEMA",
                    "required_fields": list(DOSSIER_SCHEMA["required"]),
                },
                "next_action": (
                    "Fetch every evidence page when evidence_manifest is present, produce one "
                    "complete dossier, then call ANAXIGRAPH_SEMANTIC_SUBMIT with this job id and "
                    "lease token."
                ),
                "semantic": status,
            }

        status = self.status(repository_id, semantic)
        return {
            "status": "waiting",
            "message": "Stale jobs were superseded while work was being claimed; call again.",
            "semantic": status,
        }

    def agent_evidence_page(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        job_id: int,
        lease_token: str,
        page: int,
    ) -> dict[str, Any]:
        semantic = agent_semantic(config)
        job = self._leased_agent_job(job_id, lease_token, repository_id=repository_id)
        self._validate_current_agent_job(job, repository_id, semantic)
        try:
            request = self._job_request(
                job,
                Path(repository).expanduser().resolve(),
                semantic,
            )
        except SupersededSemanticJob as exc:
            self._mark_superseded(job_id, str(exc))
            raise ValueError(str(exc)) from exc
        _, manifest, pages = packetize_agent_request(request, semantic)
        if not manifest:
            return {
                "status": "embedded",
                "message": "All evidence was embedded in ANAXIGRAPH_SEMANTIC_WORK.",
                "page_count": 0,
            }
        if page < 1 or page > len(pages):
            raise ValueError(f"Evidence page must be between 1 and {len(pages)}")
        return {
            "status": "evidence",
            "job_id": job_id,
            "page": page,
            "page_count": len(pages),
            "evidence_kind": manifest["kind"],
            "payload": pages[page - 1],
        }

    def submit_agent_work(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        job_id: int,
        lease_token: str,
        dossier: dict[str, Any],
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> dict[str, Any]:
        semantic = agent_semantic(config)
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Reported token counts cannot be negative")
        if len(json.dumps(dossier, ensure_ascii=False)) > _MAX_SUBMISSION_BYTES:
            raise ValueError("Semantic dossier exceeds the 1 MB submission limit")
        job = self._leased_agent_job(
            job_id,
            lease_token,
            repository_id=repository_id,
            allow_completed=True,
        )
        if job["status"] == "completed":
            return {
                "status": "already_completed",
                "job_id": job_id,
                "semantic": self.status(repository_id, semantic),
            }
        self._validate_current_agent_job(job, repository_id, semantic)
        try:
            # Rebuild the request immediately before commit. Intrinsic jobs recheck the current
            # bytes; contextual jobs recheck that their required documents still exist.
            self._job_request(
                job,
                Path(repository).expanduser().resolve(),
                semantic,
            )
        except SupersededSemanticJob as exc:
            self._mark_superseded(job_id, str(exc))
            raise ValueError(str(exc)) from exc
        try:
            result = validated_agent_result(
                dossier,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except SemanticAnalysisError as exc:
            raise ValueError(str(exc)) from exc
        self._complete_job(job, result, "agent", semantic)
        plan = self.plan(repository_id, repository, config)
        return {
            "status": "completed",
            "job_id": job_id,
            "completed_scope": job["scope_key"],
            "next_plan_stage": plan.stage,
            "next_action": ("Call ANAXIGRAPH_SEMANTIC_WORK again until it returns complete."),
            "semantic": self.status(repository_id, semantic),
        }

    def release_agent_work(
        self,
        repository_id: int,
        config: AnaxiGraphConfig,
        *,
        job_id: int,
        lease_token: str,
        reason: str,
    ) -> dict[str, Any]:
        semantic = agent_semantic(config)
        job = self._leased_agent_job(
            job_id,
            lease_token,
            repository_id=repository_id,
            allow_completed=True,
        )
        if job["status"] == "completed":
            return {"status": "already_completed", "job_id": job_id}
        message = (reason.strip() or "Coding agent released this work item")[:2_000]
        state = {
            "intrinsic": "pending_intrinsic",
            "context": "pending_context",
            "synthesis": "pending_synthesis",
        }[job["job_kind"]]
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE semantic_jobs SET status = 'retry', attempts = MAX(0, attempts - 1),
                    available_at = ?, worker_id = NULL, lease_expires_at = NULL,
                    lease_token_hash = NULL, error = ?
                WHERE id = ? AND status = 'running'
                """,
                (utc_now(), f"Released by coding agent: {message}", job_id),
            )
            connection.execute(
                """
                UPDATE semantic_scope_states SET status = ?, reason = ?, last_checked_at = ?
                WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
                """,
                (
                    state,
                    f"Released by coding agent: {message}",
                    utc_now(),
                    job["snapshot_id"],
                    job["scope_type"],
                    job["scope_key"],
                ),
            )
        return {
            "status": "released",
            "job_id": job_id,
            "semantic": self.status(repository_id, semantic),
        }

    def _leased_agent_job(
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
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM semantic_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Semantic job does not exist")
        job = dict(row)
        if int(job["repository_id"]) != repository_id:
            raise ValueError("Semantic job does not belong to the selected repository")
        expected = str(job.get("lease_token_hash") or "")
        if not expected or not hmac.compare_digest(expected, agent_token_hash(lease_token)):
            raise ValueError("Semantic lease token is invalid")
        if allow_completed and job["status"] == "completed":
            job["metadata"] = json.loads(job.pop("metadata_json") or "{}")
            return job
        if job["status"] != "running" or not str(job["worker_id"] or "").startswith("mcp:"):
            raise ValueError("Semantic job is not leased to a coding agent")
        expires = datetime.fromisoformat(str(job["lease_expires_at"]))
        if expires < datetime.now(UTC):
            raise ValueError("Semantic work lease expired; claim the job again")
        job["metadata"] = json.loads(job.pop("metadata_json") or "{}")
        return job

    def _validate_current_agent_job(
        self,
        job: dict[str, Any],
        repository_id: int,
        semantic: SemanticConfig,
    ) -> None:
        with self.database.connect() as connection:
            repository = connection.execute(
                "SELECT current_snapshot_id FROM repositories WHERE id = ?",
                (repository_id,),
            ).fetchone()
        matches = (
            int(job["repository_id"]) == repository_id
            and repository is not None
            and int(job["snapshot_id"]) == int(repository["current_snapshot_id"] or 0)
            and job["provider"] == "agent"
            and job["model"] == semantic.model
            and job["prompt_version"] == semantic.prompt_version
            and job["schema_version"] == SEMANTIC_SCHEMA_VERSION
        )
        if not matches:
            self._mark_superseded(int(job["id"]), "Repository or semantic policy changed")
            raise ValueError("Semantic job was superseded by a newer snapshot or policy")
