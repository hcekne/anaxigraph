"""Finding lifecycle and bounded agent-analysis routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

import anaxigraph.api_support as api_support


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
        self.router.add_api_route("/api/agent-scope", self.scope, methods=["POST"])
        self.router.add_api_route("/api/impact", self.impact, methods=["POST"])

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

    def scope(self, request: api_support.ScopeRequest) -> dict[str, Any]:
        row = self.context.selected_repository(request.repository_id)
        try:
            return api_support.agent_scope(
                self.context.database,
                repository_id=int(row["id"]),
                goal=request.goal,
                config=self.context.selected_config(row),
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
