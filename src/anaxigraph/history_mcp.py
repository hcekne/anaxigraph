"""AnaxiMCP tools for durable temporal import control."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from anaxigraph.history_jobs import HistoryJobService

RepositoryContext = Callable[[str], tuple[dict[str, Any], Path]]


def register_history_tools(
    server: FastMCP,
    *,
    database: Any,
    context: RepositoryContext,
    service: HistoryJobService | None = None,
) -> None:
    coordinator = service or HistoryJobService(database)
    _register_status(server, coordinator, context)


def _register_status(
    server: FastMCP, service: HistoryJobService, context: RepositoryContext
) -> None:
    @server.tool(
        name="ANAXIGRAPH_HISTORY_STATUS",
        title="Read Git history import status",
        description=(
            "Read saved progress, work counts, estimated time remaining, and the last complete "
            "code map from Git history. The current code map remains usable during import."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def history_status(repository: str = "") -> dict[str, Any]:
        row, _ = context(repository)
        return service.status(int(row["id"]))
