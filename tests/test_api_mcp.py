from __future__ import annotations

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from codeintel.api import create_app
from codeintel.mcp_server import create_anaxi_mcp_server, create_mcp_server
from codeintel.scanner import RepositoryScanner


@pytest.mark.anyio
async def test_dashboard_rest_api_exposes_current_intelligence(
    repository, database, tmp_path
):
    RepositoryScanner(database).scan(repository)
    stale_repository = tmp_path / "stale-repository"
    stale_repository.mkdir()
    (stale_repository / "old.py").write_text("legacy = True\n", encoding="utf-8")
    RepositoryScanner(database).scan(stale_repository)
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        assert (await client.get("/healthz")).json() == {"status": "ok"}
        assert (await client.get("/")).status_code == 200
        repositories = (await client.get("/api/repositories")).json()
        assert repositories[0]["scannable"] is True
        assert [row["path"] for row in repositories] == [str(repository.resolve())]
        stale_row = database.repository(stale_repository)
        assert stale_row is not None
        stale_overview = await client.get(
            "/api/overview", params={"repository_id": stale_row["id"]}
        )
        assert stale_overview.status_code == 404
        glossary = (await client.get("/api/glossary")).json()
        assert "persistent repository knowledge store" in glossary["product"]["anaxi_index"]
        assert glossary["findings"]["statuses"]["planned"]["label"] == "Planned for agent"
        overview = (await client.get("/api/overview")).json()
        assert overview["files"] == 10
        assert overview["group_hierarchy"]
        graph = (await client.get("/api/graph")).json()
        assert graph["nodes"]
        scope = await client.post(
            "/api/agent-scope", json={"goal": "Change Calculator behavior"}
        )
        assert scope.status_code == 200
        assert scope.json()["primary_files"][0]["path"] == "pkg/core.py"

        finding = (await client.get("/api/findings")).json()[0]
        planned = await client.post(
            f"/api/findings/{finding['id']}/status",
            json={"status": "planned"},
        )
        assert planned.status_code == 200
        context_response = await client.get(f"/api/findings/{finding['id']}/context")
        assert context_response.status_code == 200, context_response.text
        context = context_response.json()
        assert context["ready_for_agent"] is True
        assert "CODEINTEL_FINDING_CONTEXT" in context["agent_prompt"]
        assert context["verification"]


@pytest.mark.anyio
async def test_streamable_http_mcp_is_compatible_with_maxos_client_contract(repository, database):
    assert create_mcp_server is create_anaxi_mcp_server
    stats = RepositoryScanner(database).scan(repository)
    finding_id = database.findings(stats.repository_id)[0]["id"]
    database.update_finding_status(stats.repository_id, finding_id, "planned")
    server = create_mcp_server(
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
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    assert {
                        "CODEINTEL_OVERVIEW",
                        "CODEINTEL_SEARCH",
                        "CODEINTEL_FILE",
                        "CODEINTEL_SCOPE",
                        "CODEINTEL_IMPACT",
                        "CODEINTEL_FINDINGS",
                        "CODEINTEL_FINDING_CONTEXT",
                        "CODEINTEL_GUIDE",
                    } <= names
                    overview = await session.call_tool("CODEINTEL_OVERVIEW", arguments={})
                    assert overview.isError is False
                    assert overview.structuredContent["files"] == 10
                    guide = await session.call_tool(
                        "CODEINTEL_GUIDE", arguments={"topic": "findings"}
                    )
                    assert guide.isError is False
                    assert guide.structuredContent["findings"]["statuses"]["planned"]["label"]
                    scope = await session.call_tool(
                        "CODEINTEL_SCOPE",
                        arguments={"goal": "Change Calculator behavior"},
                    )
                    assert scope.isError is False
                    assert scope.structuredContent["primary_files"][0]["path"] == "pkg/core.py"
                    finding_context = await session.call_tool(
                        "CODEINTEL_FINDING_CONTEXT",
                        arguments={"finding_id": finding_id},
                    )
                    assert finding_context.isError is False
                    assert finding_context.structuredContent["ready_for_agent"] is True
