from __future__ import annotations

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from anaxigraph.api import create_app
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner


@pytest.mark.anyio
async def test_rest_scope_accepts_its_previous_verification_baseline(repository, database):
    RepositoryScanner(database).scan(repository)
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first = await client.post("/api/agent-scope", json={"goal": "Change Calculator behavior"})
        baseline = first.json()["architecture_decision"]["verification"]
        second = await client.post(
            "/api/agent-scope",
            json={
                "goal": "Change Calculator behavior",
                "verification_baseline": baseline,
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    comparison = second.json()["architecture_decision"]["verification"]["post_change_comparison"]
    assert comparison["status"] == "rescan_required"


@pytest.mark.anyio
async def test_mcp_scope_accepts_its_previous_verification_baseline(repository, database):
    RepositoryScanner(database).scan(repository)
    server = create_anaxi_mcp_server(
        database=database,
        repository=repository,
        config_path=None,
        allowed_hosts=["testserver"],
    )
    app = server.streamable_http_app()

    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            timeout=5,
        ) as http_client:
            async with streamable_http_client(
                "http://testserver/mcp",
                http_client=http_client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    first = await session.call_tool(
                        "ANAXIGRAPH_SCOPE",
                        arguments={"goal": "Change Calculator behavior"},
                    )
                    baseline = first.structuredContent["architecture_decision"]["verification"]
                    second = await session.call_tool(
                        "ANAXIGRAPH_SCOPE",
                        arguments={
                            "goal": "Change Calculator behavior",
                            "verification_baseline": baseline,
                        },
                    )

    assert first.isError is False
    assert second.isError is False
    comparison = second.structuredContent["architecture_decision"]["verification"][
        "post_change_comparison"
    ]
    assert comparison["status"] == "rescan_required"
