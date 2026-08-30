"""Repository selection and core read/planning tools for AnaxiMCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.agent import agent_scope, impact_analysis
from anaxigraph.config import load_config
from anaxigraph.config_authority import effective_semantic_policy, service_config_authority
from anaxigraph.operational_health import served_map_status
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_mcp import current_semantic_status


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
        self.targets_by_path = {str(target.path.resolve()): target for target in repository_targets}

    def visible_repositories(self) -> list[dict[str, Any]]:
        rows = self.database.repositories()
        if self.targets_by_path:
            rows = [row for row in rows if str(Path(row["path"]).resolve()) in self.targets_by_path]
        return rows

    def select(self, selector: str = "") -> tuple[dict[str, Any], Path]:
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


class CoreMcpTools:
    def __init__(self, server: Any, context: McpToolContext, *, allow_scan: bool) -> None:
        self.server = server
        self.context = context
        self.database = context.database
        self.allow_scan = allow_scan

    def register(self) -> None:
        self._register_inventory_tools()
        self._register_agent_tools()
        if self.allow_scan:
            self.server.add_tool(
                self.scan,
                name="ANAXIGRAPH_SCAN",
                description=(
                    "Read the configured repository again and save a new code map. Repository "
                    "files stay read-only; only AnaxiGraph's external index changes."
                ),
            )

    def _register_inventory_tools(self) -> None:
        for handler, name, description in (
            (
                self.repositories,
                "ANAXIGRAPH_REPOSITORIES",
                "List indexed repositories and selectors for other AnaxiGraph tools.",
            ),
            (
                self.overview,
                "ANAXIGRAPH_OVERVIEW",
                "Summarize repository size, languages, code areas, test coverage, and finding counts.",
            ),
            (
                self.search,
                "ANAXIGRAPH_SEARCH",
                "Find files and named code parts that are most relevant to a concept or feature.",
            ),
            (
                self.file_details,
                "ANAXIGRAPH_FILE",
                "Inspect one file: what it does, direct links to other files, Git history, named code parts, saved AI description, evidence, and who or what created that description.",
            ),
        ):
            self.server.add_tool(handler, name=name, description=description)

    def _register_agent_tools(self) -> None:
        self.server.add_tool(
            self.scope,
            name="ANAXIGRAPH_SCOPE",
            description=(
                "For a coding goal, return a small list of likely files, advice about where to "
                "start, AI-checked pattern results, risks, focused checks, and rescan guidance. "
                "Ask again when a coherent change may have moved responsibilities or dependencies."
            ),
        )
        self.server.add_tool(
            self.impact,
            name="ANAXIGRAPH_IMPACT",
            description=(
                "Before changing a file or named code part, find code that uses it directly or "
                "indirectly, relevant tests, possible database changes, files marked for extra "
                "care, and reasons the change may be risky."
            ),
        )

    def repositories(self) -> dict[str, Any]:
        targets = self.context.targets_by_path
        return {
            "repositories": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "path": row["path"],
                    "remote_url": row.get("remote_url"),
                    "scannable": str(Path(row["path"]).resolve()) in targets,
                    "map_status": self.context.map_status(row, Path(row["path"])),
                }
                for row in self.context.visible_repositories()
            ]
        }

    def overview(self, repository: str = "") -> dict[str, Any]:
        row, root = self.context.select(repository)
        result = self.database.overview(int(row["id"]))
        result["map_status"] = self.context.map_status(row, root)
        config = self.context.config_for(row, root)
        semantic = current_semantic_status(self.database, int(row["id"]), config.semantic)
        semantic.update(self.context.semantic_config_contract(row, root, config))
        result["semantic"] = semantic
        return result

    def search(self, query: str, limit: int = 20, repository: str = "") -> dict[str, Any]:
        row, root = self.context.select(repository)
        bounded = max(1, min(limit, 50))
        return {
            "query": query,
            "results": self.database.search(int(row["id"]), query, limit=bounded),
            "map_status": self.context.map_status(row, root),
        }

    def file_details(self, path: str, repository: str = "") -> dict[str, Any]:
        row, root = self.context.select(repository)
        result = self.database.file_details(int(row["id"]), _safe_relative_path(path))
        if result is None:
            raise ValueError(f"File is not present in the current saved scan: {path}")
        result["map_status"] = self.context.map_status(row, root)
        return result

    def scope(
        self,
        goal: str,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = self.context.select(repository)
        return agent_scope(
            self.database,
            repository_id=int(row["id"]),
            goal=goal,
            config=self.context.config_for(row, root),
        )

    def impact(self, target: str, repository: str = "") -> dict[str, Any]:
        row, root = self.context.select(repository)
        return impact_analysis(
            self.database,
            repository_id=int(row["id"]),
            target=target,
            config=self.context.config_for(row, root),
        )

    def scan(self, repository: str = "") -> dict[str, Any]:
        _, root = self.context.select(repository)
        target = self.context.targets_by_path.get(str(root.resolve()))
        if target is None and self.context.targets_by_path:
            raise ValueError("Repository is indexed but is not a configured scan target")
        selected_config = target.config_path if target else self.context.config_path
        return RepositoryScanner(self.database).scan(root, config_path=selected_config).as_dict()


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").removeprefix("./")
    if not normalized or normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise ValueError("A repository-relative file path is required")
    return normalized
