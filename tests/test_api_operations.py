from __future__ import annotations

import json
import shutil
import threading

import anyio
import httpx
import pytest
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import anaxigraph.operational_health as operational_health
from anaxigraph.api import create_app
from anaxigraph.api_limits import MAX_REQUEST_BODY_BYTES
from anaxigraph.api_operation_gate import RepositoryOperationGate
from anaxigraph.bounded_export import _compact_taxonomy
from anaxigraph.operational_health import served_map_status
from anaxigraph.persistence.schema import SCHEMA_VERSION
from anaxigraph.registry import RepositoryTarget
from anaxigraph.scanner import RepositoryScanner, ScanCancelled


@pytest.mark.anyio
async def test_operational_api_bounds_inventory_export_and_request_bodies(repository, database):
    RepositoryScanner(database).scan(repository)
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = (await client.get("/api/modules", params={"limit": 2})).json()
        second = (await client.get("/api/modules", params={"limit": 2, "offset": 2})).json()
        unsafe = await client.get("/api/modules", params={"limit": 1_001})
        health = (await client.get("/api/health")).json()
        export = (await client.get("/api/export")).json()
        oversized = await client.post(
            "/api/guidance",
            content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
            headers={"content-type": "application/json"},
        )

    assert len(first) == len(second) == 2
    assert {item["path"] for item in first}.isdisjoint(item["path"] for item in second)
    assert unsafe.status_code == 422
    assert health["contract_version"] == "operational-health-v1"
    assert health["database"]["schema_version"] == SCHEMA_VERSION
    assert health["database"]["total_index_bytes"] > 0
    assert health["pressure"]["http_operations"]["active_count"] == 0
    assert export["contract_version"] == "anaxigraph-export-v1"
    assert export["graph"]["counts"]["page_internal_nodes"] <= 250
    assert export["graph"]["counts"]["page_edges"] <= 500
    assert export["findings"]["shown"] <= 200
    assert "group_hierarchies" not in export["overview"]
    assert oversized.status_code == 413


@pytest.mark.anyio
async def test_scan_endpoint_is_nonblocking_observable_and_cancellable(
    repository, database, monkeypatch
):
    RepositoryScanner(database).scan(repository)
    entered = threading.Event()

    def blocked_scan(_scanner, _path, *, progress, is_cancelled, **_kwargs):
        progress(
            {
                "phase": "analyzing",
                "completed": 3,
                "total": 8,
                "current_path": "pkg/core.py",
                "analysis_run_id": 42,
            }
        )
        entered.set()
        while not is_cancelled():
            threading.Event().wait(0.01)
        raise ScanCancelled("cancelled by test")

    monkeypatch.setattr("anaxigraph.api_scan.RepositoryScanner.scan", blocked_scan)
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            first = await client.post("/api/scan")
            assert entered.wait(timeout=1)
            progress = (await client.get("/api/scan")).json()
            repeated = await client.post("/api/scan")
            cancelling = (await client.post("/api/scan/cancel")).json()
            terminal = await _wait_for_scan(client, "cancelled")
            health = (await client.get("/api/health")).json()

    assert first.status_code == 202
    assert first.json()["scan_id"]
    assert progress["phase"] == "analyzing"
    assert progress["completed"] == 3
    assert progress["total"] == 8
    assert progress["current_path"] == "pkg/core.py"
    assert repeated.status_code == 409
    assert int(repeated.headers["retry-after"]) >= 1
    assert cancelling["status"] == "cancelling"
    assert terminal["active"] is False
    assert health["pressure"]["http_operations"]["active_count"] == 0


@pytest.mark.anyio
async def test_service_lifecycle_supervises_repository_watcher(repository, database):
    app = create_app(
        database=database,
        repository=repository,
        enable_mcp=False,
        watch_interval=0.2,
    )

    async with app.router.lifespan_context(app):
        first = await _wait_for_snapshot(database, repository)
        core = repository / "pkg" / "core.py"
        core.write_text(core.read_text(encoding="utf-8") + "\nWATCHED = True\n", encoding="utf-8")
        second = await _wait_for_snapshot(database, repository, after=int(first["id"]))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            health = (await client.get("/api/health")).json()

    assert int(second["id"]) > int(first["id"])
    assert health["write_authority"]["claimed"] is True
    assert health["write_authority"]["owner"] == "service"
    assert health["watcher"]["running"] is True
    assert health["watcher"]["targets"]["default"]["status"] == "current"


