"""Semantic queue execution, concurrency, budgets, and worker leases."""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.semantic import create_semantic_provider
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.semantic_job_state import SemanticLeaseLost
from anaxigraph.semantic_leases import SemanticLeaseService
from anaxigraph.semantic_ports import (
    SemanticEvidencePort,
    SemanticPersistencePort,
    SemanticPlanningPort,
    SemanticReportingPort,
)
from anaxigraph.semantic_request_analysis import analyze_semantic_request


def _bootstrap_state(
    limit: int | None,
    semantic: SemanticConfig,
    until_complete: bool,
) -> tuple[int | None, dict[str, Any], list[str]]:
    bounded = max(1, limit if limit is not None else semantic.max_jobs_per_run)
    remaining = None if until_complete else bounded
    total = {"planned": 0, "processed": 0, "completed": 0, "failed": 0, "retry": 0}
    return remaining, total, []


def _merge_run_counts(total: dict[str, Any], run: dict[str, Any]) -> None:
    for key in ("processed", "completed", "failed", "retry"):
        total[key] += int(run[key])


def _stop_bootstrap(plan_only: bool, plan: Any, remaining: int | None) -> bool:
    paused = bool(plan.status.get("budget", {}).get("paused"))
    exhausted = remaining is not None and remaining <= 0
    return plan_only or plan.active_jobs == 0 or exhausted or paused


def _bootstrap_passes(until_complete: bool, semantic: SemanticConfig) -> Any:
    return itertools.count() if until_complete else range(12 + semantic.taxonomy.review_passes)


def _validate_job_execution(
    semantic: SemanticConfig,
    execution: SemanticConfig | None,
) -> None:
    if not semantic.enabled:
        raise ValueError("Semantic analysis is disabled in .anaxigraph.yml")
    if semantic.provider == "agent" and execution is None:
        raise ValueError(
            "Agent-funded semantic jobs are executed through AnaxiMCP, not the local "
            "semantic worker; pass a local agent executor or use the MCP work loop"
        )
    if execution is not None and semantic.provider != "agent":
        raise ValueError("A local agent executor can only bridge semantic.provider=agent")
    create_semantic_provider(execution or semantic)


def _worker_limits(
    semantic: SemanticConfig,
    execution: SemanticConfig | None,
    bounded: int,
) -> tuple[int, int]:
    requested = execution.max_parallel_jobs if execution else semantic.max_parallel_jobs
    return requested, min(semantic.max_parallel_jobs, requested, bounded)


