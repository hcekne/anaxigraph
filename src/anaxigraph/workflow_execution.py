"""Execute only the selected workflow steps through the durable semantic queue."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

from anaxigraph.persistence.workflow_read import workflow_coverage
from anaxigraph.semantic_fresh_eyes_plan import FreshEyesPlanner
from anaxigraph.semantic_pattern_plan import SemanticPatternPlanner
from anaxigraph.understanding import SemanticEngine
from anaxigraph.workflow_settings import FLOW_STEPS, STEP_MODES, WorkerChoice

JOB_STEPS = {
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
    stages = [stage for stage in fresh.get("stages", []) if stage["key"].startswith("proposal:")]
    if not stages:
        return
    if len(stages) != len(workers):
        raise ValueError(
            "The saved review has a different proposal count. Start a new review generation to change it."
        )
    for stage, worker in zip(stages, workers):
        pin = stage.get("required_executor")
        if pin and pin not in {"any", worker["provider"]}:
            raise ValueError(
                "The saved review pins this proposal to another provider. Restore its settings or start a new review generation."
            )


class WorkflowExecution:
    def __init__(self, database: Any, row: Any, config: Any, request: Any, settings: Any) -> None:
        self.database, self.row, self.request = database, row, request
        self.engine = SemanticEngine(database)
        self.config = (
            config
            if request.workflow == "mapping"
            else replace(config, semantic=replace(config.semantic, detailed_reviews=True))
        )
        self.repository_id = int(row["id"])
        self.snapshot_id = int(database.latest_snapshot(self.repository_id)["id"])
        self.steps = (request.step,) if request.step else FLOW_STEPS[request.workflow]
        self.settings = settings
        self.processed = 0

    def run(self) -> dict[str, Any]:
        if self.request.workflow == "fresh-eyes":
            self._start_review()
        while True:
            if self.database.latest_snapshot(self.repository_id)["id"] != self.snapshot_id:
                return self._result(False, "The source scan changed. Resume on the new scan.")
            if self.request.max_jobs and self.processed >= self.request.max_jobs:
                return self._result(
                    False, "The requested job limit was reached; resume to continue."
                )
            self._plan()
            jobs = self._jobs()
            if not jobs:
                return self._finish()
            results = self._dispatch(jobs)
            count = sum(result["processed"] for result in results)
            self.processed += count
            if not count or any(result["failed"] or result["retry"] for result in results):
                return self._result(
                    False, "Work is waiting. Check saved errors, limits and prerequisites."
                )

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
        retry = self.request.retry_failed and self.processed == 0
        if self.request.workflow == "mapping":
            self.engine.plan(
                self.repository_id,
                self.row["path"],
                self.config,
                retry_failed=retry,
                preserve_patterns=True,
            )
            return
        with self.database.transaction() as connection:
            arguments = dict(
                repository_id=self.repository_id,
                snapshot_id=self.snapshot_id,
                semantic=self.config.semantic,
                retry_failed=retry,
            )
            if self.request.workflow == "patterns":
                SemanticPatternPlanner().plan_patterns(connection, **arguments)
            else:
                FreshEyesPlanner().plan_active(connection, **arguments)

    def _jobs(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM semantic_jobs WHERE repository_id = ? AND snapshot_id = ?
                AND status IN ('pending', 'retry') ORDER BY priority DESC, id""",
                (self.repository_id, self.snapshot_id),
            ).fetchall()
        return [dict(row) for row in rows if job_step(row) in self.steps]

    def _dispatch(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Run the earliest eligible card. Distinct model pools share file jobs, never duplicate them.
        step = next(step for step in self.steps if any(job_step(job) == step for job in jobs))
        selected = [job for job in jobs if job_step(job) == step]
        remaining = (
            self.request.max_jobs - self.processed if self.request.max_jobs else len(selected)
        )
        selected = selected[: min(remaining, self.config.semantic.max_jobs_per_run)]
        pools = [WorkerChoice(**item) for item in self.settings[step]]
        assignments = assign_jobs(step, selected, pools)
        cap = min(len(pools), self.config.semantic.max_parallel_jobs)
        with ThreadPoolExecutor(max_workers=cap) as executor:
            futures = [
                executor.submit(self._run_pool, pool, identifiers)
                for pool, identifiers in zip(pools, assignments)
                if identifiers
            ]
            return [future.result() for future in futures]

    def _run_pool(self, pool: WorkerChoice, identifiers: list[int]) -> dict[str, Any]:
        execution = replace(
            self.config.semantic,
            provider=pool.provider,
            model=pool.model,
            reasoning_effort=pool.reasoning_effort,
            max_parallel_jobs=pool.workers,
            stage_models={},
        )
        return self.engine.run_jobs(
            self.repository_id,
            self.row["path"],
            self.config,
            limit=len(identifiers),
            execution_semantic=execution,
            job_ids=tuple(identifiers),
        )

    def _finish(self) -> dict[str, Any]:
        status = self.engine.status(self.repository_id, self.config.semantic)
        with self.database.connect() as connection:
            coverage = workflow_coverage(connection, self.snapshot_id)
        fresh = self.engine.fresh_eyes_status(self.repository_id, self.config.semantic)
        completed = completed_steps(status, coverage, fresh)
        ready = all(step in completed for step in self.steps)
        message = (
            "Selected work is complete."
            if ready
            else ("No eligible jobs for this step yet. Complete its preceding cards, then resume.")
        )
        return self._result(ready, message)

    def _result(self, complete: bool, message: str) -> dict[str, Any]:
        return {
            "status": "complete" if complete else "waiting",
            "processed": self.processed,
            "step": self.request.step,
            "snapshot_id": self.snapshot_id,
            "message": message,
            "settings": {step: self.settings[step] for step in self.steps if step in self.settings},
        }


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


def completed_steps(status: Any, coverage: Any, fresh: Any) -> set[str]:
    scopes = coverage.get("scopes", {})
    modules, groups = scopes.get("module", {}), scopes.get("group", {})
    total = modules.get("total", 0) - modules.get("excluded", 0)
    taxonomy = status.get("taxonomy", {})
    current = taxonomy.get("current") or {}
    patterns = status.get("patterns", {})
    pattern = scopes.get("pattern", {})
    checks = {
        "intrinsic": bool(modules) and modules.get("intrinsic", 0) == total,
        "context": bool(modules) and modules.get("current", 0) == total,
        "taxonomy_proposal": bool(current) or not taxonomy.get("enabled"),
        "taxonomy_review": taxonomy.get("ready") or not taxonomy.get("enabled"),
        "groups": bool(groups) and groups.get("current", 0) == groups.get("total", 0),
        "charter": (status.get("architecture_charter") or {}).get("status") == "current",
        "pattern_plan": patterns.get("planned"),
        "pattern_assessment": patterns.get("planned")
        and max(pattern.get("current", 0), pattern.get("intrinsic", 0)) == patterns.get("selected"),
        "pattern_review": patterns.get("planned")
        and pattern.get("current", 0) == patterns.get("selected"),
        "brief": bool(fresh.get("capability_brief")),
        "grounding": fresh.get("ready"),
    }
    stages = fresh.get("stages", [])
    for step, key in (
        ("proposals", "proposal:"),
        ("adjudication", "adjudication"),
        ("comparison", "comparison"),
        ("mission_filter", "review"),
    ):
        matching = [stage for stage in stages if stage["key"].startswith(key)]
        checks[step] = bool(matching) and all(stage["state"] == "current" for stage in matching)
    return {step for step, ready in checks.items() if ready}
