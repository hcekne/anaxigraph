"""Repository workflow progress and explicit execution using the existing semantic queue."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from anaxigraph.api_semantic_routes import SemanticRoutes
from anaxigraph.operational_health import served_map_status
from anaxigraph.persistence.workflow_read import workflow_coverage
from anaxigraph.semantic_pattern_plan import SemanticPatternPlanner
from anaxigraph.understanding import SemanticEngine
from anaxigraph.workflow_execution import WorkflowExecution, validate_proposal_settings
from anaxigraph.workflow_settings import (
    FLOW_STEPS,
    SOFTWARE_STEPS,
    StepSettingsRequest,
    WorkerChoice,
    WorkflowSettings,
    required_steps,
    validate_step,
)


class WorkflowRequest(BaseModel):
    repository_id: int | None = None
    workflow: Literal["mapping", "patterns", "fresh-eyes"]
    executor: Literal["configured", "codex", "claude"] = "configured"
    model: str = Field(default="", max_length=200)
    reasoning_effort: str = Field(default="", max_length=40)
    parallel_jobs: int = Field(default=2, ge=1, le=64)
    proposal_count: int = Field(default=2, ge=1, le=3)
    goal: str | None = Field(default=None, max_length=4_000)
    retry_failed: bool = True
    restart: bool = False
    use_step_settings: bool = False
    step: str | None = Field(default=None, max_length=60)
    max_jobs: int | None = Field(default=None, ge=1, le=10_000)


class WorkflowRoutes:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.settings = WorkflowSettings(context.database.path)
        self.router = APIRouter()
        self.router.add_api_route("/api/workflows", self.status, methods=["GET"])
        self.router.add_api_route("/api/workflows/run", self.run, methods=["POST"])
        self.router.add_api_route("/api/workflows/settings", self.save_settings, methods=["PUT"])

    def status(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        config = self.context.selected_config(row)
        snapshot = self.context.database.latest_snapshot(int(row["id"]))
        result = {
            "repository_id": row["id"],
            "snapshot_id": snapshot["id"] if snapshot else None,
            **self._read_progress(row, config, snapshot),
            "scan": self.context.scan_coordinator.status_for(Path(row["path"])),
            "settings": self.settings.read(
                int(row["id"]),
                config.semantic.max_parallel_jobs,
                config.semantic.taxonomy.review_passes,
            ),
            "execution": {
                "mounted": self.context.target_for_path(Path(row["path"])) is not None,
                "local_executors": [name for name in ("codex", "claude") if shutil.which(name)],
                "configured_provider": config.semantic.provider,
                "max_parallel_jobs": config.semantic.max_parallel_jobs,
            },
        }
        latest = self.context.database.latest_snapshot(int(row["id"]))
        if result["snapshot_id"] != (latest["id"] if latest else None):
            raise HTTPException(
                409, "The source scan changed while reading progress. Refresh to continue."
            )
        return result

    def _read_progress(self, row: Any, config: Any, snapshot: Any) -> dict[str, Any]:
        """Re-read across a run transition so completion cannot precede its saved counts."""
        for _ in range(2):
            worker = self.context.semantic_refresh.status_for(Path(row["path"]))
            semantic = SemanticRoutes(self.context).status(int(row["id"]))
            fresh = SemanticEngine(self.context.database).fresh_eyes_status(
                int(row["id"]), config.semantic
            )
            with self.context.database.connect() as connection:
                coverage = workflow_coverage(connection, int(snapshot["id"])) if snapshot else {}
            semantic["worker"] = worker
            if worker == self.context.semantic_refresh.status_for(Path(row["path"])):
                break
        return {"semantic": semantic, "fresh_eyes": fresh, "coverage": coverage}

    def run(self, request: WorkflowRequest) -> dict[str, Any]:
        row = self.context.selected_repository(request.repository_id)
        target = self.context.target_for_path(Path(row["path"]))
        if target is None:
            raise HTTPException(403, "This repository is not mounted for analysis")
        config = self.context.selected_config(row)
        self._require_ready(row, config)
        execution = (
            self._step_execution(request, row, config)
            if request.use_step_settings
            else (_execution(request, config.semantic))
        )
        if request.step and not request.use_step_settings:
            raise HTTPException(400, "Single steps require their saved step settings")
        if request.workflow == "fresh-eyes" and config.semantic.provider != "agent":
            raise HTTPException(400, "Fresh eyes requires the repository's agent provider")
        self.context.admit_operation(
            int(row["id"]), "semantic_refresh", hold=False, cooldown_seconds=0
        )
        started = self.context.semantic_refresh.start(
            target,
            workflow=request.workflow,
            step=request.step,
            settings=execution if request.use_step_settings else None,
            run=lambda: (
                self._run_steps(row, config, request, execution)
                if request.use_step_settings
                else _run_workflow(self.context.database, row, config, execution, request)
            ),
        )
        return {"status": "started" if started else "already_running", "repository_id": row["id"]}

    def _run_steps(self, row: Any, config: Any, request: Any, execution: Any) -> dict[str, Any]:
        return WorkflowExecution(
            self.context.database,
            row,
            config,
            request,
            execution,
            step_lock=lambda step: self.context.semantic_refresh.step_lock(Path(row["path"]), step),
            on_progress=lambda **fields: self.context.semantic_refresh.update_run(
                Path(row["path"]), request.workflow, request.step, **fields
            ),
            on_pool_error=lambda error: self.context.semantic_refresh.report_pool_error(
                Path(row["path"]), error, request.workflow, request.step
            ),
        ).run()

    def save_settings(self, request: StepSettingsRequest) -> dict[str, Any]:
        row = self.context.selected_repository(request.repository_id)
        if self.context.target_for_path(Path(row["path"])) is None:
            raise HTTPException(403, "This repository is not mounted for analysis")
        config = self.context.selected_config(row)
        try:
            if request.step == "taxonomy_review" and len(request.workers) > max(
                1, config.semantic.taxonomy.review_passes
            ):
                raise ValueError("There are more model rows than configured review passes")
            settings = self.settings.save(
                int(row["id"]),
                request,
                config.semantic.max_parallel_jobs,
                config.semantic.taxonomy.review_passes,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"repository_id": row["id"], "settings": settings}

    def _step_execution(self, request: WorkflowRequest, row: Any, config: Any) -> Any:
        if config.semantic.provider != "agent":
            raise HTTPException(400, "Per-step CLI workers require the repository's agent provider")
        allowed = (*FLOW_STEPS[request.workflow], *SOFTWARE_STEPS.get(request.workflow, ()))
        if request.step is not None and request.step not in allowed:
            raise HTTPException(400, "This step does not belong to the selected workflow")
        settings = self.settings.read(
            int(row["id"]),
            config.semantic.max_parallel_jobs,
            config.semantic.taxonomy.review_passes,
        )["steps"]
        steps = required_steps(request.workflow, request.step)
        try:
            if request.workflow == "fresh-eyes" and not request.restart:
                validate_proposal_settings(
                    SemanticEngine(self.context.database).fresh_eyes_status(
                        int(row["id"]), config.semantic
                    ),
                    settings["proposals"],
                )
            _validate_workers(settings, steps, config.semantic.max_parallel_jobs)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return settings

    def _require_ready(self, row: dict[str, Any], config: Any) -> None:
        if not config.semantic.enabled:
            raise HTTPException(400, "Enable AI mapping in this repository's service policy first")
        snapshot = self.context.database.latest_snapshot(int(row["id"]))
        if not snapshot or served_map_status(Path(row["path"]), snapshot)["state"] != "current":
            raise HTTPException(409, "Refresh the source scan before starting this workflow")
        if self.context.scan_coordinator.status_for(Path(row["path"])).get("active"):
            raise HTTPException(409, "Wait for the source scan to finish")


def _validate_workers(settings: Any, steps: Any, ceiling: int) -> None:
    for step in steps:
        if step not in settings:
            continue
        workers = [WorkerChoice(**item) for item in settings[step]]
        validate_step(step, workers, ceiling)
        for worker in workers:
            if not shutil.which(worker.provider):
                raise ValueError(f"{worker.provider} is not installed on this server")


def _execution(request: WorkflowRequest, semantic: Any) -> Any:
    if semantic.provider != "agent":
        if request.executor != "configured":
            raise HTTPException(400, "This repository uses its configured provider")
        return None
    if request.executor == "configured" or not shutil.which(request.executor):
        raise HTTPException(400, "Select an installed Codex or Claude executor on this server")
    if not request.model.strip():
        raise HTTPException(400, "Choose a worker model before starting model calls")
    return replace(
        semantic,
        provider=request.executor,
        model=request.model.strip(),
        reasoning_effort=request.reasoning_effort.strip(),
        max_parallel_jobs=min(request.parallel_jobs, semantic.max_parallel_jobs),
    )


def _run_workflow(
    database: Any, row: dict[str, Any], config: Any, execution: Any, request: WorkflowRequest
) -> dict[str, Any]:
    engine = SemanticEngine(database)
    repository_id = int(row["id"])
    if request.workflow == "fresh-eyes":
        engine.start_fresh_eyes_review(
            repository_id,
            row["path"],
            config,
            proposal_count=request.proposal_count,
            goal=request.goal,
            restart=request.restart,
            plan=False,
        )
    processed = 0
    while True:
        result = engine.bootstrap(
            repository_id,
            row["path"],
            config,
            execution_semantic=execution,
            retry_failed=request.retry_failed and processed == 0,
        )
        processed += result["processed"]
        if result["processed"] == 0 or result["failed"] or result["semantic"]["budget"]["paused"]:
            break
    remaining = sum(
        result["semantic"].get(key, 0)
        for key in ("pending", "failed", "pending_scopes", "failed_scopes")
    )
    if request.workflow == "fresh-eyes":
        remaining += not engine.fresh_eyes_status(repository_id, config.semantic)["ready"]
    if request.workflow == "patterns" and not remaining:
        return _run_patterns(database, engine, row, config, execution, request.retry_failed)
    return {
        "status": "waiting" if remaining else "complete",
        "processed": processed,
        "detailed_reviews": config.semantic.detailed_reviews,
        "paused": result["semantic"]["budget"]["paused"],
        "snapshot_id": result["semantic"].get("snapshot_id"),
    }


def _run_patterns(
    database: Any, engine: Any, row: dict[str, Any], config: Any, execution: Any, retry_failed: bool
) -> dict[str, Any]:
    """Run the optional pattern stage against the saved map without changing file contracts."""
    config = replace(config, semantic=replace(config.semantic, detailed_reviews=True))
    repository_id = int(row["id"])
    snapshot_id = int(database.latest_snapshot(repository_id)["id"])
    processed = 0
    while True:
        if database.latest_snapshot(repository_id)["id"] != snapshot_id:
            return {
                "status": "waiting",
                "error": "The source scan changed. Resume pattern analysis.",
            }
        with database.transaction() as connection:
            _created, ready = SemanticPatternPlanner().plan_patterns(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                semantic=config.semantic,
                retry_failed=retry_failed and processed == 0,
            )
        if ready:
            return {"status": "complete", "snapshot_id": snapshot_id, "processed": processed}
        result = engine.run_jobs(repository_id, row["path"], config, execution_semantic=execution)
        processed += result["processed"]
        if not result["processed"] or result["failed"]:
            return {
                "status": "waiting",
                "snapshot_id": snapshot_id,
                "processed": processed,
                "paused": result["semantic"]["budget"]["paused"],
            }
