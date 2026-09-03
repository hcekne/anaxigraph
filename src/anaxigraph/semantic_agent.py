"""Agent-funded semantic work packets and validated AnaxiIndex write-back."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.semantic_agent_contracts import (
    SemanticAgentContractService,
    agent_reported_usage,
)
from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.semantic_lease_claim import claimant_family
from anaxigraph.semantic_leases import SemanticLeaseService
from anaxigraph.semantic_ports import (
    SemanticEvidencePort,
    SemanticPersistencePort,
    SemanticPlanningPort,
    SemanticReportingPort,
)


class SemanticAgentService:
    """Let a connected coding agent execute durable semantic jobs with its own model."""

    def __init__(
        self,
        planning: SemanticPlanningPort,
        reporting: SemanticReportingPort,
        leases: SemanticLeaseService,
        evidence: SemanticEvidencePort,
        persistence: SemanticPersistencePort,
    ) -> None:
        self._planning = planning
        self._reporting = reporting
        self._leases = leases
        self._evidence = evidence
        self._contracts = SemanticAgentContractService()
        self._persistence = persistence

    def claim_agent_work(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        agent_id: str,
        agent_model: str = "",
        agent_effort: str = "",
        executor_family: str = "",
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        semantic = self._contracts.semantic(config)
        executor = self._contracts.identity(agent_id, agent_model, agent_effort)
        family = claimant_family(executor[0], executor_family)
        root = Path(repository).expanduser().resolve()
        planned_stage = "queued"
        planned = False
        for _ in range(3):
            job, token = self._claim(repository_id, semantic, executor, family)
            if job is None:
                status = self._reporting.status(repository_id, semantic)
                if _queue_active(status) or planned:
                    waiting = self._leases.pinned_for_other_executors(repository_id, family)
                    if waiting:
                        return self._contracts.waiting_for_executor_response(
                            status, planned_stage, waiting, root
                        )
                    return self._contracts.no_work_response(status, planned_stage)
                plan = self._planning.plan(
                    repository_id,
                    root,
                    config,
                    retry_failed=retry_failed,
                )
                planned_stage = plan.stage
                planned = True
                continue
            packet = self._work_packet(repository_id, root, semantic, job, token)
            if packet is not None:
                return packet

        status = self._reporting.status(repository_id, semantic)
        return self._contracts.waiting_response(status)

    def _claim(
        self,
        repository_id: int,
        semantic: SemanticConfig,
        executor: tuple[str, str, str],
        family: str,
    ) -> tuple[dict[str, Any] | None, str]:
        executor_id, executor_model, executor_effort = executor
        token, token_hash, worker_id = self._contracts.lease_identity(executor_id)
        job = self._leases.claim_job(
            repository_id,
            semantic,
            worker_id=worker_id,
            lease_seconds=semantic.agent_lease_seconds,
            lease_token_hash=token_hash,
            executor_id=executor_id,
            executor_model=executor_model or None,
            executor_effort=executor_effort or None,
            executor_family=family,
        )
        return job, token

    def _work_packet(
        self,
        repository_id: int,
        root: Path,
        semantic: SemanticConfig,
        job: dict[str, Any],
        token: str,
    ) -> dict[str, Any] | None:
        try:
            request = self._evidence.job_request(job, root, semantic)
        except SupersededSemanticJob as exc:
            self._persistence.mark_superseded(int(job["id"]), str(exc))
            return None
        bounded_request, manifest, _ = self._contracts.packetize(request, semantic)
        status = self._reporting.status(repository_id, semantic)
        return self._contracts.work_response(
            job, token, bounded_request, request, manifest, semantic, status
        )

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
        semantic = self._contracts.semantic(config)
        job = self._leases.leased_agent_job(job_id, lease_token, repository_id=repository_id)
        self._leases.validate_current_agent_job(job, repository_id, semantic)
        try:
            request = self._evidence.job_request(
                job,
                Path(repository).expanduser().resolve(),
                semantic,
            )
        except SupersededSemanticJob as exc:
            self._persistence.mark_superseded(job_id, str(exc))
            raise ValueError(str(exc)) from exc
        _, manifest, pages = self._contracts.packetize(request, semantic)
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
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> dict[str, Any]:
        semantic = self._contracts.semantic(config)
        job = self._leases.leased_agent_job(
            job_id,
            lease_token,
            repository_id=repository_id,
            allow_completed=True,
        )
        if job["status"] == "completed":
            return self._already_completed(repository_id, semantic, job_id)
        self._leases.validate_current_agent_job(job, repository_id, semantic)
        try:
            # Rebuild the request immediately before commit. Intrinsic jobs recheck the current
            # bytes; contextual jobs recheck that their required documents still exist.
            request = self._evidence.job_request(
                job,
                Path(repository).expanduser().resolve(),
                semantic,
            )
        except SupersededSemanticJob as exc:
            self._persistence.mark_superseded(job_id, str(exc))
            raise ValueError(str(exc)) from exc
        result = self._contracts.validate_submission(
            dossier,
            request,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
        )
        self._persistence.complete_job(job, result, "agent", semantic)
        status = self._reporting.status(repository_id, semantic)
        return self._contracts.completed_response(job, "claim_next", status)

    def _already_completed(
        self, repository_id: int, semantic: SemanticConfig, job_id: int
    ) -> dict[str, Any]:
        return {
            "status": "already_completed",
            "job_id": job_id,
            "semantic": self._reporting.status(repository_id, semantic),
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
        semantic = self._contracts.semantic(config)
        job = self._leases.leased_agent_job(
            job_id,
            lease_token,
            repository_id=repository_id,
            allow_completed=True,
        )
        if job["status"] == "completed":
            return {"status": "already_completed", "job_id": job_id}
        self._leases.release_agent_job(job, reason)
        return {
            "status": "released",
            "job_id": job_id,
            "semantic": self._reporting.status(repository_id, semantic),
        }

    def fail_agent_work(
        self,
        repository_id: int,
        config: AnaxiGraphConfig,
        *,
        job_id: int,
        lease_token: str,
        reason: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> dict[str, Any]:
        semantic = self._contracts.semantic(config)
        job = self._leases.leased_agent_job(
            job_id,
            lease_token,
            repository_id=repository_id,
            allow_completed=True,
        )
        if job["status"] == "completed":
            return {"status": "already_completed", "job_id": job_id}
        self._leases.validate_current_agent_job(job, repository_id, semantic)
        usage = agent_reported_usage(
            input_tokens,
            output_tokens,
            cache_read_input_tokens,
            cache_creation_input_tokens,
        )
        retry = self._persistence.fail_job(
            job,
            SemanticAnalysisError(reason.strip() or "Coding agent model execution failed"),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            usage_reported=usage.reported,
        )
        return {
            "status": "retry" if retry else "failed",
            "job_id": job_id,
            "semantic": self._reporting.status(repository_id, semantic),
        }


def _queue_active(status: dict[str, Any]) -> bool:
    jobs = status.get("jobs") or {}
    return any(int(jobs.get(key, 0)) > 0 for key in ("pending", "retry", "running"))
