"""Focused registration facade for MCP tool families."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from anaxigraph.finding_mcp import register_finding_tools as register_finding_tools
from anaxigraph.graph_mcp import register_graph_tool
from anaxigraph.history_mcp import register_history_tools

__all__ = ["register_finding_tools", "register_query_tools"]


def register_query_tools(
    server: FastMCP,
    database: Any,
    context: Any,
    targets_by_path: dict[str, Any],
    config_path: Path | None,
    history_service: Any | None,
) -> None:
    register_graph_tool(server, database, context)
    register_history_tools(
        server,
        database=database,
        targets_by_path=targets_by_path,
        config_path=config_path,
        service=history_service,
        context=context,
    )
