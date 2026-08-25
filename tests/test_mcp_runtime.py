from __future__ import annotations

import asyncio
import threading
import time

import pytest
from mcp.server.fastmcp.server import Settings as FastMCPSettings

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
