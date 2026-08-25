from __future__ import annotations

import httpx
import pytest
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from semantic_support import _agent_dossier

from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner


@pytest.mark.anyio
async def test_mcp_coding_agent_can_claim_and_submit_semantic_work(repository, database):
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {
        "enabled": True,
        "provider": "agent",
        "agent_lease_seconds": 120,
    }
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
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
                    work = await session.call_tool(
                        "ANAXIGRAPH_SEMANTIC_WORK",
                        arguments={"agent_id": "codex-integration", "agent_model": "test"},
                    )
                    assert work.isError is False
                    packet = work.structuredContent
                    assert packet["status"] == "work"
                    submit = await session.call_tool(
                        "ANAXIGRAPH_SEMANTIC_SUBMIT",
                        arguments={
                            "job_id": packet["job"]["id"],
                            "lease_token": packet["lease"]["token"],
                            "dossier": _agent_dossier(packet["analysis_request"]),
                        },
                    )
                    assert submit.isError is False
                    assert submit.structuredContent["status"] == "completed"

    with database.connect() as connection:
        row = connection.execute(
            "SELECT source, provider, executor_id, file_fact_id FROM semantic_documents"
        ).fetchone()
    assert tuple(row)[:3] == ("coding_agent", "agent", "codex-integration")
    assert row["file_fact_id"] is not None
