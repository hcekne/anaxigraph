"""AnaxiMCP composition root for coding-agent architecture intelligence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.mcp_core import CoreMcpTools, McpToolContext
from anaxigraph.mcp_runtime import build_responsive_mcp
from anaxigraph.mcp_tools import register_finding_tools, register_query_tools
from anaxigraph.registry import RepositoryTarget
from anaxigraph.semantic_mcp import register_semantic_tools
from anaxigraph.storage import AnaxiIndex


def create_anaxi_mcp_server(
    *,
    database: AnaxiIndex,
    repository: Path | None,
    config_path: Path | None,
    allowed_hosts: list[str] | None = None,
    allow_scan_tool: bool = False,
    repository_targets: tuple[RepositoryTarget, ...] = (),
    history_service: Any | None = None,
) -> Any:
    server = build_responsive_mcp(allowed_hosts)
    context = McpToolContext(database, repository, config_path, repository_targets)

    CoreMcpTools(server, context, allow_scan=allow_scan_tool).register()
    register_query_tools(
        server,
        database,
        context.select,
        context.targets_by_path,
        config_path,
        history_service,
    )
    register_semantic_tools(
        server,
        database,
        context.select,
        context.config_for,
        context.semantic_config_contract,
    )
    register_finding_tools(server, database, context.select, context.config_for)
    return server
