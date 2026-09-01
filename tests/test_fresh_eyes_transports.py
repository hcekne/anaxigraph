from __future__ import annotations

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.api import create_app
from anaxigraph.config import load_config
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def _complete_queue(engine, repository_id, repository, config) -> None:
    for index in range(500):
        packet = engine.claim_agent_work(
            repository_id,
            repository,
            config,
            agent_id=f"transport-{index}",
            agent_model="fixture-model",
        )
        if packet["status"] == "complete":
            return
        engine.submit_agent_work(
            repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=_agent_dossier(packet["analysis_request"]),
        )
    raise AssertionError("Semantic queue did not converge")


@pytest.mark.anyio
async def test_dashboard_cli_contract_and_mcp_share_one_fresh_eyes_result(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _complete_queue(engine, stats.repository_id, repository, config)
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _complete_queue(engine, stats.repository_id, repository, config)

    app = create_app(database=database, repository=repository, enable_mcp=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        rest = (await client.get("/api/fresh-eyes")).json()

    server = create_anaxi_mcp_server(
        database=database,
        repository=repository,
        config_path=None,
        allowed_hosts=["testserver"],
    )
    mcp_app = server.streamable_http_app()
    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mcp_app),
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
                    response = await session.call_tool(
                        "ANAXIGRAPH_GUIDE", arguments={"fresh_eyes": True}
                    )
                    assert response.isError is False
                    mcp = response.structuredContent

    for field in ("identity", "state", "fingerprints", "recommendations", "caveats"):
        assert mcp[field] == rest[field]
    assert rest["state"] == "current"
    assert rest["recommendations"][0]["action"] == "consolidate"
