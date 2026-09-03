"""Call AnaxiMCP tools for the remote worker and wait out sidecar writer contention."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

from mcp import ClientSession

MCP_TOOL_TIMEOUT_SECONDS = 60
_LOCK_RETRY_ATTEMPTS = 6
_LOCKED_MARKER = "database is locked"


async def call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
    """Call one AnaxiMCP tool with a bounded wait."""
    try:
        return await asyncio.wait_for(
            session.call_tool(
                name,
                arguments=arguments,
                read_timeout_seconds=timedelta(seconds=MCP_TOOL_TIMEOUT_SECONDS),
            ),
            timeout=MCP_TOOL_TIMEOUT_SECONDS + 1,
        )
    except TimeoutError as exc:
        raise RuntimeError(
            f"AnaxiMCP tool {name} exceeded {MCP_TOOL_TIMEOUT_SECONDS} seconds"
        ) from exc


async def call_tool_retrying_locks(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
    *,
    action: str,
    attempts: int = _LOCK_RETRY_ATTEMPTS,
) -> dict[str, Any]:
    """Call a write-back tool, backing off while another writer holds the sidecar index."""
    for attempt in range(attempts - 1):
        try:
            return tool_value(await call_tool(session, name, arguments), action)
        except RuntimeError as exc:
            if not _is_lock_error(exc):
                raise
            await asyncio.sleep(2**attempt)
    return tool_value(await call_tool(session, name, arguments), action)


def tool_value(result: Any, action: str) -> dict[str, Any]:
    """Return a tool's structured result, or raise its error text as a RuntimeError."""
    if result.isError:
        message = " ".join(
            str(getattr(item, "text", "")) for item in result.content if getattr(item, "text", "")
        )
        raise RuntimeError(f"AnaxiMCP could not {action}: {message[:1_000]}")
    value = result.structuredContent
    if isinstance(value, dict):
        return value
    for item in result.content:
        text = getattr(item, "text", "")
        if text:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    raise RuntimeError(f"AnaxiMCP returned no structured result while trying to {action}")


def _is_lock_error(error: BaseException) -> bool:
    return _LOCKED_MARKER in str(error).lower()
