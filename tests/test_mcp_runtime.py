from __future__ import annotations

import asyncio
import threading
import time

import pytest
from mcp.server.fastmcp.server import Settings as FastMCPSettings
from mcp.types import CallToolResult

from anaxigraph.mcp_runtime import ResponsiveFastMCP


@pytest.mark.anyio
async def test_synchronous_tool_does_not_block_the_server_event_loop():
    FastMCPSettings.model_rebuild()
    server = ResponsiveFastMCP("responsive-test")
    entered = threading.Event()
    release = threading.Event()

    @server.tool(name="BLOCKING_TEST")
    def blocking_test() -> dict[str, bool]:
        entered.set()
        assert release.wait(timeout=2)
        return {"complete": True}

    started = time.monotonic()
    task = asyncio.create_task(server.call_tool("BLOCKING_TEST", {}))
    assert await asyncio.to_thread(entered.wait, 0.25)
    assert time.monotonic() - started < 0.25

    release.set()
    result = await task
    assert result[1] == {"complete": True}


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["ANAXIGRAPH_GUIDE", "ANAXIGRAPH_IMPACT"])
async def test_agent_results_do_not_duplicate_structured_json_in_text(name):
    FastMCPSettings.model_rebuild()
    server = ResponsiveFastMCP("compact-test")
    payload = {
        "plain_language": {"conclusion": "Start with the direct users."},
        "evidence": ["Saved architecture context. " * 500],
    }

    def result() -> dict:
        return payload

    server.add_tool(result, name=name)
    response = await server.call_tool(name, {})
    assert isinstance(response, CallToolResult)
    assert response.structuredContent == payload
    assert response.content[0].text == "Start with the direct users."
    assert len(response.content[0].text) < 100
