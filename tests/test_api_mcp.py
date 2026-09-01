from __future__ import annotations

import time

import anyio
import httpx
import pytest
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

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
        assert (await client.get("/assets/journey-navigation.css")).status_code == 200
        assert (await client.get("/assets/patterns-view.js")).status_code == 200
        assert (await client.get("/assets/patterns-render.js")).status_code == 200
        assert (await client.get("/assets/patterns.css")).status_code == 200
        assert (await client.get("/assets/themes.css")).status_code == 200
        repositories = (await client.get("/api/repositories")).json()
        assert repositories[0]["scannable"] is True
        assert repositories[0]["map_status"]["state"] == "current"
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
        assert "saved index" in glossary["product"]["anaxi_index"]
        assert "direct code links" in glossary["product"]["anaxi_index"]
        assert set(glossary["architecture"]) >= {
            "current_view",
            "declared_map",
            "responsibility_map",
            "path_map",
        }
        assert glossary["findings"]["statuses"]["planned"]["label"] == "Planned for agent"
        overview = (await client.get("/api/overview")).json()
        assert overview["files"] == 8
        assert overview["map_status"]["state"] == "current"
        assert overview["group_hierarchies"]["current"]
        assert overview["map"]["default_layer"] == "current"
        assert "declared" in overview["map"]["available_layers"]
        assert overview["group_hierarchies"]["declared"]
        charter = overview["architecture_charter"]
        assert charter["contract_version"] == "architecture-charter-v1"
        assert charter["state"] == "provisional"
        assert charter["complete"] is False
        assert charter["responsibilities"]
        assert charter["unknowns"]
        assert overview["graph_quality"]["resolution_rate"] == 1.0
        assert overview["coverage"]["state"] == "imported"
        assert overview["coverage"]["required"] is False
        assert overview["coverage"]["configured_inputs"] == [
            {"path": "coverage.xml", "exists": True, "format": "xml"}
        ]
        assert overview["semantic"]["enabled"] is False
        semantic = (await client.get("/api/semantic")).json()
        assert semantic["plain_language"]["version"] == "semantic-status-explanation-v2"
        assert semantic["map_status"]["state"] == "current"
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
        assert findings[0]["plain_language"]["version"] == "plain-language-v2"
        assert "not a grade for the code" in findings[0]["plain_language"]["priority"]["meaning"]
        modules = (await client.get("/api/modules")).json()
        assert len(modules) == 8
        core = next(item for item in modules if item["path"] == "pkg/core.py")
        assert core["architecture_area"] == "domain"
        assert core["evaluation"]["monitored_by_default"] is True
        assert core["evaluation"]["suitability_score"] is None
        assert "not a grade for the code" in core["evaluation"]["attention_score_meaning"]
        documentation = next(item for item in modules if item["path"] == "docs/architecture.md")
        assert documentation["evaluation"]["monitored_by_default"] is False
        assert documentation["evaluation"]["attention_score"] is None
        search = (await client.get("/api/search", params={"q": "Calculator", "limit": 5})).json()
        assert search["results"][0]["path"] == "pkg/core.py"
        assert search["results"][0]["search"]["contract_version"] == "module-search-fts-v1"
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
        scope = await client.post(
            "/api/guidance",
            json={"goal": "Change Calculator behavior", "intent": "build"},
        )
        assert scope.status_code == 200
        assert scope.json()["map_status"]["state"] == "current"
        assert scope.json()["primary_files"][0]["path"] == "pkg/core.py"
        assert scope.json()["primary_files"][0]["path"] == search["results"][0]["path"]
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
        assert context["finding_history"]["contract_version"] == "finding-history-v1"
        assert context["finding_history"]["status"] == "current_frame_only"


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
        allow_scan_tool=True,
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
                        "ANAXIGRAPH_REPOSITORIES",
                        "ANAXIGRAPH_OVERVIEW",
                        "ANAXIGRAPH_SEMANTIC_STATUS",
                        "ANAXIGRAPH_SEARCH",
                        "ANAXIGRAPH_FILE",
                        "ANAXIGRAPH_GUIDE",
                        "ANAXIGRAPH_IMPACT",
                        "ANAXIGRAPH_FINDINGS",
                        "ANAXIGRAPH_FINDING_CONTEXT",
                        "ANAXIGRAPH_SCAN",
                    }
                    assert len(names) <= 10
                    descriptions = {tool.name: str(tool.description or "") for tool in tools.tools}
                    public_help = " ".join(descriptions.values()).lower()
                    for unexplained_term in (
                        "bounded",
                        "dossier",
                        "taxonomy",
                        "deterministically",
                        "diagnostic ledger",
                    ):
                        assert unexplained_term not in public_help
                    assert "refresh guidance" in descriptions["ANAXIGRAPH_GUIDE"]
                    assert "ordinary sentences" in descriptions["ANAXIGRAPH_FINDINGS"]
                    overview = await session.call_tool("ANAXIGRAPH_OVERVIEW", arguments={})
                    assert overview.isError is False
                    assert overview.structuredContent["files"] == 8
                    assert overview.structuredContent["map_status"]["state"] == "current"
                    charter = overview.structuredContent["architecture_charter"]
                    assert charter["contract_version"] == "architecture-charter-v1"
                    assert charter["state"] == "provisional"
                    assert charter["identity"]
                    semantic = await session.call_tool("ANAXIGRAPH_SEMANTIC_STATUS", arguments={})
                    assert semantic.isError is False
                    assert semantic.structuredContent["enabled"] is False
                    assert semantic.structuredContent["semantic_policy"]["enabled"] is False
                    assert (
                        semantic.structuredContent["config_authority"]["source_kind"]
                        == "repository_policy"
                    )
                    search = await session.call_tool(
                        "ANAXIGRAPH_SEARCH",
                        arguments={"query": "Calculator", "limit": 5},
                    )
                    assert search.isError is False
                    assert search.structuredContent["results"][0]["path"] == "pkg/core.py"
                    assert (
                        search.structuredContent["results"][0]["search"]["contract_version"]
                        == "module-search-fts-v1"
                    )
                    guidance = await session.call_tool(
                        "ANAXIGRAPH_GUIDE",
                        arguments={"goal": "Change Calculator behavior"},
                    )
                    assert guidance.isError is False
                    assert guidance.structuredContent["primary_files"][0]["path"] == "pkg/core.py"
                    assert (
                        guidance.structuredContent["primary_files"][0]["path"]
                        == search.structuredContent["results"][0]["path"]
                    )
                    assert guidance.structuredContent["architecture_decision"]["snapshot_id"] > 0
                    refreshed = await session.call_tool("ANAXIGRAPH_SCAN", arguments={})
                    assert refreshed.isError is False
                    assert refreshed.structuredContent["repository_id"] == stats.repository_id
                    finding_context = await session.call_tool(
                        "ANAXIGRAPH_FINDING_CONTEXT",
                        arguments={"finding_id": finding_id},
                    )
                    assert finding_context.isError is False
                    assert finding_context.structuredContent["ready_for_agent"] is True
                    assert (
                        finding_context.structuredContent["finding_history"]["contract_version"]
                        == "finding-history-v1"
                    )
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
                    assert language["version"] == "plain-language-v2"


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
