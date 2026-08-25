"""Semantic status and refresh routes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

import anaxigraph.api_support as api_support
from anaxigraph.config_authority import effective_semantic_policy, service_config_authority
from anaxigraph.operational_health import served_map_status
from anaxigraph.semantic_status_language import semantic_status_explanation


def semantic_router(context: Any) -> APIRouter:
    return SemanticRoutes(context).router


class SemanticRoutes:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.router = APIRouter()
        self.router.add_api_route("/api/semantic", self.status, methods=["GET"])
        self.router.add_api_route("/api/semantic/prepare", self.prepare, methods=["POST"])
        self.router.add_api_route("/api/semantic/refresh", self.refresh, methods=["POST"])

    def status(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        target = self.context.target_for_path(Path(row["path"]))
        config = self.context.selected_config(row)
        result = api_support.SemanticEngine(self.context.database).status(
            int(row["id"]), config.semantic
        )
        result["map_status"] = self._map_status(row)
        result["worker"] = self.context.semantic_refresh.status_for(Path(row["path"]))
        result["config_authority"] = service_config_authority(Path(row["path"]), target, config)
        result["semantic_policy"] = effective_semantic_policy(config.semantic)
        result["plain_language"] = semantic_status_explanation(result)
        return result

    async def prepare(
        self,
        repository_id: int | None = None,
        force: bool = False,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        """Reconcile one semantic stage against the current snapshot without scanning source."""

        row = self.context.selected_repository(repository_id)
        target = self._semantic_target(row)
        config = self.context.selected_config(row)
        self._require_enabled(row, target, config)
        if scan_required := self._scan_required(row, target, config):
            return scan_required
        self.context.admit_operation(int(row["id"]), "semantic_prepare", hold=True)
        try:
            plan = await asyncio.to_thread(
                api_support.SemanticEngine(self.context.database).plan,
                int(row["id"]),
                target.path,
                config,
                force=force,
                retry_failed=retry_failed,
            )
        finally:
            self.context.finish_operation(int(row["id"]), "semantic_prepare")
        return {
            "status": "prepared",
            **plan.as_dict(),
            **self._config_contract(row, target, config),
        }

    def refresh(
        self,
        repository_id: int | None = None,
        force: bool = False,
        retry_failed: bool = False,
        wait: bool = False,
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        target = self._semantic_target(row)
        config = self.context.selected_config(row)
        self._require_enabled(row, target, config)
        if scan_required := self._scan_required(row, target, config):
            return scan_required
        self.context.admit_operation(int(row["id"]), "semantic_refresh", hold=wait)
        if wait:
            try:
                return self._refresh_current_snapshot(row, target, config, force, retry_failed)
            finally:
                self.context.finish_operation(int(row["id"]), "semantic_refresh")
        started = self.context.semantic_refresh.start(
            target, force=force, retry_failed=retry_failed
        )
        return {
            "status": "started" if started else "already_running",
            "repository_id": row["id"],
        }

    def _semantic_target(self, row: dict[str, Any]) -> Any:
        target = self.context.target_for_path(Path(row["path"]))
        if target is None:
            raise HTTPException(
                status_code=403,
                detail="This indexed repository is not mounted as a semantic-analysis target",
            )
        return target

    def _require_enabled(self, row: dict[str, Any], target: Any, config: Any) -> None:
        if config.semantic.enabled:
            return
        authority = service_config_authority(Path(row["path"]), target, config)
        source = authority["service_config_path"] or "service defaults"
        raise HTTPException(
            status_code=400,
            detail=(
                f"Semantic analysis is disabled by authoritative service policy {source} "
                f"(registry key {authority['registry_key']!r})"
            ),
        )

    @staticmethod
    def _config_contract(row: dict[str, Any], target: Any, config: Any) -> dict[str, Any]:
        return {
            "config_authority": service_config_authority(Path(row["path"]), target, config),
            "semantic_policy": effective_semantic_policy(config.semantic),
        }

    def _refresh_current_snapshot(
        self,
        row: dict[str, Any],
        target: Any,
        config: Any,
        force: bool,
        retry_failed: bool,
    ) -> dict[str, Any]:
        if self.context.database.latest_snapshot(int(row["id"])) is None:
            return {
                "status": "scan_required",
                "repository_id": int(row["id"]),
                "recommended_action": "Run the explicit repository scan, then retry understand.",
                **self._config_contract(row, target, config),
            }
        result = api_support.SemanticEngine(self.context.database).bootstrap(
            int(row["id"]),
            target.path,
            config,
            force=force,
            retry_failed=retry_failed,
            plan_only=True,
        )
        return {"status": "prepared", **result, **self._config_contract(row, target, config)}

    def _scan_required(
        self, row: dict[str, Any], target: Any, config: Any
    ) -> dict[str, Any] | None:
        status = self._map_status(row)
        if status and status["state"] == "current":
            return None
        return {
            "status": "scan_required",
            "repository_id": int(row["id"]),
            "map_status": status,
            "recommended_action": (
                "Refresh the structural scan, then retry understand."
                if status
                else "Run the explicit repository scan, then retry understand."
            ),
            **self._config_contract(row, target, config),
        }

    def _map_status(self, row: dict[str, Any]) -> dict[str, Any] | None:
        snapshot = self.context.database.latest_snapshot(int(row["id"]))
        return served_map_status(Path(row["path"]), snapshot) if snapshot is not None else None
