"""Exact repository selection and service policy shared by MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.config import load_config
from anaxigraph.config_authority import effective_semantic_policy, service_config_authority
from anaxigraph.operational_health import served_map_status
from anaxigraph.registry_worktrees import expand_worktree_targets


class McpToolContext:
    def __init__(
        self,
        database: Any,
        repository: Path | None,
        config_path: Path | None,
        repository_targets: tuple[Any, ...],
    ) -> None:
        self.database = database
        self.repository = repository
        self.config_path = config_path
        self.repository_targets = repository_targets
        self.targets_by_path = {str(target.path.resolve()): target for target in repository_targets}

    def visible_repositories(self) -> list[dict[str, Any]]:
        self._refresh_targets()
        rows = self.database.repositories()
        if self.targets_by_path:
            rows = [row for row in rows if str(Path(row["path"]).resolve()) in self.targets_by_path]
        return rows

    def select(self, selector: str = "") -> tuple[dict[str, Any], Path]:
        self._refresh_targets()
        if selector:
            row = self.database.repository(int(selector) if selector.isdigit() else selector)
        else:
            row = (
                self.database.repository(self.repository)
                if self.repository
                else self.database.repository()
            )
        if row is None:
            raise ValueError("No analyzed repository is configured. Run anaxigraph scan first.")
        if self.targets_by_path and str(Path(row["path"]).resolve()) not in self.targets_by_path:
            raise ValueError("Repository is not in the active AnaxiGraph registry.")
        return row, Path(row["path"])

    def _refresh_targets(self) -> None:
        targets = expand_worktree_targets(self.repository_targets)
        self.targets_by_path = {str(target.path.resolve()): target for target in targets}

    def config_for(self, row: dict[str, Any], root: Path) -> Any:
        target = self.targets_by_path.get(str(root.resolve()))
        return load_config(root, target.config_path if target else self.config_path)

    def semantic_config_contract(
        self, row: dict[str, Any], root: Path, config: Any
    ) -> dict[str, Any]:
        target = self.targets_by_path.get(str(root.resolve()))
        return {
            "config_authority": service_config_authority(root, target, config),
            "semantic_policy": effective_semantic_policy(config.semantic),
        }

    def map_status(self, row: dict[str, Any], root: Path) -> dict[str, Any]:
        snapshot = self.database.latest_snapshot(int(row["id"]))
        if snapshot is None:
            raise ValueError("Repository has not been scanned")
        return served_map_status(root, snapshot)
