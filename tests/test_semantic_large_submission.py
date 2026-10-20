"""A real executor HTTP submission is not cut off by the control-request byte limit."""

from __future__ import annotations

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.api import create_app
from anaxigraph.api_limits import MAX_REQUEST_BODY_BYTES
from anaxigraph.scanner import RepositoryScanner


@pytest.mark.anyio
async def test_large_valid_result_saves_through_combined_dashboard_mcp(repository, database):
    _enable_agent_semantics(repository)
    RepositoryScanner(database).scan(repository)
    app = create_app(
        database=database, repository=repository, enable_mcp=True, allowed_hosts=["testserver"]
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=10
        ) as client:
            async with streamable_http_client(
                "http://testserver/executor/mcp", http_client=client, terminate_on_close=False
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    work = await session.call_tool(
                        "ANAXIGRAPH_SEMANTIC_WORK", {"agent_id": "large-result-test"}
                    )
                    assert not work.isError
                    packet = work.structuredContent
                    dossier = _agent_dossier(packet["analysis_request"])
                    dossier["summary"] = "Valid result. " * (MAX_REQUEST_BODY_BYTES // 10)
                    assert len(dossier["summary"].encode()) > MAX_REQUEST_BODY_BYTES
                    result = await session.call_tool(
                        "ANAXIGRAPH_SEMANTIC_SUBMIT",
                        {
                            "job_id": packet["job"]["id"],
                            "lease_token": packet["lease"]["token"],
                            "dossier": dossier,
                        },
                    )
                    assert not result.isError
                    assert result.structuredContent["status"] == "completed"
            with database.connect() as connection:
                saved = connection.execute(
                    "SELECT status, attempts FROM semantic_jobs WHERE id = ?",
                    (packet["job"]["id"],),
                ).fetchone()
            assert tuple(saved) == ("completed", 1)
            # Small control endpoints retain their own explicit request boundary.
            oversized = await client.post(
                "/api/guidance", content=b"x" * (MAX_REQUEST_BODY_BYTES + 1)
            )
            assert oversized.status_code == 413
