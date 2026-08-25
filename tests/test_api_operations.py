from __future__ import annotations

import threading

import anyio
import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from anaxigraph.api import create_app
from anaxigraph.api_limits import MAX_REQUEST_BODY_BYTES
from anaxigraph.api_operation_gate import RepositoryOperationGate
from anaxigraph.bounded_export import _compact_taxonomy
from anaxigraph.persistence.schema import SCHEMA_VERSION
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
            "/api/agent-scope",
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
    assert "group_hierarchy" not in export["overview"]
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
            async with streamable_http_client(
                "http://testserver/mcp",
                http_client=http_client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    overview = await session.call_tool("ANAXIGRAPH_OVERVIEW", arguments={})

    assert overview.isError is False
    assert overview.structuredContent["files"] == 8
