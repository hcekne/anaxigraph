"""Repository catalogue and architecture read routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import anaxigraph.api_support as api_support


def repository_router(context: Any) -> APIRouter:
    return RepositoryRoutes(context).router


class RepositoryRoutes:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.database = context.database
        self.router = APIRouter()
        self.router.add_api_route("/api/repositories", self.repositories, methods=["GET"])
        self.router.add_api_route("/api/glossary", self.glossary, methods=["GET"])
        self.router.add_api_route("/api/overview", self.overview, methods=["GET"])
        self.router.add_api_route("/api/modules", self.modules, methods=["GET"])
        self.router.add_api_route("/api/groups", self.groups, methods=["GET"])
        self.router.add_api_route("/api/taxonomy", self.taxonomy, methods=["GET"])
        self.router.add_api_route("/api/file", self.file_details, methods=["GET"])
        self.router.add_api_route("/api/search", self.search, methods=["GET"])
        self.router.add_api_route("/api/snapshots", self.snapshots, methods=["GET"])

    def repositories(self) -> list[dict[str, Any]]:
        target_order = {
            str(target.path.resolve()): index for index, target in enumerate(self.context.targets)
        }
        rows = self.context.visible_repositories()
        rows.sort(key=lambda row: _repository_order(row, target_order))
        return [self._repository(row) for row in rows]

    def _repository(self, row: dict[str, Any]) -> dict[str, Any]:
        target = self.context.target_for_path(Path(row["path"]))
        config = self.context.selected_config(row)
        first_target = self.context.targets[0] if self.context.targets else None
        return {
            **row,
            "scannable": target is not None,
            "registry_key": target.key if target else None,
            "default": bool(
                first_target and Path(row["path"]).resolve() == first_target.path.resolve()
            ),
            "config_path": str(
                (target.config_path if target else None) or config.config_path or ""
            ),
            "history_snapshots": target.history_snapshots if target else None,
        }

    def glossary(self) -> dict[str, Any]:
        return api_support.product_glossary()

    def overview(
        self,
        repository_id: int | None = None,
        snapshot_id: int | None = None,
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        result = self.database.overview(int(row["id"]), snapshot_id)
        config = self.context.selected_config(row)
        result["coverage"] = api_support.coverage_diagnostics(
            row, config, result.get("coverage") or {}
        )
        if snapshot_id is None:
            result["semantic"] = api_support.SemanticEngine(self.database).status(
                int(row["id"]), config.semantic
            )
        return result

    def modules(
        self,
        repository_id: int | None = None,
        snapshot_id: int | None = None,
        limit: int = Query(default=250, ge=1, le=1_000),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        row = self.context.selected_repository(repository_id)
        return self.database.modules(int(row["id"]), snapshot_id, limit=limit, offset=offset)

    def groups(
        self,
        repository_id: int | None = None,
        snapshot_id: int | None = None,
        layer: str = Query(default="effective", pattern="^(effective|semantic|policy|inferred)$"),
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        return {
            "layer": layer,
            "groups": self.database.group_hierarchy(int(row["id"]), snapshot_id, layer=layer),
        }

    def taxonomy(
        self,
        repository_id: int | None = None,
        snapshot_id: int | None = None,
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        result = self.database.semantic_taxonomy(int(row["id"]), snapshot_id)
        if result is None:
            raise HTTPException(status_code=404, detail="No current semantic taxonomy")
        return result

    def file_details(
        self,
        path: str = Query(min_length=1, max_length=2_000),
        repository_id: int | None = None,
        snapshot_id: int | None = None,
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        result = self.database.file_details(int(row["id"]), path, snapshot_id)
        if result is None:
            raise HTTPException(status_code=404, detail="File not found in snapshot")
        return result

    def search(
        self,
        q: str = Query(min_length=2, max_length=1_000),
        repository_id: int | None = None,
        limit: int = Query(default=30, ge=1, le=100),
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        return {
            "query": q,
            "results": self.database.search(int(row["id"]), q, limit=limit),
        }

    def snapshots(
        self,
        repository_id: int | None = None,
        limit: int = Query(default=100, ge=1, le=1_000),
    ) -> list[dict[str, Any]]:
        row = self.context.selected_repository(repository_id)
        return self.database.timeline_snapshots(int(row["id"]), limit=limit)


def _repository_order(row: dict[str, Any], target_order: dict[str, int]) -> tuple[int, int]:
    path = str(Path(row["path"]).resolve())
    return (0, target_order[path]) if path in target_order else (1, 0)
