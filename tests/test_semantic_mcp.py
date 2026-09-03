from __future__ import annotations

import httpx
import pytest
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from semantic_support import _agent_dossier

from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner


async def _claim_and_submit(
    session: ClientSession,
    usage: dict[str, int],
    *,
    agent_effort: str = "",
) -> dict:
    """Claim one job and submit it with exactly the usage arguments the caller named."""

    work = await session.call_tool(
        "ANAXIGRAPH_SEMANTIC_WORK",
        arguments={
            "agent_id": "codex-integration",
            "agent_model": "test",
            "agent_effort": agent_effort,
        },
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
            **usage,
        },
    )
    assert submit.isError is False
    return submit.structuredContent


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
        profile="executor",
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
                    assert names == {
                        "ANAXIGRAPH_SEMANTIC_STATUS",
                        "ANAXIGRAPH_SEMANTIC_SCHEMA",
                        "ANAXIGRAPH_SEMANTIC_WORK",
                        "ANAXIGRAPH_SEMANTIC_EVIDENCE",
                        "ANAXIGRAPH_SEMANTIC_SUBMIT",
                        "ANAXIGRAPH_SEMANTIC_RELEASE",
                        "ANAXIGRAPH_SEMANTIC_FAIL",
                    }
                    submit_tool = next(
                        tool for tool in tools.tools if tool.name == "ANAXIGRAPH_SEMANTIC_SUBMIT"
                    )
                    assert submit_tool.annotations.readOnlyHint is False
                    silent = await _claim_and_submit(session, {})
                    assert silent["status"] == "completed"
                    reported = await _claim_and_submit(
                        session,
                        {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cache_read_input_tokens": 12,
                            "cache_creation_input_tokens": 3,
                        },
                        agent_effort="medium",
                    )
                    assert reported["status"] == "completed"

    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT source, provider, executor_id, executor_effort, file_fact_id, usage_source,
                   cache_read_input_tokens, cache_creation_input_tokens
            FROM semantic_documents ORDER BY id
            """
        ).fetchall()
    assert tuple(rows[0])[:3] == ("coding_agent", "agent", "codex-integration")
    assert rows[0]["file_fact_id"] is not None
    # An agent that names no token counts is unknown usage, never a reported zero.
    assert rows[0]["usage_source"] == "unknown"
    assert rows[0]["executor_effort"] is None
    assert rows[1]["usage_source"] == "reported"
    assert rows[1]["executor_effort"] == "medium"
    assert rows[1]["cache_read_input_tokens"] == 12
    assert rows[1]["cache_creation_input_tokens"] == 3


@pytest.mark.anyio
async def test_mcp_refuses_to_claim_semantic_work_from_a_stale_map(repository, database):
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent"}
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    RepositoryScanner(database).scan(repository)
    core = repository / "pkg" / "core.py"
    core.write_text(core.read_text(encoding="utf-8") + "\nCHANGED = True\n", encoding="utf-8")
    server = create_anaxi_mcp_server(
        database=database,
        repository=repository,
        config_path=None,
        allowed_hosts=["testserver"],
        profile="executor",
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
                        arguments={"agent_id": "stale-map-agent"},
                    )

    assert work.isError is False
    assert work.structuredContent["status"] == "scan_required"
    assert work.structuredContent["map_status"]["state"] == "stale"
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_jobs").fetchone()[0] == 0
