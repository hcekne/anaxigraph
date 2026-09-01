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
    "To build or resume the complete AI-created code map, run `anaxigraph understand "
    "<repository> --executor codex --background`, then watch `anaxigraph semantic-status "
    "<repository>`. Do not report completion until semantic status says semantically_ready: true. "
    "Never edit repository source while mapping; the official executor processes one saved task "
    "at a time and writes only checked AI descriptions to AnaxiGraph's external index. Start "
    "with ANAXIGRAPH_GUIDE intent=understand, build, improve, redesign, or reassess. Use "
    "ANAXIGRAPH_IMPACT before changing shared behavior. After a coherent edit, call "
    "ANAXIGRAPH_SCAN with refresh_semantics=true, finish the prepared AI work when any remains, "
    "then call ANAXIGRAPH_GUIDE with intent=reassess (reassess=true remains accepted); it "
    "compares the last compatible saved map, explains improvement or regression, and never edits "
    "source or creates approval state. Use ANAXIGRAPH_FILE for the "
    "full saved description of one file. The results distinguish facts read directly from code "
    "from AI explanations. Findings and pattern advice explain what to check; they do not order "
    "you to refactor."
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