@pytest.mark.anyio
async def test_single_service_watches_two_repositories_without_crossing_results(
    repository, database, tmp_path
):
    second = tmp_path / "second"
    shutil.copytree(repository, second)
    (second / "second_only.py").write_text("SECOND_ONLY = True\n", encoding="utf-8")
    targets = (
        RepositoryTarget("first", repository, history_snapshots=0),
        RepositoryTarget("second", second, history_snapshots=0),
    )
    app = create_app(
        database=database,
        enable_mcp=False,
        repository_targets=targets,
        watch_interval=0.2,
    )

    async with app.router.lifespan_context(app):
        await _wait_for_snapshot(database, repository)
        await _wait_for_snapshot(database, second)
        first_row = database.repository(repository)
        second_row = database.repository(second)
        assert first_row is not None and second_row is not None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            repositories = (await client.get("/api/repositories")).json()
            first = (
                await client.get("/api/overview", params={"repository_id": first_row["id"]})
            ).json()
            other = (
                await client.get("/api/overview", params={"repository_id": second_row["id"]})
            ).json()

    assert [item["registry_key"] for item in repositories] == ["first", "second"]
    assert first["files"] == 8
    assert other["files"] == 9


async def _wait_for_snapshot(database, repository, *, after: int = 0) -> dict:
    for _ in range(200):
        row = database.repository(repository)
        snapshot = database.latest_snapshot(int(row["id"])) if row else None
        if snapshot and int(snapshot["id"]) > after:
            return snapshot
        await anyio.sleep(0.02)
    raise AssertionError("watcher did not produce a current snapshot")


async def _wait_for_scan(client: httpx.AsyncClient, expected: str) -> dict:
    for _ in range(100):
        value = (await client.get("/api/scan")).json()
        if value["status"] == expected:
            return value
        await anyio.sleep(0.01)
    raise AssertionError(f"scan did not reach {expected}")


def test_repository_operation_gate_reports_active_work_and_releases_it():
    gate = RepositoryOperationGate()

    admitted = gate.acquire(7, "scan", cooldown_seconds=5, hold=True)
    duplicate = gate.acquire(7, "scan", cooldown_seconds=5, hold=True)

    assert admitted.allowed is True
    assert duplicate.reason == "already_running"
    active = gate.snapshot()["active"]
    assert len(active) == 1
    assert active[0]["repository_id"] == 7
    assert active[0]["operation"] == "scan"
    assert active[0]["started_at"]
    gate.release(7, "scan")
    assert gate.snapshot()["active_count"] == 0


def test_served_map_status_refuses_to_call_a_changed_checkout_current(
    repository, database, monkeypatch
):
    stats = RepositoryScanner(database).scan(repository)
    snapshot = database.latest_snapshot(stats.repository_id)
    assert snapshot is not None

    current = served_map_status(repository, snapshot)
    assert current["state"] == "current"
    assert current["safe_to_plan"] is True
    assert current["mapped"]["commit_sha"] == current["checkout"]["commit_sha"]

    legacy_clean = dict(snapshot)
    legacy_clean["metadata_json"] = "{"
    assert served_map_status(repository, legacy_clean)["state"] == "current"
    wrong_commit = {**legacy_clean, "commit_sha": "f" * 40}
    assert served_map_status(repository, wrong_commit)["state"] == "stale"
    assert (
        served_map_status(repository, {**legacy_clean, "commit_sha": "unversioned"})["state"]
        == "uncertain"
    )
    assert served_map_status(repository, {**legacy_clean, "dirty": True})["state"] == "stale"

    core = repository / "pkg" / "core.py"
    core.write_text(core.read_text(encoding="utf-8") + "\nCHANGED = True\n", encoding="utf-8")
    stale = served_map_status(repository, snapshot)
    assert stale["state"] == "stale"
    assert stale["safe_to_plan"] is False
    assert stale["scan_recommended"] is True
    assert "Refresh" in stale["plain_language"]["action"]

    RepositoryScanner(database).scan(repository)
    dirty_snapshot = database.latest_snapshot(stats.repository_id)
    assert dirty_snapshot is not None
    current_dirty = served_map_status(repository, dirty_snapshot)
    assert current_dirty["state"] == "current"
    core.write_text(core.read_text(encoding="utf-8") + "CHANGED_AGAIN = True\n", encoding="utf-8")
    assert served_map_status(repository, dirty_snapshot)["state"] == "stale"

    legacy_snapshot = dict(dirty_snapshot)
    metadata = json.loads(legacy_snapshot["metadata_json"])
    metadata.pop("working_tree_fingerprint")
    legacy_snapshot["metadata_json"] = json.dumps(metadata)
    uncertain = served_map_status(repository, legacy_snapshot)
    assert uncertain["state"] == "uncertain"
    assert "uncommitted content" in uncertain["plain_language"]["summary"]

    def unavailable(_root):
        raise operational_health.git.GitError("checkout unavailable")

    monkeypatch.setattr(operational_health.git, "metadata", unavailable)
    unavailable_status = served_map_status(repository, snapshot)
    assert unavailable_status["state"] == "unavailable"
    assert unavailable_status["checkout"] is None


