"""AnaxiMCP tools for durable temporal import control."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from anaxigraph.history_jobs import HistoryJobService
from anaxigraph.registry import RepositoryTarget

RepositoryContext = Callable[[str], tuple[dict[str, Any], Path]]


def register_history_tools(
    server: FastMCP,
    *,
    database: Any,
    context: RepositoryContext,
    targets_by_path: dict[str, RepositoryTarget],
    config_path: Path | None,
    service: HistoryJobService | None = None,
) -> None:
    coordinator = service or HistoryJobService(database)

    def target_for(root: Path) -> RepositoryTarget:
        return targets_by_path.get(str(root.resolve())) or RepositoryTarget(
            key="default", path=root, config_path=config_path, history_snapshots="auto"
        )

    _register_status(server, coordinator, context)
    _register_import(server, coordinator, context, target_for)
    _register_cancel(server, coordinator, context)


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


def _register_import(
    server: FastMCP,
    service: HistoryJobService,
    context: RepositoryContext,
    target_for: Callable[[Path], RepositoryTarget],
) -> None:
    @server.tool(
        name="ANAXIGRAPH_HISTORY_IMPORT",
        title="Start or resume Git history import",
        description=(
            "Build code maps in the background from commits in the repository's main Git history, "
            "or continue after an interruption from the last complete map. This writes only to "
            "AnaxiGraph's external index, never to repository source."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def history_import(repository: str = "") -> dict[str, Any]:
        row, root = context(repository)
        result = service.start(target_for(root))
        result["repository_id"] = int(row["id"])
        return result


def _register_cancel(
    server: FastMCP, service: HistoryJobService, context: RepositoryContext
) -> None:
    @server.tool(
        name="ANAXIGRAPH_HISTORY_CANCEL",
        title="Cancel Git history import",
        description=(
            "Ask the import to stop after it finishes the current commit's code map. Completed "
            "maps remain usable, and a later import continues without repeating them."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def history_cancel(repository: str = "") -> dict[str, Any]:
        row, _ = context(repository)
        return service.cancel(int(row["id"]))
