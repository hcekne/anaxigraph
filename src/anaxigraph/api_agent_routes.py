"""Finding lifecycle and bounded agent-analysis routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import anaxigraph.api_support as api_support
from anaxigraph.architecture_reassessment import architecture_reassessment

FRESH_EYES_START_OPERATION = "fresh_eyes_start"


def agent_router(context: Any) -> APIRouter:
    return AgentRoutes(context).router


class AgentRoutes:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.router = APIRouter()
        self.router.add_api_route("/api/findings", self.findings, methods=["GET"])
        self.router.add_api_route(
            "/api/findings/{finding_id}/status", self.finding_status, methods=["POST"]
        )
        self.router.add_api_route(
            "/api/findings/{finding_id}/context", self.finding_context, methods=["GET"]
        )
        self.router.add_api_route("/api/guidance", self.guidance, methods=["POST"])
        self.router.add_api_route("/api/impact", self.impact, methods=["POST"])
        self.router.add_api_route("/api/fresh-eyes", self.fresh_eyes, methods=["GET"])
        self.router.add_api_route("/api/fresh-eyes", self.start_fresh_eyes, methods=["POST"])
        self.router.add_api_route("/api/reassessment", self.reassessment, methods=["GET"])

    def findings(
        self,
        repository_id: int | None = None,
        view: str = Query(default="attention", pattern="^(attention|diagnostics)$"),
        cursor: str = Query(default="", max_length=2_000),
        page_size: int | None = Query(default=None, ge=1, le=200),
        status: list[str] = Query(default=[]),
        severity: list[str] = Query(default=[]),
        finding_type: list[str] = Query(default=[]),
        module: str = Query(default="", max_length=2_000),
        architecture_area: str = Query(default="", max_length=250),
        minimum_confidence: float = Query(default=0, ge=0, le=1),
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        try:
            return api_support.query_findings(
                self.context.database,
                int(row["id"]),
                self.context.selected_config(row),
                view=view,
                cursor=cursor,
                page_size=page_size,
                statuses=tuple(status),
                severities=tuple(severity),
                finding_types=tuple(finding_type),
                module=module,
                architecture_area=architecture_area,
                minimum_confidence=minimum_confidence,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def finding_status(
        self,
        finding_id: int,
        request: api_support.FindingStatusRequest,
        repository_id: int | None = None,
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        try:
            updated = self.context.database.update_finding_status(
                int(row["id"]), finding_id, request.status
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Finding not found")
        return {"id": finding_id, "status": request.status}

    def finding_context(
        self,
        finding_id: int,
        repository_id: int | None = None,
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        try:
            return api_support.finding_context(
                self.context.database,
                repository_id=int(row["id"]),
                finding_id=finding_id,
                config=self.context.selected_config(row),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def guidance(self, request: api_support.GuidanceRequest) -> dict[str, Any]:
        row = self.context.selected_repository(request.repository_id)
        try:
            return api_support.architecture_guidance(
                self.context.database,
                repository_id=int(row["id"]),
                goal=request.goal,
                config=self.context.selected_config(row),
                intent=request.intent,
                focus=request.focus,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def impact(self, request: api_support.ImpactRequest) -> dict[str, Any]:
        row = self.context.selected_repository(request.repository_id)
        try:
            return api_support.impact_analysis(
                self.context.database,
                repository_id=int(row["id"]),
                target=request.target,
                config=self.context.selected_config(row),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def fresh_eyes(
        self,
        repository_id: int | None = None,
        generation: int | None = Query(default=None, ge=1),
        compare_with: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        config = self.context.selected_config(row)
        try:
            return api_support.SemanticEngine(self.context.database).fresh_eyes_status(
                int(row["id"]), config.semantic, generation=generation, compare_with=compare_with
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def start_fresh_eyes(self, request: api_support.FreshEyesRequest) -> dict[str, Any]:
        """Record the request under the operation gate, off the event loop.

        ``wait=false`` returns once the ``requested`` transaction commits and leaves
        planning to the next executor claim that finds the queue otherwise empty.
        The gate holds for mutual exclusion but adds no cooldown: starting a review
        and then rerunning it are ordinary sequential operations, and the CLI does
        not retry a rate-limited request.
        """

        row = self.context.selected_repository(request.repository_id)
        repository_id = int(row["id"])
        config = self.context.selected_config(row)
        self.context.admit_operation(
            repository_id, FRESH_EYES_START_OPERATION, hold=True, cooldown_seconds=0
        )
        engine = api_support.SemanticEngine(self.context.database)
        try:
            if request.unpin:
                return await asyncio.to_thread(
                    engine.unpin_fresh_eyes_executors, repository_id, config.semantic
                )
            return await asyncio.to_thread(
                engine.start_fresh_eyes_review,
                repository_id,
                row["path"],
                config,
                proposal_count=request.proposal_count,
                proposal_executors=tuple(request.proposal_executors),
                retry_failed=request.retry_failed,
                restart=request.restart,
                plan=request.wait,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            self.context.finish_operation(repository_id, FRESH_EYES_START_OPERATION)

    def reassessment(
        self,
        repository_id: int | None = None,
        from_snapshot_id: int | None = Query(default=None, ge=1),
        goal: str = Query(default="", max_length=2_000),
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        try:
            return architecture_reassessment(
                self.context.database,
                repository_id=int(row["id"]),
                config=self.context.selected_config(row),
                from_snapshot_id=from_snapshot_id,
                goal=goal,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
