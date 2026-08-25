"""Responsive MCP runtime adapters for synchronous AnaxiGraph services."""

from __future__ import annotations

import asyncio
import functools
import inspect
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMCPSettings
from mcp.server.transport_security import TransportSecuritySettings

_INSTRUCTIONS = (
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
)


class ResponsiveFastMCP(FastMCP):
    """Run synchronous tool handlers outside the ASGI event-loop thread.

    FastMCP awaits coroutine tools but calls ordinary functions inline. Most AnaxiGraph
    tools use synchronous SQLite and filesystem services, so a long semantic planning or
    submission call would otherwise make health, inventory, and every other endpoint wait.
    """

    def add_tool(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        handler = fn if inspect.iscoroutinefunction(fn) else _threaded(fn)
        super().add_tool(handler, *args, **kwargs)


def build_responsive_mcp(allowed_hosts: list[str] | None) -> ResponsiveFastMCP:
    """Build AnaxiMCP with loopback transport defaults and nonblocking tools."""

    # MCP 1.x ships postponed settings annotations that need one rebuild on Python 3.11.
    FastMCPSettings.model_rebuild()
    security = TransportSecuritySettings(
        allowed_hosts=allowed_hosts
        or ["127.0.0.1:*", "localhost:*", "[::1]:*", "anaxigraph:*", "testserver"]
    )
    return ResponsiveFastMCP(
        "AnaxiMCP",
        instructions=_INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )


def _threaded(function: Any) -> Any:
    @functools.wraps(function)
    async def invoke(*args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(function, *args, **kwargs)

    return invoke
