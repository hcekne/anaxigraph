"""AnaxiMCP: Streamable HTTP architecture intelligence for coding agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMCPSettings
from mcp.server.transport_security import TransportSecuritySettings

from codeintel.agent import agent_scope, branch_collisions, finding_context, impact_analysis
from codeintel.config import load_config
from codeintel.guidance import product_glossary
from codeintel.registry import RepositoryTarget
from codeintel.scanner import RepositoryScanner
from codeintel.storage import Database


def create_anaxi_mcp_server(
    *,
    database: Database,
    repository: Path | None,
    config_path: Path | None,
    allowed_hosts: list[str] | None = None,
    allow_scan_tool: bool = False,
    repository_targets: tuple[RepositoryTarget, ...] = (),
) -> FastMCP:
    # MCP 1.x defines this generic settings model with postponed annotations.
    # Rebuilding it after the module is fully imported resolves the lifespan type
    # for pydantic-settings (notably on Python 3.11) and avoids a noisy warning.
    FastMCPSettings.model_rebuild()
    security = TransportSecuritySettings(
        allowed_hosts=allowed_hosts
        or [
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            "codeintel:*",
            "anaxigraph:*",
            "testserver",
        ]
    )
    server = FastMCP(
        "AnaxiMCP",
        instructions=(
            "AnaxiMCP exposes the AnaxiIndex knowledge held by AnaxiGraph. "
            "Use these tools to understand repository architecture before editing. "
            "Prefer CODEINTEL_SCOPE for a new goal and CODEINTEL_IMPACT before changing a shared interface. "
            "Parser facts and LLM inferences are labeled separately. Findings are recommendations, not permission to refactor."
        ),
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )

    targets_by_path = {str(target.path.resolve()): target for target in repository_targets}

    def visible_repositories() -> list[dict[str, Any]]:
        rows = database.repositories()
        if targets_by_path:
            rows = [
                row
                for row in rows
                if str(Path(row["path"]).resolve()) in targets_by_path
            ]
        return rows

    def context(selector: str = "") -> tuple[dict[str, Any], Path]:
        if selector:
            row = database.repository(int(selector) if selector.isdigit() else selector)
        else:
            row = database.repository(repository) if repository else database.repository()
        if row is None:
            raise ValueError("No analyzed repository is configured. Run anaxigraph scan first.")
        if targets_by_path and str(Path(row["path"]).resolve()) not in targets_by_path:
            raise ValueError("Repository is not in the active AnaxiGraph registry.")
        return row, Path(row["path"])

    def config_for(row: dict[str, Any], root: Path):
        target = targets_by_path.get(str(root.resolve()))
        return load_config(root, target.config_path if target else config_path)

    @server.tool(
        name="CODEINTEL_REPOSITORIES",
        description="List indexed repositories and the selector to pass to other AnaxiGraph tools.",
    )
    def repositories() -> dict[str, Any]:
        return {
            "repositories": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "path": row["path"],
                    "scannable": str(Path(row["path"]).resolve()) in targets_by_path,
                }
                for row in visible_repositories()
            ]
        }

    @server.tool(
        name="CODEINTEL_OVERVIEW",
        description="Return current repository size, languages, groups, coverage, and architecture finding counts.",
    )
    def overview(repository: str = "") -> dict[str, Any]:
        row, _ = context(repository)
        return database.overview(int(row["id"]))

    @server.tool(
        name="CODEINTEL_MODULES",
        description=(
            "List and filter the AnaxiIndex module inventory, including architecture area, "
            "summary, size, coupling, coverage, Git activity, findings, and review signals."
        ),
    )
    def modules(
        query: str = "",
        area: str = "",
        subsystem: str = "",
        language: str = "",
        sort: str = "path",
        descending: bool = False,
        limit: int = 200,
        repository: str = "",
    ) -> dict[str, Any]:
        row, _ = context(repository)
        items = database.modules(int(row["id"]))
        lowered = query.strip().lower()
        if lowered:
            items = [
                item
                for item in items
                if lowered in f"{item['path']} {item['summary']}".lower()
            ]
        if area:
            items = [item for item in items if item["architecture_area"] == area]
        if subsystem:
            items = [item for item in items if item["architecture_subsystem"] == subsystem]
        if language:
            items = [item for item in items if item["language"] == language]
        allowed_sort = {
            "path",
            "lines_of_code",
            "complexity",
            "fan_in",
            "fan_out",
            "change_count",
            "first_changed_at",
            "last_commit_at",
        }
        sort_key = sort if sort in allowed_sort else "path"
        items.sort(
            key=lambda item: (item.get(sort_key) is None, item.get(sort_key) or ""),
            reverse=descending,
        )
        bounded = max(1, min(limit, 1_000))
        return {"total": len(items), "modules": items[:bounded]}

    @server.tool(
        name="CODEINTEL_SEARCH",
        description="Find the most relevant modules and symbols for a codebase concept or feature.",
    )
    def search(query: str, limit: int = 20, repository: str = "") -> dict[str, Any]:
        row, _ = context(repository)
        bounded = max(1, min(limit, 50))
        return {
            "query": query,
            "results": database.search(int(row["id"]), query, limit=bounded),
        }

    @server.tool(
        name="CODEINTEL_FILE",
        description="Inspect one module's summary, symbols, dependencies, dependants, Git history, and semantic provenance.",
    )
    def file_details(path: str, repository: str = "") -> dict[str, Any]:
        row, _ = context(repository)
        result = database.file_details(int(row["id"]), _safe_relative_path(path))
        if result is None:
            raise ValueError(f"File is not present in the current snapshot: {path}")
        return result

    @server.tool(
        name="CODEINTEL_SCOPE",
        description="Build the smallest useful task context for a coding goal, including files, tests, protected boundaries, findings, and branch collisions.",
    )
    def scope(goal: str, branch: str = "", repository: str = "") -> dict[str, Any]:
        row, root = context(repository)
        config = config_for(row, root)
        return agent_scope(
            database,
            repository_id=int(row["id"]),
            goal=goal,
            branch=branch or None,
            config=config,
        )

    @server.tool(
        name="CODEINTEL_IMPACT",
        description="Traverse reverse dependencies before changing a file or symbol and return dependants, tests, migrations, protected paths, and risk.",
    )
    def impact(target: str, branch: str = "", repository: str = "") -> dict[str, Any]:
        row, root = context(repository)
        config = config_for(row, root)
        return impact_analysis(
            database,
            repository_id=int(row["id"]),
            target=target,
            branch=branch or None,
            config=config,
        )

    @server.tool(
        name="CODEINTEL_FINDINGS",
        description=(
            "List persistent review signals. Use status='planned' for work a human has explicitly "
            "approved for an agent; active signals are not automatic permission to refactor."
        ),
    )
    def findings(status: str = "active", limit: int = 100, repository: str = "") -> dict[str, Any]:
        row, _ = context(repository)
        statuses = ()
        if status == "active":
            statuses = ("new", "acknowledged", "accepted", "planned", "regressed")
        elif status != "all":
            statuses = (status,)
        return {
            "findings": database.findings(
                int(row["id"]), statuses=statuses, limit=max(1, min(limit, 500))
            )
        }

    @server.tool(
        name="CODEINTEL_FINDING_CONTEXT",
        description=(
            "Turn one finding into an actionable handoff with affected files, impact, tests, "
            "protected paths, risk, and verification steps. Planned status means human-approved."
        ),
    )
    def finding_work(finding_id: int, branch: str = "", repository: str = "") -> dict[str, Any]:
        row, root = context(repository)
        return finding_context(
            database,
            repository_id=int(row["id"]),
            finding_id=finding_id,
            branch=branch or None,
            config=config_for(row, root),
        )

    @server.tool(
        name="CODEINTEL_GUIDE",
        description=(
            "Explain architecture groups, graph overlays, finding states, confidence, and the "
            "human-to-agent workflow in plain language."
        ),
    )
    def guide(topic: str = "all") -> dict[str, Any]:
        value = product_glossary()
        if topic == "all":
            return value
        if topic not in value:
            raise ValueError(f"Unknown guide topic: {topic}")
        return {topic: value[topic]}

    @server.tool(
        name="CODEINTEL_BRANCH_COLLISIONS",
        description="Compare local and origin feature branches and report files changed by more than one branch.",
    )
    def collisions(repository: str = "") -> dict[str, Any]:
        row, _ = context(repository)
        return branch_collisions(database, repository_id=int(row["id"]))

    if allow_scan_tool:

        @server.tool(
            name="CODEINTEL_SCAN",
            description="Refresh the configured repository snapshot. The target is read-only; only AnaxiIndex changes.",
        )
        def scan(repository: str = "") -> dict[str, Any]:
            _, root = context(repository)
            target = targets_by_path.get(str(root.resolve()))
            if target is None and repository_targets:
                raise ValueError("Repository is indexed but is not a configured scan target")
            selected_config = target.config_path if target else config_path
            return RepositoryScanner(database).scan(root, config_path=selected_config).as_dict()

    return server


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise ValueError("A repository-relative file path is required")
    return normalized


# Compatibility alias retained for existing Python integrations.
create_mcp_server = create_anaxi_mcp_server
