"""Execute only the selected workflow steps through the durable semantic queue."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from threading import Event, Lock
from typing import Any

from anaxigraph.architecture_plan import plan_requested, request_plan
from anaxigraph.persistence.workflow_read import workflow_coverage
from anaxigraph.semantic_fresh_eyes_plan import FreshEyesPlanner
from anaxigraph.semantic_pattern_plan import SemanticPatternPlanner
from anaxigraph.semantic_timeouts import worker_lease_seconds
from anaxigraph.understanding import SemanticEngine
from anaxigraph.workflow_progress import completed_steps as completed_steps
from anaxigraph.workflow_settings import FLOW_STEPS, STEP_MODES, WorkerChoice, required_steps

JOB_STEPS = {
    "annotation": "annotation",
    "architecture_plan": "architecture_plan",
    "intrinsic": "intrinsic",
    "context": "context",
    "taxonomy_proposal": "taxonomy_proposal",
    "taxonomy_review": "taxonomy_review",
    "pattern_assessment": "pattern_assessment",
    "pattern_review": "pattern_review",
    "fresh_proposal": "proposals",
    "fresh_adjudication": "adjudication",
    "fresh_comparison": "comparison",
    "fresh_review": "mission_filter",
}


def job_step(job: dict[str, Any]) -> str:
    if job["job_kind"] == "synthesis":
        return "charter" if job["scope_type"] == "repository" else "groups"
    return JOB_STEPS.get(job["job_kind"], "")


def validate_proposal_settings(fresh: Any, workers: Any) -> None:
    stages = [
        stage
        for stage in fresh.get("stages", [])
        if ":proposal:" in stage["key"] or stage["key"].startswith("proposal:")
    ]
    if not stages:
        return
    slots = sorted({stage["key"].rsplit(":", 1)[1] for stage in stages})
    if len(slots) != len(workers):
        raise ValueError(
            "The saved review has a different proposal count. Start a new review generation to change it."
        )
    for stage in stages:
        worker = workers[slots.index(stage["key"].rsplit(":", 1)[1])]
        pin = stage.get("required_executor")
        if pin and pin not in {"any", worker["provider"]}:
            raise ValueError(
                "The saved review pins this proposal to another provider. Restore its settings or start a new review generation."
            )


class WorkflowExecution:
    def __init__(
        self,
        database: Any,
        row: Any,
        config: Any,
        request: Any,
        settings: Any,
        *,
        on_step: Callable[[str], None] | None = None,
        on_pool_error: Callable[[dict[str, Any]], None] | None = None,
        on_progress: Callable[..., None] | None = None,
        step_lock: Callable[[str], Any] | None = None,
    ) -> None:
        self.database, self.row, self.request = database, row, request
        self.engine = SemanticEngine(database)
        self.base_config = config
        self.mapping_config = replace(
            config, semantic=replace(config.semantic, detailed_reviews=False)
        )
        self.config = (
            config
            if request.workflow in {"mapping", "architecture"}
            else replace(config, semantic=replace(config.semantic, detailed_reviews=True))
        )
        self.repository_id = int(row["id"])
        self.snapshot_id = int(database.latest_snapshot(self.repository_id)["id"])
        self.steps = required_steps(request.workflow, request.step)
        self.settings = settings
        self.processed = 0
        self.on_step = on_step
        self.on_pool_error = on_pool_error
        self.pool_errors: list[dict[str, Any]] = []
        self.error_lock = Lock()
        self.retry_prepared = False
        self.joined_workers = False
        self.review_started = False
        self.on_progress = on_progress
        self.active_step = None
        self.step_lock = step_lock
        self.joined_step = False

    def run(self) -> dict[str, Any]:
        self._plan()
        while True:
            if self.database.latest_snapshot(self.repository_id)["id"] != self.snapshot_id:
                return self._result(False, "The source scan changed. Resume on the new scan.")
            if self.request.max_jobs and self.processed >= self.request.max_jobs:
                return self._result(
                    False, "The requested job limit was reached; resume to continue."
                )
            jobs = self._jobs()
            if not jobs:
                if self._wait_for_workers(selected_only=True):
                    continue
                return self._finish()
            if self._wait_for_retry(jobs):
                continue
            results = self._dispatch(jobs)
            count = sum(result["processed"] for result in results)
            self.processed += count
            result = self._after_dispatch(count)
            if result is not None:
                return result

    def _after_dispatch(self, count: int) -> dict[str, Any] | None:
        if self.joined_step:
            self.joined_step = False
            time.sleep(0.1)
            return None
        if not count:
            if not self.pool_errors and self._wait_for_workers(selected_only=False):
                return None
            return self._result(False, self._waiting_message())
        if not self._jobs() and not self._wait_for_workers(selected_only=True):
            if self.active_step == self.request.step and self.request.step in {
                "annotation",
                "intrinsic",
                "context",
                "groups",
            }:
                return self._finish()
            self._plan()
        return None

    def _start_review(self) -> None:
        workers = self.settings["proposals"]
        self.engine.start_fresh_eyes_review(
            self.repository_id,
            self.row["path"],
            self.config,
            proposal_count=len(workers),
            proposal_executors=tuple(worker["provider"] for worker in workers),
            goal=self.request.goal,
            restart=self.request.restart,
            plan=False,
        )

    def _plan(self) -> None:
        self._progress("preparing", "Checking saved results and preparing pending jobs.")
        retry = self.request.retry_failed and not self.retry_prepared
        self.retry_prepared = True
        if self.request.workflow == "mapping" or not self._mapping_ready():
            self.engine.plan(
                self.repository_id,
                self.row["path"],
                self.mapping_config,
                retry_failed=retry,
                preserve_patterns=True,
            )
            if self.request.workflow == "mapping" or not self._mapping_ready():
                return
        if self.request.workflow == "fresh-eyes" and not self.review_started:
            self._start_review()
            self.review_started = True
        with self.database.transaction() as connection:
            arguments = dict(
                repository_id=self.repository_id,
                snapshot_id=self.snapshot_id,
                semantic=self.config.semantic,
                retry_failed=retry,
            )
            if self.request.workflow == "patterns":
                SemanticPatternPlanner().plan_patterns(connection, **arguments)
            elif self.request.workflow == "architecture":
                if not self.review_started:
                    request_plan(
                        connection, self.repository_id, self.snapshot_id, self.request.goal
                    )
                    self.review_started = True
                plan_requested(connection, **arguments)
            else:
                FreshEyesPlanner().plan_active(connection, **arguments)

    def _mapping_ready(self) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT status FROM semantic_scope_states
                WHERE snapshot_id = ? AND scope_type = 'repository'""",
                (self.snapshot_id,),
            ).fetchone()
        return row is not None and row["status"] == "current"

    def _progress(self, phase: str, message: str, step: str | None = None) -> None:
        self.active_step = step
        if step and self.on_step:
            self.on_step(step)
        if self.on_progress:
            self.on_progress(phase=phase, message=message, active_step=step)

    def _jobs(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM semantic_jobs WHERE repository_id = ? AND snapshot_id = ?
                AND status IN ('pending', 'retry') ORDER BY priority DESC, id""",
                (self.repository_id, self.snapshot_id),
            ).fetchall()
        return [dict(row) for row in rows if job_step(row) in self.steps]

    def _wait_for_workers(self, *, selected_only: bool) -> bool:
        """Join existing work and wait for shared slots instead of ending a requested run."""
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM semantic_jobs WHERE repository_id = ? AND snapshot_id = ?
                AND status = 'running'""",
                (self.repository_id, self.snapshot_id),
            ).fetchall()
        running = [row for row in rows if not selected_only or job_step(row) in self.steps]
        if not running:
            if self.joined_workers:
                self.joined_workers = False
                self._plan()
                return True
            return False
        fallback = timedelta(seconds=worker_lease_seconds(self.config.semantic.timeout_seconds))
        expired = any(
            (
                datetime.fromisoformat(row["lease_expires_at"])
                if row["lease_expires_at"]
                else datetime.fromisoformat(row["started_at"]) + fallback
            )
            <= datetime.now(UTC)
            for row in running
        )
        if expired:
            self.engine.plan(
                self.repository_id, self.row["path"], self.mapping_config, preserve_patterns=True
            )
            return True
        self.joined_workers = True
        self._progress(
            "waiting_workers",
            "Waiting for shared workers to finish.",
            job_step(running[0]) if selected_only else None,
        )
        time.sleep(1)
        return True

    def _dispatch(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Share one pool per card across overlapping requests, while other ready cards advance.
        for step in self.steps:
            if not any(job_step(job) == step for job in jobs):
                continue
            lock = self.step_lock(step) if self.step_lock else Lock()
            if not lock.acquire(blocking=False):
                self.joined_workers = True
                continue
            try:
                return self._dispatch_step(step, jobs)
            finally:
                lock.release()
        self.joined_step = True
        self._progress("waiting_workers", "Another request is processing these prerequisites.")
        return []

    def _dispatch_step(self, step: str, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._progress("executing", "Processing pending jobs.", step)
        selected = [job for job in jobs if job_step(job) == step]
        remaining = (
            self.request.max_jobs - self.processed if self.request.max_jobs else len(selected)
        )
        # This explicit workflow run already has its own optional limit. Chunking it by
        # max_jobs_per_run would reintroduce a slowest-worker barrier between chunks.
        selected = selected[:remaining]
        assignments = self._assignments(step, selected)
        cap = max(1, min(len(assignments), self.config.semantic.max_parallel_jobs))
        with ThreadPoolExecutor(max_workers=cap) as executor:
            futures = [
                executor.submit(self._run_pool, step, pool, identifiers)
                for pool, identifiers in assignments
                if identifiers
            ]
            return [future.result() for future in futures]

    def _assignments(self, step: str, jobs: list[dict[str, Any]]) -> Any:
        pools = [WorkerChoice(**item) for item in self.settings[step]]
        disabled = {(error["provider"], error["model"]) for error in self.pool_errors}
        if STEP_MODES[step] == "parallel":
            pools = [pool for pool in pools if (pool.provider, pool.model) not in disabled]
            if not pools:
                return []
            if not self.request.max_jobs:
                # Atomic leases prevent duplicates. A fast or surviving model can
                # drain the whole card instead of stranding another pool's partition.
                return [(pool, [int(job["id"]) for job in jobs]) for pool in pools]
        return [
            (pool, identifiers)
            for pool, identifiers in zip(pools, assign_jobs(step, jobs, pools))
            if (pool.provider, pool.model) not in disabled
        ]

    def _wait_for_retry(self, jobs: list[dict[str, Any]]) -> bool:
        step = next(step for step in self.steps if any(job_step(job) == step for job in jobs))
        selected = [job for job in jobs if job_step(job) == step]
        eligible = {
            identifier for _, ids in self._assignments(step, selected) for identifier in ids
        }
        deadlines = [
            datetime.fromisoformat(job["available_at"]) for job in selected if job["id"] in eligible
        ]
        delay = (min(deadlines) - datetime.now(UTC)).total_seconds() if deadlines else 0
        if delay > 0:
            self._progress("waiting_retry", "Waiting for the scheduled retry.", step)
            time.sleep(min(delay, 1))
            return True
        return False

    def _run_pool(self, step: str, pool: WorkerChoice, identifiers: list[int]) -> dict[str, Any]:
        config = self.base_config if step in FLOW_STEPS["mapping"] else self.config
        execution = replace(
            config.semantic,
            provider=pool.provider,
            model=pool.model,
            reasoning_effort=pool.reasoning_effort,
            max_parallel_jobs=pool.workers,
            stage_models={},
        )
        stop = Event()
        try:
            return self.engine.run_jobs(
                self.repository_id,
                self.row["path"],
                config,
                limit=len(identifiers),
                execution_semantic=execution,
                job_ids=tuple(identifiers),
                stop_on_failure=stop,
                on_error=partial(self._pool_error, step, pool, stop),
                include_status=False,
            )
        except Exception as exc:
            if not executor_unavailable(exc):
                raise
            self._pool_error(step, pool, stop, exc)
            return {"processed": 0}

    def _pool_error(self, step: str, pool: WorkerChoice, stop: Event, exc: Exception) -> None:
        if not executor_unavailable(exc):
            return
        stop.set()
        error = dict(step=step, provider=pool.provider, model=pool.model, error=str(exc)[:1000])
        with self.error_lock:
            if any(
                item["provider"] == pool.provider and item["model"] == pool.model
                for item in self.pool_errors
            ):
                return
            self.pool_errors.append(error)
        if self.on_pool_error:
            self.on_pool_error(error)

    def _waiting_message(self) -> str:
        if self.pool_errors:
            error = self.pool_errors[0]
            return f"{error['provider']} / {error['model']}: {error['error']}. Update this card's settings and resume."
        status = self.engine.status(self.repository_id, self.config.semantic)
        if status.get("budget", {}).get("paused"):
            return (
                "The repository usage limit is paused. Saved work is kept; resume when available."
            )
        return "No worker could claim the remaining jobs. Check usage limits and active workers."

    def _finish(self) -> dict[str, Any]:
        self._progress("finishing", "Results saved. Checking completion.")
        if self.database.latest_snapshot(self.repository_id)["id"] != self.snapshot_id:
            return self._result(False, "The source scan changed. Resume on the new scan.")
        status = (
            {}
            if self.request.step in {"annotation", "intrinsic", "context"}
            else self.engine.status(self.repository_id, self.config.semantic)
        )
        with self.database.connect() as connection:
            coverage = workflow_coverage(connection, self.snapshot_id)
        fresh = (
            self.engine.fresh_eyes_status(self.repository_id, self.config.semantic)
            if self.request.workflow == "fresh-eyes"
            else {}
        )
        completed = completed_steps(status, coverage, fresh)
        ready = all(step in completed for step in self.steps)
        failures = [
            error for error in coverage.get("failures", []) if job_step(error) in self.steps
        ]
        message = (
            "Selected work is complete."
            if ready
            else (
                "A prerequisite could not complete. Saved results are kept; resume after resolving its reported issue."
            )
        )
        if not ready and failures:
            message = f"Some files could not finish after their retries: {failures[0]['error']}"
        return self._result(ready, message)

    def _result(self, complete: bool, message: str) -> dict[str, Any]:
        return {
            "status": "complete" if complete else "waiting",
            "processed": self.processed,
            "step": self.request.step,
            "snapshot_id": self.snapshot_id,
            "message": message,
            "pool_errors": self.pool_errors,
            "settings": {step: self.settings[step] for step in self.steps if step in self.settings},
        }


def executor_unavailable(error: Exception) -> bool:
    """Only executor-wide failures stop a pool; file and transient errors keep draining."""
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "unrecognized_model",
            "model_not_found",
            "invalid model",
            "unknown model",
            "model is unavailable",
            "selected model is unavailable",
            "model does not exist",
            "may not exist or you may not have access",
            "not supported when using codex",
            "authentication_error",
            "invalid_api_key",
            "invalid api key",
            "not logged in",
            "cannot authenticate",
            "please log in",
            "please run /login",
        )
    )


def assign_jobs(
    step: str, jobs: list[dict[str, Any]], pools: list[WorkerChoice]
) -> list[list[int]]:
    assignments: list[list[int]] = [[] for _ in pools]
    slots = [index for index, pool in enumerate(pools) for _ in range(pool.workers)]
    for index, job in enumerate(jobs):
        metadata = json.loads(job["metadata_json"] or "{}")
        if STEP_MODES[step] == "sequence":
            slot = (int(metadata.get("review_pass", 1)) - 1) % len(pools)
        elif step == "proposals":
            slot = ord(job["scope_key"].rsplit(":", 1)[-1]) - ord("a")
            if slot >= len(pools):
                raise ValueError(
                    "This review has more proposal slots. Restore its settings or start a new generation."
                )
            pin = metadata.get("required_executor")
            if pin and pin not in {"any", pools[slot].provider}:
                raise ValueError(
                    "A saved proposal is pinned to another provider. Restore its settings or start a new generation."
                )
        else:
            slot = slots[index % len(slots)]
        assignments[slot].append(int(job["id"]))
    return assignments
