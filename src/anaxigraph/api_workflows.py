"""Repository workflow progress and explicit execution using the existing semantic queue."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from anaxigraph.api_semantic_routes import SemanticRoutes
from anaxigraph.persistence.workflow_read import workflow_coverage
from anaxigraph.semantic_pattern_plan import SemanticPatternPlanner
from anaxigraph.understanding import SemanticEngine


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


class WorkflowRoutes:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.router = APIRouter()
        self.router.add_api_route("/api/workflows", self.status, methods=["GET"])
        self.router.add_api_route("/api/workflows/run", self.run, methods=["POST"])

    def status(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        config = self.context.selected_config(row)
        snapshot = self.context.database.latest_snapshot(int(row["id"]))
        semantic = SemanticRoutes(self.context).status(int(row["id"]))
        fresh_eyes = SemanticEngine(self.context.database).fresh_eyes_status(
            int(row["id"]), config.semantic
        )
        coverage = {}
        if snapshot:
            with self.context.database.connect() as connection:
                coverage = workflow_coverage(connection, int(snapshot["id"]))
        result = {
            "repository_id": row["id"],
            "snapshot_id": snapshot["id"] if snapshot else None,
            "semantic": semantic,
            "fresh_eyes": fresh_eyes,
            "coverage": coverage,
            "scan": self.context.scan_coordinator.status_for(Path(row["path"])),
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

    def run(self, request: WorkflowRequest) -> dict[str, Any]:
        row = self.context.selected_repository(request.repository_id)
        target = self.context.target_for_path(Path(row["path"]))
        if target is None:
            raise HTTPException(403, "This repository is not mounted for analysis")
        config = self.context.selected_config(row)
        self._require_ready(row, config)
        execution = _execution(request, config.semantic)
        if request.workflow == "fresh-eyes" and config.semantic.provider != "agent":
            raise HTTPException(400, "Fresh eyes requires the repository's agent provider")
        self.context.admit_operation(
            int(row["id"]), "semantic_refresh", hold=False, cooldown_seconds=0
        )
        started = self.context.semantic_refresh.start(
            target,
            workflow=request.workflow,
            run=lambda: _run_workflow(self.context.database, row, config, execution, request),
        )
        return {"status": "started" if started else "already_running", "repository_id": row["id"]}

    def _require_ready(self, row: dict[str, Any], config: Any) -> None:
        if not config.semantic.enabled:
            raise HTTPException(400, "Enable AI mapping in this repository's service policy first")
        status = SemanticRoutes(self.context).status(int(row["id"]))
        if (status.get("map_status") or {}).get("state") != "current":
            raise HTTPException(409, "Refresh the source scan before starting this workflow")
        if self.context.scan_coordinator.status_for(Path(row["path"])).get("active"):
            raise HTTPException(409, "Wait for the source scan to finish")


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
