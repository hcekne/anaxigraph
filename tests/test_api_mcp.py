from __future__ import annotations

import time

import anyio
import httpx
import pytest
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from semantic_support import _agent_dossier

from anaxigraph import git
from anaxigraph.api import create_app
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner


@pytest.mark.anyio
async def test_dashboard_rest_api_exposes_current_intelligence(repository, database, tmp_path):
    RepositoryScanner(database).scan(repository)
    stale_repository = tmp_path / "stale-repository"
    stale_repository.mkdir()
    (stale_repository / "old.py").write_text("stale = True\n", encoding="utf-8")
    RepositoryScanner(database).scan(stale_repository)
    app = create_app(
        database=database,
        repository=repository,
        enable_mcp=False,
        repository_history_snapshots="auto",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        assert (await client.get("/healthz")).json() == {"status": "ok"}
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/assets/findings-view.js")).status_code == 200
        assert (await client.get("/assets/dashboard-core.js")).status_code == 200
        assert (await client.get("/assets/graph-regions.js")).status_code == 200
        assert (await client.get("/assets/graph-regions.css")).status_code == 200
        assert (await client.get("/assets/patterns-view.js")).status_code == 200
        assert (await client.get("/assets/patterns-render.js")).status_code == 200
        assert (await client.get("/assets/patterns.css")).status_code == 200
        assert (await client.get("/assets/themes.css")).status_code == 200
        repositories = (await client.get("/api/repositories")).json()
        assert repositories[0]["scannable"] is True
        assert repositories[0]["history_snapshots"] == "auto"
        assert [row["path"] for row in repositories] == [str(repository.resolve())]
        assert repositories[0]["config_authority"]["source_kind"] == "repository_policy"
        assert repositories[0]["config_authority"]["sha256"]
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
        assert overview["files"] == 8
        assert overview["group_hierarchy"]
        assert overview["map"]["default_layer"] == "effective"
        assert "policy" in overview["map"]["available_layers"]
        policy_groups = (await client.get("/api/groups", params={"layer": "policy"})).json()
        assert policy_groups["layer"] == "policy"
        assert policy_groups["groups"]
        assert overview["graph_quality"]["resolution_rate"] == 1.0
        assert overview["coverage"]["state"] == "imported"
        assert overview["coverage"]["required"] is False
        assert overview["coverage"]["configured_inputs"] == [
            {"path": "coverage.xml", "exists": True, "format": "xml"}
        ]
        assert overview["semantic"]["enabled"] is False
        semantic = (await client.get("/api/semantic")).json()
        assert semantic["state"] == "not_started"
        assert semantic["recommended_action"]["kind"] == "enable_semantics"
        assert semantic["semantic_policy"] == repositories[0]["semantic_policy"]
        assert semantic["config_authority"] == repositories[0]["config_authority"]
        assert (await client.get("/api/taxonomy")).status_code == 404
        disabled_refresh = await client.post("/api/semantic/refresh")
        assert disabled_refresh.status_code == 400
        attention = (await client.get("/api/findings")).json()
        assert attention["view"] == "attention"
        assert attention["shown"] <= 20
        assert attention["total_matching"] == 0
        diagnostic_page = (await client.get("/api/findings", params={"view": "diagnostics"})).json()
        findings = diagnostic_page["items"]
        assert findings[0]["priority_score"] >= findings[-1]["priority_score"]
        assert findings[0]["priority_reasons"]
        assert findings[0]["actionability"]["verification"]
        assert findings[0]["plain_language"]["version"] == "plain-language-v1"
        assert "not a grade for the code" in findings[0]["plain_language"]["priority"]["meaning"]
        modules = (await client.get("/api/modules")).json()
        assert len(modules) == 8
        core = next(item for item in modules if item["path"] == "pkg/core.py")
        assert core["architecture_area"] == "domain"
        assert core["evaluation"]["monitored_by_default"] is True
        assert core["evaluation"]["suitability_score"] is None
        documentation = next(item for item in modules if item["path"] == "docs/architecture.md")
        assert documentation["evaluation"]["monitored_by_default"] is False
        assert documentation["evaluation"]["attention_score"] is None
        graph = (await client.get("/api/graph")).json()
        assert graph["nodes"]
        patterns = (await client.get("/api/patterns")).json()
        assert patterns["contract_version"] == "pattern-query-v1"
        assert patterns["snapshot_id"] > 0
        assert patterns["total"] == 0
        candidates = (
            await client.get(
                "/api/patterns/candidates",
                params={"pattern": "circular-dependency", "limit": 1},
            )
        ).json()
        assert candidates["contract_version"] == "pattern-candidate-query-v1"
        assert candidates["plan_ready"] is False
        assert candidates["returned"] <= 1
        invalid_candidates = await client.get(
            "/api/patterns/candidates", params={"pattern": "not-a-catalog-card"}
        )
        assert invalid_candidates.status_code == 400
        invalid_pattern_query = await client.get(
            "/api/patterns", params={"sort_by": "unbounded_magic"}
        )
        assert invalid_pattern_query.status_code == 400
        scope = await client.post("/api/agent-scope", json={"goal": "Change Calculator behavior"})
        assert scope.status_code == 200
        assert scope.json()["primary_files"][0]["path"] == "pkg/core.py"
        assert (
            scope.json()["architecture_decision"]["contract_version"] == "architecture-decision-v1"
        )

        finding = diagnostic_page["items"][0]
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
                        "ANAXIGRAPH_HISTORY_STATUS",
                        "ANAXIGRAPH_HISTORY_IMPORT",
                        "ANAXIGRAPH_HISTORY_CANCEL",
                        "ANAXIGRAPH_SEMANTIC_STATUS",
                        "ANAXIGRAPH_TAXONOMY",
                        "ANAXIGRAPH_SEMANTIC_SCHEMA",
                        "ANAXIGRAPH_SEMANTIC_WORK",
                        "ANAXIGRAPH_SEMANTIC_EVIDENCE",
                        "ANAXIGRAPH_SEMANTIC_SUBMIT",
                        "ANAXIGRAPH_SEMANTIC_RELEASE",
                        "ANAXIGRAPH_MODULES",
                        "ANAXIGRAPH_GRAPH",
                        "ANAXIGRAPH_PATTERNS",
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
                    assert overview.structuredContent["files"] == 8
                    graph = await session.call_tool("ANAXIGRAPH_GRAPH", arguments={})
                    assert graph.isError is False
                    assert graph.structuredContent["contract_version"] == "graph-overview-v1"
                    graph_delta = await session.call_tool(
                        "ANAXIGRAPH_GRAPH",
                        arguments={
                            "mode": "delta",
                            "baseline_snapshot_id": stats.snapshot_id,
                        },
                    )
                    assert graph_delta.isError is False
                    assert graph_delta.structuredContent["contract_version"] == "graph-delta-v1"
                    graph_page = await session.call_tool(
                        "ANAXIGRAPH_GRAPH",
                        arguments={
                            "mode": "page",
                            "node_limit": 3,
                            "edge_limit": 4,
                            "language": ["python"],
                        },
                    )
                    assert graph_page.isError is False
                    assert graph_page.structuredContent["contract_version"] == "graph-query-v1"
                    assert len(graph_page.structuredContent["nodes"]) <= 3
                    graph_neighbors = await session.call_tool(
                        "ANAXIGRAPH_GRAPH",
                        arguments={
                            "mode": "neighbors",
                            "node": "pkg/core.py",
                            "depth": 1,
                            "direction": "both",
                            "relationship": ["imports"],
                        },
                    )
                    assert graph_neighbors.isError is False
                    assert (
                        graph_neighbors.structuredContent["contract_version"]
                        == "graph-neighborhood-v1"
                    )
                    missing_delta = await session.call_tool(
                        "ANAXIGRAPH_GRAPH", arguments={"mode": "delta"}
                    )
                    invalid_mode = await session.call_tool(
                        "ANAXIGRAPH_GRAPH", arguments={"mode": "everything"}
                    )
                    assert missing_delta.isError is True
                    assert invalid_mode.isError is True
                    patterns = await session.call_tool("ANAXIGRAPH_PATTERNS", arguments={})
                    assert patterns.isError is False
                    assert patterns.structuredContent["contract_version"] == "pattern-query-v1"
                    assert patterns.structuredContent["total"] == 0
                    invalid_patterns = await session.call_tool(
                        "ANAXIGRAPH_PATTERNS", arguments={"limit": 101}
                    )
                    assert invalid_patterns.isError is True
                    candidate_explanations = await session.call_tool(
                        "ANAXIGRAPH_PATTERNS",
                        arguments={
                            "mode": "candidates",
                            "pattern": "circular-dependency",
                            "limit": 1,
                        },
                    )
                    assert candidate_explanations.isError is False
                    assert (
                        candidate_explanations.structuredContent["contract_version"]
                        == "pattern-candidate-query-v1"
                    )
                    history = await session.call_tool("ANAXIGRAPH_HISTORY_STATUS", arguments={})
                    assert history.isError is False
                    assert history.structuredContent["status"] == "not_started"
                    semantic = await session.call_tool("ANAXIGRAPH_SEMANTIC_STATUS", arguments={})
                    assert semantic.isError is False
                    assert semantic.structuredContent["enabled"] is False
                    assert semantic.structuredContent["semantic_policy"]["enabled"] is False
                    assert (
                        semantic.structuredContent["config_authority"]["source_kind"]
                        == "repository_policy"
                    )
                    schema = await session.call_tool("ANAXIGRAPH_SEMANTIC_SCHEMA", arguments={})
                    assert schema.isError is False
                    assert (
                        schema.structuredContent["schema_version"] == "repository-understanding-v5"
                    )
                    assert schema.structuredContent["taxonomy_schema"]["type"] == "object"
                    assert schema.structuredContent["taxonomy_review_schema"]["type"] == "object"
                    assert schema.structuredContent["pattern_evaluation_schema"]["type"] == "object"
                    assert schema.structuredContent["pattern_review_schema"]["type"] == "object"
                    taxonomy = await session.call_tool("ANAXIGRAPH_TAXONOMY", arguments={})
                    assert taxonomy.isError is False
                    assert taxonomy.structuredContent["status"] == "not_ready"
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
                    assert scope.structuredContent["architecture_decision"]["snapshot_id"] > 0
                    finding_context = await session.call_tool(
                        "ANAXIGRAPH_FINDING_CONTEXT",
                        arguments={"finding_id": finding_id},
                    )
                    assert finding_context.isError is False
                    assert finding_context.structuredContent["ready_for_agent"] is True
                    findings = await session.call_tool(
                        "ANAXIGRAPH_FINDINGS",
                        arguments={
                            "view": "diagnostics",
                            "page_size": 1,
                            "token_budget": 2_000,
                        },
                    )
                    assert findings.isError is False
                    assert findings.structuredContent["shown"] == 1
                    assert findings.structuredContent["total_matching"] >= 1
                    assert findings.structuredContent["items"][0]["actionability"]
                    language = findings.structuredContent["items"][0]["plain_language"]
                    assert language["version"] == "plain-language-v1"


@pytest.mark.anyio
async def test_semantic_prepare_reconciles_current_snapshot_without_scanning(
    repository, database, monkeypatch
):
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent"}
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    RepositoryScanner(database).scan(repository)
    monkeypatch.setattr(
        "anaxigraph.api_semantic_routes.api_support.RepositoryScanner.scan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("prepare scanned source")),
    )
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/semantic/prepare",
            params={"force": True, "retry_failed": True},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "prepared"
    assert result["stage"] == "intrinsic"
    assert "scan" not in result
    assert result["semantic"]["jobs"]["pending"] > 0


@pytest.mark.anyio
async def test_semantic_prepare_reports_scan_required_without_current_snapshot(
    repository, database
):
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent"}
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    repository_id = database.ensure_repository(
        path=repository,
        name="Unscanned fixture",
        git=git.metadata(repository),
    )
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/semantic/prepare")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "scan_required"
    assert result["repository_id"] == repository_id
    assert result["recommended_action"] == (
        "Run the explicit repository scan, then retry understand."
    )
    assert result["semantic_policy"]["enabled"] is True
    assert result["config_authority"]["sha256"]


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


@pytest.mark.anyio
async def test_history_job_does_not_block_current_intelligence_and_can_cancel(
    repository, database, monkeypatch
):
    RepositoryScanner(database).scan(repository)

    def held_import(*args, job_progress, should_cancel, **kwargs):
        job_progress({"stage": "enumerated", "total_commits": 1, "total_frames": 1})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not should_cancel():
            time.sleep(0.01)
        from anaxigraph.history import HistoryImportCancelled

        raise HistoryImportCancelled("cancelled through REST")

    monkeypatch.setattr("anaxigraph.history_jobs.import_git_history", held_import)
    app = create_app(
        database=database,
        repository=repository,
        enable_mcp=False,
        repository_history_snapshots="auto",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        started = (await client.post("/api/history/import")).json()
        assert started["status"] == "started"
        for _ in range(100):
            active = (await client.get("/api/history")).json()["job"]
            if active["status"] == "importing":
                break
            await anyio.sleep(0.01)
        assert active["status"] == "importing"
        assert (await client.get("/api/modules")).status_code == 200
        assert (await client.get("/api/overview")).json()["files"] == 8

        cancellation = (await client.post("/api/history/cancel")).json()
        assert cancellation["cancelled"] is True
        for _ in range(100):
            final = (await client.get("/api/history")).json()["job"]
            if final["status"] == "cancelled":
                break
            await anyio.sleep(0.01)
        assert final["status"] == "cancelled"
        assert final["last_complete_snapshot_id"] is not None