def _wave_execution(
    execution: SemanticConfig | None,
    requested_workers: int,
    wave: int,
) -> SemanticConfig | None:
    if execution is None:
        return None
    return replace(execution, max_parallel_jobs=max(1, requested_workers // wave))


def _job_counts() -> dict[str, int]:
    return {
        key: 0 for key in ("processed", "completed", "failed", "retry", "superseded", "lease_lost")
    }


def _count_job_results(counts: dict[str, int], results: list[str]) -> None:
    counts["processed"] += len(results)
    for result in results:
        counts[result] += 1


def _bootstrap_result(
    total: dict[str, Any], stages: list[str], semantic: dict[str, Any]
) -> dict[str, Any]:
    return {
        **total,
        "stages": list(dict.fromkeys(stages)),
        "semantic": semantic,
    }


class SemanticRunnerService:
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
        self._persistence = persistence

    def run_jobs(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        limit: int | None = None,
        execution_semantic: SemanticConfig | None = None,
    ) -> dict[str, Any]:
        semantic = config.semantic
        _validate_job_execution(semantic, execution_semantic)
        bounded = max(1, limit if limit is not None else semantic.max_jobs_per_run)
        requested_workers, workers = _worker_limits(semantic, execution_semantic, bounded)
        counts = _job_counts()
        root = Path(repository).expanduser().resolve()
        while counts["processed"] < bounded:
            wave = min(workers, bounded - counts["processed"])
            results = self._work_wave(
                repository_id,
                root,
                config,
                wave,
                _wave_execution(execution_semantic, requested_workers, wave),
            )
            if not results:
                break
            _count_job_results(counts, results)
        return {
            **counts,
            "semantic": self._reporting.status(repository_id, semantic),
        }

    def _work_wave(
        self,
        repository_id: int,
        root: Path,
        config: AnaxiGraphConfig,
        workers: int,
        execution_semantic: SemanticConfig | None,
    ) -> list[str]:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = executor.map(
                lambda _: self._work_one(
                    repository_id,
                    root,
                    config,
                    execution_semantic=execution_semantic,
                ),
                range(workers),
            )
        return [result for result in results if result is not None]

    def bootstrap(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        limit: int | None = None,
        force: bool = False,
        retry_failed: bool = False,
        plan_only: bool = False,
        execution_semantic: SemanticConfig | None = None,
        until_complete: bool = False,
        run_jobs: Callable[..., dict[str, Any]],
    ) -> dict[str, Any]:
        semantic = config.semantic
        if semantic.provider == "agent" and execution_semantic is None:
            plan_only = True
        if execution_semantic is not None and semantic.provider != "agent":
            raise ValueError("A local agent executor can only bridge semantic.provider=agent")
        remaining, total, stages = _bootstrap_state(limit, semantic, until_complete)
        for _ in _bootstrap_passes(until_complete, semantic):
            plan = self._planning.plan(
                repository_id,
                repository,
                config,
                force=force and not stages,
                retry_failed=retry_failed,
            )
            total["planned"] += plan.enqueued
            total.setdefault("work_plan", plan.work_plan())
            stages.append(plan.stage)
            if _stop_bootstrap(plan_only, plan, remaining):
                break
            run_limit = plan.active_jobs if remaining is None else min(remaining, plan.active_jobs)
            run = run_jobs(
                repository_id,
                repository,
                config,
                limit=run_limit,
                execution_semantic=execution_semantic,
            )
            _merge_run_counts(total, run)
            if remaining is not None:
                remaining -= int(run["processed"])
            if run["processed"] == 0:
                if until_complete:
                    time.sleep(2)
                    continue
                break
        return _bootstrap_result(total, stages, self._reporting.status(repository_id, semantic))

    def _work_one(
        self,
        repository_id: int,
        root: Path,
        config: AnaxiGraphConfig,
        *,
        execution_semantic: SemanticConfig | None = None,
    ) -> str | None:
        runtime_semantic = execution_semantic or config.semantic
        job = self._leases.claim_job(
            repository_id,
            config.semantic,
            executor_id=(f"cli:{runtime_semantic.provider}" if execution_semantic else None),
            executor_model=(runtime_semantic.model or None) if execution_semantic else None,
        )
        if job is None:
            return None
        try:
            with self._leases.job_lease(job, config.semantic):
                request = self._evidence.job_request(job, root, config.semantic)
                provider = create_semantic_provider(runtime_semantic)
                result = self.analyze_request(provider, request, runtime_semantic)
                recorded_provider = (
                    config.semantic.provider if execution_semantic else provider.name
                )
                self._persistence.complete_job(job, result, recorded_provider, config.semantic)
            return "completed"
        except SupersededSemanticJob as exc:
            self._persistence.mark_superseded(int(job["id"]), str(exc))
            return "superseded"
        except SemanticLeaseLost:
            return "lease_lost"
        except Exception as exc:
            return self._record_failure(job, exc)

    def _record_failure(self, job: dict[str, Any], exc: Exception) -> str:
        try:
            retry = self._persistence.fail_job(
                job,
                exc,
                input_tokens=max(0, int(getattr(exc, "input_tokens", 0))),
                output_tokens=max(0, int(getattr(exc, "output_tokens", 0))),
            )
        except SemanticLeaseLost:
            return "lease_lost"
        return "retry" if retry else "failed"

    def analyze_request(
        self,
        provider: Any,
        request: dict[str, Any],
        semantic: SemanticConfig,
    ) -> Any:
        """Compatibility shim for callers testing provider-side request reduction."""

        return analyze_semantic_request(provider, request, semantic)
