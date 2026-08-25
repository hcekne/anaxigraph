"""AnaxiMCP: Streamable HTTP architecture intelligence for coding agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMCPSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from anaxigraph.agent import agent_scope, branch_collisions, impact_analysis
from anaxigraph.config import load_config
from anaxigraph.guidance import product_glossary
from anaxigraph.mcp_tools import register_finding_tools, register_query_tools
from anaxigraph.registry import RepositoryTarget
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_agent_protocol import semantic_agent_schema
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine


def create_anaxi_mcp_server(
    *,
    database: AnaxiIndex,
    repository: Path | None,
    config_path: Path | None,
    allowed_hosts: list[str] | None = None,
    allow_scan_tool: bool = False,
    repository_targets: tuple[RepositoryTarget, ...] = (),
    history_service: Any | None = None,
) -> FastMCP:
    server = _build_server(allowed_hosts)

    targets_by_path = {str(target.path.resolve()): target for target in repository_targets}

    def visible_repositories() -> list[dict[str, Any]]:
        rows = database.repositories()
        if targets_by_path:
            rows = [row for row in rows if str(Path(row["path"]).resolve()) in targets_by_path]
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
        name="ANAXIGRAPH_REPOSITORIES",
        description="List indexed repositories and the selector to pass to other AnaxiGraph tools.",
    )
    def repositories() -> dict[str, Any]:
        return {
            "repositories": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "path": row["path"],
                    "remote_url": row.get("remote_url"),
                    "scannable": str(Path(row["path"]).resolve()) in targets_by_path,
                }
                for row in visible_repositories()
            ]
        }

    @server.tool(
        name="ANAXIGRAPH_OVERVIEW",
        description="Return current repository size, languages, groups, coverage, and architecture finding counts.",
    )
    def overview(repository: str = "") -> dict[str, Any]:
        row, root = context(repository)
        result = database.overview(int(row["id"]))
        result["semantic"] = SemanticEngine(database).status(
            int(row["id"]), config_for(row, root).semantic
        )
        return result

    register_query_tools(server, database, context, targets_by_path, config_path, history_service)

    @server.tool(
        name="ANAXIGRAPH_SEMANTIC_STATUS",
        description=(
            "Report semantic-bootstrap coverage, freshness, pending/failed modules, token/cost "
            "usage, and the current repository-level dossier."
        ),
    )
    def semantic_status(repository: str = "") -> dict[str, Any]:
        row, root = context(repository)
        return SemanticEngine(database).status(int(row["id"]), config_for(row, root).semantic)

    @server.tool(
        name="ANAXIGRAPH_TAXONOMY",
        description=(
            "Return the current agent-proposed, agent-reviewed, deterministically validated "
            "semantic area/subsystem map with provenance, confidence, facets, and review issues."
        ),
    )
    def semantic_taxonomy(repository: str = "") -> dict[str, Any]:
        row, _ = context(repository)
        result = database.semantic_taxonomy(int(row["id"]))
        if result is None:
            return {
                "status": "not_ready",
                "message": "No finalized semantic taxonomy exists for the current snapshot.",
            }
        return result

    @server.tool(
        name="ANAXIGRAPH_SEMANTIC_SCHEMA",
        title="Read semantic dossier contract",
        description=(
            "Read the strict dossier, taxonomy, and taxonomy-review schemas and reasoning rules "
            "once before executing agent-funded semantic work."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def semantic_schema() -> dict[str, Any]:
        return semantic_agent_schema()

    @server.tool(
        name="ANAXIGRAPH_SEMANTIC_WORK",
        title="Claim semantic mapping work",
        description=(
            "Prepare and lease the next bounded semantic mapping task to this coding agent. Use "
            "only when the repository opts into semantic.provider: agent. This changes queue "
            "state but never writes the target repository."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def semantic_work(
        agent_id: str,
        agent_model: str = "",
        retry_failed: bool = False,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = context(repository)
        return SemanticEngine(database).claim_agent_work(
            int(row["id"]),
            root,
            config_for(row, root),
            agent_id=agent_id,
            agent_model=agent_model,
            retry_failed=retry_failed,
        )

    @server.tool(
        name="ANAXIGRAPH_SEMANTIC_EVIDENCE",
        title="Read a semantic evidence page",
        description=(
            "Read one overflow evidence page for a leased semantic task. Fetch every page named "
            "by the work packet before submitting its dossier."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def semantic_evidence(
        job_id: int,
        lease_token: str,
        page: int,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = context(repository)
        return SemanticEngine(database).agent_evidence_page(
            int(row["id"]),
            root,
            config_for(row, root),
            job_id=job_id,
            lease_token=lease_token,
            page=page,
        )

    @server.tool(
        name="ANAXIGRAPH_SEMANTIC_SUBMIT",
        title="Store a semantic mapping result",
        description=(
            "Validate and store one completed coding-agent dossier, taxonomy, or taxonomy review "
            "in AnaxiIndex. This index-only write never changes repository source. Repeating the "
            "same completed submission is safe."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def semantic_submit(
        job_id: int,
        lease_token: str,
        dossier: dict[str, Any],
        input_tokens: int = 0,
        output_tokens: int = 0,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = context(repository)
        return SemanticEngine(database).submit_agent_work(
            int(row["id"]),
            root,
            config_for(row, root),
            job_id=job_id,
            lease_token=lease_token,
            dossier=dossier,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @server.tool(
        name="ANAXIGRAPH_SEMANTIC_RELEASE",
        title="Release semantic mapping work",
        description=(
            "Return an unfinished leased semantic task to the queue without consuming an "
            "attempt, for example when the coding agent lacks required local source access."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def semantic_release(
        job_id: int,
        lease_token: str,
        reason: str,
        repository: str = "",
    ) -> dict[str, Any]:
        row, root = context(repository)
        return SemanticEngine(database).release_agent_work(
            int(row["id"]),
            config_for(row, root),
            job_id=job_id,
            lease_token=lease_token,
            reason=reason,
        )

    @server.tool(
        name="ANAXIGRAPH_MODULES",
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
                item for item in items if lowered in f"{item['path']} {item['summary']}".lower()
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
        name="ANAXIGRAPH_SEARCH",
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
        name="ANAXIGRAPH_FILE",
        description="Inspect one module's summary, symbols, dependencies, dependants, Git history, and semantic provenance.",
    )
    def file_details(path: str, repository: str = "") -> dict[str, Any]:
        row, _ = context(repository)
        result = database.file_details(int(row["id"]), _safe_relative_path(path))
        if result is None:
            raise ValueError(f"File is not present in the current snapshot: {path}")
        return result

    @server.tool(
        name="ANAXIGRAPH_SCOPE",
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
        name="ANAXIGRAPH_IMPACT",
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

    register_finding_tools(server, database, context, config_for)

    @server.tool(
        name="ANAXIGRAPH_GUIDE",
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
        name="ANAXIGRAPH_BRANCH_COLLISIONS",
        description="Compare local and origin feature branches and report files changed by more than one branch.",
    )
    def collisions(repository: str = "") -> dict[str, Any]:
        row, _ = context(repository)
        return branch_collisions(database, repository_id=int(row["id"]))

    if allow_scan_tool:

        @server.tool(
            name="ANAXIGRAPH_SCAN",
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


def _build_server(allowed_hosts: list[str] | None) -> FastMCP:
    # MCP 1.x ships postponed settings annotations that need one explicit rebuild on Python 3.11.
    FastMCPSettings.model_rebuild()
    security = TransportSecuritySettings(
        allowed_hosts=allowed_hosts
        or ["127.0.0.1:*", "localhost:*", "[::1]:*", "anaxigraph:*", "testserver"]
    )
    return FastMCP(
        "AnaxiMCP",
        instructions=(
            "AnaxiMCP exposes the AnaxiIndex knowledge held by AnaxiGraph. "
            "For an agent-funded semantic baseline, call ANAXIGRAPH_SEMANTIC_SCHEMA once, then "
            "repeat WORK → optional EVIDENCE pages → SUBMIT until WORK returns complete. The "
            "coding agent supplies the reasoning and tokens; submission writes only validated "
            "interpretations to AnaxiIndex, never source files. Use these tools to understand "
            "repository architecture before editing. Prefer ANAXIGRAPH_SCOPE for a new goal, "
            "ANAXIGRAPH_IMPACT before changing a shared interface, and ANAXIGRAPH_FILE for the "
            "complete semantic dossier behind a module. Parser facts and LLM inferences are "
            "labeled separately. Findings and pattern advice are recommendations, not permission "
            "to refactor."
        ),
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise ValueError("A repository-relative file path is required")
    return normalized
