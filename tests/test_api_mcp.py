from __future__ import annotations

import httpx
import pytest
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from anaxigraph.api import create_app
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner


@pytest.mark.anyio
async def test_dashboard_rest_api_exposes_current_intelligence(
    repository, database, tmp_path
):
    RepositoryScanner(database).scan(repository)
    stale_repository = tmp_path / "stale-repository"
    stale_repository.mkdir()
    (stale_repository / "old.py").write_text("stale = True\n", encoding="utf-8")
    RepositoryScanner(database).scan(stale_repository)
    app = create_app(
        database=database,
        repository=repository,
        enable_mcp=False,
        repository_history_snapshots=23,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        assert (await client.get("/healthz")).json() == {"status": "ok"}
        assert (await client.get("/")).status_code == 200
        repositories = (await client.get("/api/repositories")).json()
        assert repositories[0]["scannable"] is True
        assert repositories[0]["history_snapshots"] == 23
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
        assert overview["files"] == 9
        assert overview["group_hierarchy"]
        assert overview["graph_quality"]["resolution_rate"] == 1.0
        assert overview["coverage"]["state"] == "imported"
        assert overview["coverage"]["required"] is False
        assert overview["coverage"]["configured_inputs"] == [
            {"path": "coverage.xml", "exists": True, "format": "xml"}
        ]
        assert overview["semantic"]["enabled"] is False
        semantic = (await client.get("/api/semantic")).json()
        assert semantic["state"] == "not_started"
        disabled_refresh = await client.post("/api/semantic/refresh")
        assert disabled_refresh.status_code == 400
        findings = (await client.get("/api/findings")).json()
        assert findings[0]["priority_score"] >= findings[-1]["priority_score"]
        assert findings[0]["priority_reasons"]
        modules = (await client.get("/api/modules")).json()
        assert len(modules) == 9
        core = next(item for item in modules if item["path"] == "pkg/core.py")
        assert core["architecture_area"] == "domain"
        assert core["evaluation"]["monitored_by_default"] is True
        assert core["evaluation"]["suitability_score"] is None
        documentation = next(
            item for item in modules if item["path"] == "docs/architecture.md"
        )
        assert documentation["evaluation"]["monitored_by_default"] is False
        assert documentation["evaluation"]["attention_score"] is None
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
        assert "ANAXIGRAPH_FINDING_CONTEXT" in context["agent_prompt"]
        assert context["verification"]


@pytest.mark.anyio
async def test_streamable_http_mcp_exposes_anaxigraph_tools(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    finding_id = database.findings(stats.repository_id)[0]["id"]
    database.update_finding_status(stats.repository_id, finding_id, "planned")
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
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    assert {
                        "ANAXIGRAPH_OVERVIEW",
                        "ANAXIGRAPH_SEMANTIC_STATUS",
                        "ANAXIGRAPH_SEMANTIC_SCHEMA",
                        "ANAXIGRAPH_SEMANTIC_WORK",
                        "ANAXIGRAPH_SEMANTIC_EVIDENCE",
                        "ANAXIGRAPH_SEMANTIC_SUBMIT",
                        "ANAXIGRAPH_SEMANTIC_RELEASE",
                        "ANAXIGRAPH_MODULES",
                        "ANAXIGRAPH_SEARCH",
                        "ANAXIGRAPH_FILE",
                        "ANAXIGRAPH_SCOPE",
                        "ANAXIGRAPH_IMPACT",
                        "ANAXIGRAPH_FINDINGS",
                        "ANAXIGRAPH_FINDING_CONTEXT",
                        "ANAXIGRAPH_GUIDE",
                    } <= names
                    submit_tool = next(
                        tool for tool in tools.tools if tool.name == "ANAXIGRAPH_SEMANTIC_SUBMIT"
                    )
                    assert submit_tool.annotations.readOnlyHint is False
                    overview = await session.call_tool("ANAXIGRAPH_OVERVIEW", arguments={})
                    assert overview.isError is False
                    assert overview.structuredContent["files"] == 9
                    semantic = await session.call_tool(
                        "ANAXIGRAPH_SEMANTIC_STATUS", arguments={}
                    )
                    assert semantic.isError is False
                    assert semantic.structuredContent["enabled"] is False
                    schema = await session.call_tool(
                        "ANAXIGRAPH_SEMANTIC_SCHEMA", arguments={}
                    )
                    assert schema.isError is False
                    assert schema.structuredContent["schema_version"] == "module-dossier-v4"
                    modules = await session.call_tool(
                        "ANAXIGRAPH_MODULES", arguments={"language": "python", "limit": 3}
                    )
                    assert modules.isError is False
                    assert modules.structuredContent["total"] >= 3
                    assert len(modules.structuredContent["modules"]) == 3
                    guide = await session.call_tool(
                        "ANAXIGRAPH_GUIDE", arguments={"topic": "findings"}
                    )
                    assert guide.isError is False
                    assert guide.structuredContent["findings"]["statuses"]["planned"]["label"]
                    scope = await session.call_tool(
                        "ANAXIGRAPH_SCOPE",
                        arguments={"goal": "Change Calculator behavior"},
                    )
                    assert scope.isError is False
                    assert scope.structuredContent["primary_files"][0]["path"] == "pkg/core.py"
                    finding_context = await session.call_tool(
                        "ANAXIGRAPH_FINDING_CONTEXT",
                        arguments={"finding_id": finding_id},
                    )
                    assert finding_context.isError is False
                    assert finding_context.structuredContent["ready_for_agent"] is True


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
                            "dossier": _mcp_dossier(packet["job"]["scope_key"]),
                        },
                    )
                    assert submit.isError is False
                    assert submit.structuredContent["status"] == "completed"

    with database.connect() as connection:
        row = connection.execute(
            "SELECT source, provider, executor_id FROM semantic_documents"
        ).fetchone()
    assert tuple(row) == ("coding_agent", "agent", "codex-integration")


def _mcp_dossier(scope: str) -> dict:
    return {
        "summary": f"Agent understanding for {scope}",
        "detailed_summary": f"Evidence-grounded dossier for {scope}.",
        "responsibilities": [f"Own {scope}"],
        "inputs": [],
        "outputs": [],
        "side_effects": [],
        "public_contracts": [],
        "invariants": [],
        "architecture_role": "integration test role",
        "domain_concepts": [],
        "collaborators": [],
        "overlaps": [],
        "extension_points": [],
        "similar_modules": [],
        "pattern_opportunities": [],
        "consolidation_assessment": {
            "recommendation": "insufficient_evidence",
            "score": 0,
            "rationale": "",
            "candidates": [],
            "evidence": [],
            "counter_evidence": [],
        },
        "dead_code_candidates": [],
        "placement_guidance": "",
        "testing_guidance": [],
        "change_summary": "",
        "risks": [],
        "evidence": [scope],
        "confidence": 0.9,
    }
