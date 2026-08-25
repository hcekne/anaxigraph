"""Repository selection and core read/planning tools for AnaxiMCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.agent import agent_scope, branch_collisions, impact_analysis
from anaxigraph.config import load_config
from anaxigraph.config_authority import effective_semantic_policy, service_config_authority
from anaxigraph.guidance import product_glossary
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


class CoreMcpTools:
    def __init__(self, server: Any, context: McpToolContext, *, allow_scan: bool) -> None:
        self.server = server
        self.context = context
        self.database = context.database
        self.allow_scan = allow_scan

    def register(self) -> None:
        self._register_inventory_tools()
        self._register_agent_tools()
        self._register_misc_tools()
        if self.allow_scan:
            self.server.add_tool(
                self.scan,
                name="ANAXIGRAPH_SCAN",
                description=(
                    "Refresh the configured repository snapshot. The target is read-only; only "
                    "AnaxiIndex changes."
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
                "Return repository size, languages, groups, coverage, and finding counts.",
            ),
            (
                self.modules,
                "ANAXIGRAPH_MODULES",
                "List and filter modules with placement, coupling, coverage, and review signals.",
            ),
            (
                self.search,
                "ANAXIGRAPH_SEARCH",
                "Find the most relevant modules and symbols for a codebase concept or feature.",
            ),
            (
                self.file_details,
                "ANAXIGRAPH_FILE",
                "Inspect one module's graph, history, symbols, semantics, and provenance.",
            ),
        ):
            self.server.add_tool(handler, name=name, description=description)

    def _register_agent_tools(self) -> None:
        self.server.add_tool(
            self.scope,
            name="ANAXIGRAPH_SCOPE",
            description=(
                "Build bounded task context plus an evidence-backed placement, reviewed-pattern, "
                "safety, and verification decision for a coding goal. After a rescan, pass the "
                "earlier post_change_baseline to measure what changed."
            ),
        )
        self.server.add_tool(
            self.impact,
            name="ANAXIGRAPH_IMPACT",
            description=(
                "Traverse reverse dependencies before changing a file or symbol and return "
                "dependants, tests, migrations, protected paths, and risk."
            ),
        )
        self.server.add_tool(
            self.collisions,
            name="ANAXIGRAPH_BRANCH_COLLISIONS",
            description="Report files changed by more than one local or origin feature branch.",
        )

    def _register_misc_tools(self) -> None:
        self.server.add_tool(
            self.guide,
            name="ANAXIGRAPH_GUIDE",
            description=(
                "Explain architecture groups, graph overlays, finding states, confidence, and "
                "agent workflows in plain language."
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
                }
                for row in self.context.visible_repositories()
            ]
        }

    def overview(self, repository: str = "") -> dict[str, Any]:
        row, root = self.context.select(repository)
        result = self.database.overview(int(row["id"]))
        config = self.context.config_for(row, root)
        semantic = current_semantic_status(self.database, int(row["id"]), config.semantic)
        semantic.update(self.context.semantic_config_contract(row, root, config))
        result["semantic"] = semantic
        return result

    def modules(
        self,
        query: str = "",
        area: str = "",
        subsystem: str = "",
        language: str = "",
        sort: str = "path",
        descending: bool = False,
        limit: int = 200,
        repository: str = "",
    ) -> dict[str, Any]:
        row, _ = self.context.select(repository)
        items = self.database.modules(int(row["id"]))
        items = _filter_modules(items, query, area, subsystem, language)
        allowed = {
            "path",
            "lines_of_code",
            "complexity",
            "fan_in",
            "fan_out",
            "change_count",
            "first_changed_at",
            "last_commit_at",
        }
        sort_key = sort if sort in allowed else "path"
        items.sort(
            key=lambda item: (item.get(sort_key) is None, item.get(sort_key) or ""),
            reverse=descending,
        )
        return {"total": len(items), "modules": items[: max(1, min(limit, 1_000))]}

    def search(self, query: str, limit: int = 20, repository: str = "") -> dict[str, Any]:
        row, _ = self.context.select(repository)
        bounded = max(1, min(limit, 50))
        return {
            "query": query,
            "results": self.database.search(int(row["id"]), query, limit=bounded),
        }

    def file_details(self, path: str, repository: str = "") -> dict[str, Any]:
        row, _ = self.context.select(repository)
        result = self.database.file_details(int(row["id"]), _safe_relative_path(path))
        if result is None:
            raise ValueError(f"File is not present in the current snapshot: {path}")
        return result

    def scope(
        self,
        goal: str,
        branch: str = "",
        repository: str = "",
        verification_baseline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row, root = self.context.select(repository)
        return agent_scope(
            self.database,
            repository_id=int(row["id"]),
            goal=goal,
            branch=branch or None,
            config=self.context.config_for(row, root),
            verification_baseline=verification_baseline,
        )

    def impact(self, target: str, branch: str = "", repository: str = "") -> dict[str, Any]:
        row, root = self.context.select(repository)
        return impact_analysis(
            self.database,
            repository_id=int(row["id"]),
            target=target,
            branch=branch or None,
            config=self.context.config_for(row, root),
        )

    def guide(self, topic: str = "all") -> dict[str, Any]:
        value = product_glossary()
        if topic == "all":
            return value
        if topic not in value:
            raise ValueError(f"Unknown guide topic: {topic}")
        return {topic: value[topic]}

    def collisions(self, repository: str = "") -> dict[str, Any]:
        row, _ = self.context.select(repository)
        return branch_collisions(self.database, repository_id=int(row["id"]))

    def scan(self, repository: str = "") -> dict[str, Any]:
        _, root = self.context.select(repository)
        target = self.context.targets_by_path.get(str(root.resolve()))
        if target is None and self.context.targets_by_path:
            raise ValueError("Repository is indexed but is not a configured scan target")
        selected_config = target.config_path if target else self.context.config_path
        return RepositoryScanner(self.database).scan(root, config_path=selected_config).as_dict()


def _filter_modules(
    items: list[dict[str, Any]], query: str, area: str, subsystem: str, language: str
) -> list[dict[str, Any]]:
    lowered = query.strip().lower()
    if lowered:
        items = [item for item in items if lowered in f"{item['path']} {item['summary']}".lower()]
    for field, value in (
        ("architecture_area", area),
        ("architecture_subsystem", subsystem),
        ("language", language),
    ):
        if value:
            items = [item for item in items if item[field] == value]
    return items


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").removeprefix("./")
    if not normalized or normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise ValueError("A repository-relative file path is required")
    return normalized
