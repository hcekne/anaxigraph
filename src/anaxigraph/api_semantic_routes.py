"""Semantic status and refresh routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

import anaxigraph.api_support as api_support


def semantic_router(context: Any) -> APIRouter:
    return SemanticRoutes(context).router


class SemanticRoutes:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.router = APIRouter()
        self.router.add_api_route("/api/semantic", self.status, methods=["GET"])
        self.router.add_api_route("/api/semantic/refresh", self.refresh, methods=["POST"])

    def status(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        result = api_support.SemanticEngine(self.context.database).status(
            int(row["id"]), self.context.selected_config(row).semantic
        )
        result["worker"] = self.context.semantic_refresh.status_for(Path(row["path"]))
        return result

    def refresh(
        self,
        repository_id: int | None = None,
        force: bool = False,
        retry_failed: bool = False,
        wait: bool = False,
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        target = self.context.target_for_path(Path(row["path"]))
        if target is None:
            raise HTTPException(
                status_code=403,
                detail="This indexed repository is not mounted as a semantic-analysis target",
            )
        config = self.context.selected_config(row)
        if not config.semantic.enabled:
            raise HTTPException(
                status_code=400,
                detail="Semantic analysis is disabled in this repository's .anaxigraph.yml",
            )
        self.context.admit_operation(int(row["id"]), "semantic_refresh", hold=wait)
        if wait:
            try:
                return self._prepare(target, config, force, retry_failed)
            finally:
                self.context.finish_operation(int(row["id"]), "semantic_refresh")
        started = self.context.semantic_refresh.start(
            target, force=force, retry_failed=retry_failed
        )
        return {
            "status": "started" if started else "already_running",
            "repository_id": row["id"],
        }

    def _prepare(
        self,
        target: Any,
        config: Any,
        force: bool,
        retry_failed: bool,
    ) -> dict[str, Any]:
        stats = api_support.RepositoryScanner(self.context.database).scan(
            target.path,
            config_path=target.config_path,
            run_type="semantic_reconcile",
        )
        result = api_support.SemanticEngine(self.context.database).bootstrap(
            stats.repository_id,
            target.path,
            config,
            force=force,
            retry_failed=retry_failed,
            plan_only=True,
        )
        return {"status": "prepared", "scan": stats.as_dict(), **result}