@pytest.mark.anyio
async def test_semantic_prepare_requires_a_current_structural_map(repository, database):
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent"}
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    RepositoryScanner(database).scan(repository)
    core = repository / "pkg" / "core.py"
    core.write_text(core.read_text(encoding="utf-8") + "\nCHANGED = True\n", encoding="utf-8")
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        result = (await client.post("/api/semantic/prepare")).json()

    assert result["status"] == "scan_required"
    assert result["map_status"]["state"] == "stale"
    assert result["recommended_action"] == "Refresh the structural scan, then retry understand."
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_jobs").fetchone()[0] == 0


def test_bounded_export_truncates_nested_taxonomy_collections():
    hierarchy = [
        {"key": f"area-{index}", "children": [{"key": f"child-{index}", "children": []}]}
        for index in range(200)
    ]
    result = _compact_taxonomy(
        {
            "hierarchy": hierarchy,
            "reviews": list(range(30)),
            "changes": list(range(300)),
        }
    )

    assert result is not None
    assert result["export_omitted_nodes"] == 150
    assert sum(1 + len(item["children"]) for item in result["hierarchy"]) == 250
    assert len(result["reviews"]) == 25
    assert len(result["changes"]) == 250
    assert _compact_taxonomy(None) is None


@pytest.mark.anyio
async def test_request_limit_preserves_combined_mcp_transport(repository, database):
    RepositoryScanner(database).scan(repository)
    app = create_app(
        database=database,
        repository=repository,
        enable_mcp=True,
        allowed_hosts=["testserver"],
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            timeout=5,
        ) as http_client:
            corrected = await http_client.post(
                "/api/charter/corrections",
                json={
                    "section": "purpose",
                    "statement": "Provide sample calculator behavior.",
                    "author": "test owner",
                    "rationale": "Static facts do not establish the intended user outcome.",
                },
            )
            assert corrected.status_code == 200
            rest_charter = (await http_client.get("/api/overview")).json()["architecture_charter"]
            assert corrected.json()["identity"] == rest_charter["identity"]
            rest_guidance = (
                await http_client.post(
                    "/api/guidance",
                    json={"goal": "Simplify Calculator structure", "intent": "refactor"},
                )
            ).json()
            async with streamable_http_client(
                "http://testserver/mcp",
                http_client=http_client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    overview = await session.call_tool("ANAXIGRAPH_OVERVIEW", arguments={})
                    guidance = await session.call_tool(
                        "ANAXIGRAPH_GUIDE",
                        arguments={
                            "goal": "Simplify Calculator structure",
                            "intent": "refactor",
                        },
                    )
            async with streamable_http_client(
                "http://testserver/executor/mcp",
                http_client=http_client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    executor_tools = await session.list_tools()

    assert overview.isError is False
    assert overview.structuredContent["files"] == 8
    mcp_charter = overview.structuredContent["architecture_charter"]
    assert mcp_charter["identity"] == rest_charter["identity"]
    assert mcp_charter["readiness"] == rest_charter["readiness"]
    assert mcp_charter["purpose"] == rest_charter["purpose"]
    assert mcp_charter["caveats"] == rest_charter["caveats"]
    assert mcp_charter["declared_context"] == rest_charter["declared_context"]
    assert guidance.isError is False
    mcp_guidance = guidance.structuredContent
    assert mcp_guidance["identity"] == rest_guidance["identity"]
    assert mcp_guidance["recommendation"] == rest_guidance["recommendation"]
    assert mcp_guidance["understanding"] == rest_guidance["understanding"]
    assert mcp_guidance["impact_summary"] == rest_guidance["impact_summary"]
    assert mcp_guidance["confidence"] == rest_guidance["confidence"]
    assert {tool.name for tool in executor_tools.tools} == {
        "ANAXIGRAPH_SEMANTIC_STATUS",
        "ANAXIGRAPH_SEMANTIC_SCHEMA",
        "ANAXIGRAPH_SEMANTIC_WORK",
        "ANAXIGRAPH_SEMANTIC_EVIDENCE",
        "ANAXIGRAPH_SEMANTIC_SUBMIT",
        "ANAXIGRAPH_SEMANTIC_RELEASE",
        "ANAXIGRAPH_SEMANTIC_FAIL",
    }
