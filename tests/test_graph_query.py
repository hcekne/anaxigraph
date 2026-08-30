from __future__ import annotations

import json

import httpx
import pytest

from anaxigraph.api import create_app
from anaxigraph.graph_contract import (
    GRAPH_QUERY_VERSION,
    MAX_EDGE_LIMIT,
    MAX_NODE_LIMIT,
    GraphNeighborhoodRequest,
    GraphPageRequest,
    _with_response_telemetry,
)
from anaxigraph.scanner import RepositoryScanner


def test_response_telemetry_counts_utf8_wire_bytes_without_ascii_escaping():
    response = _with_response_telemetry({"label": "Anaxi → graph"}, 0, action="test")
    expected = len(
        json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    )

    assert response["telemetry"]["payload_bytes"] == expected
    assert expected < len(json.dumps(response, separators=(",", ":")).encode("utf-8"))


def test_graph_pages_cover_every_matching_node_and_edge(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    cursor = ""
    node_ids: set[int] = set()
    edge_ids: set[int] = set()
    pages = 0
    totals = None

    while True:
        page = database.graph(
            stats.repository_id,
            query=GraphPageRequest(
                cursor=cursor,
                node_limit=2,
                edge_limit=1,
                include_external=True,
            ),
        )
        pages += 1
        assert page["contract_version"] == GRAPH_QUERY_VERSION
        assert page["counts"]["page_internal_nodes"] <= 2
        assert page["counts"]["page_edges"] <= 1
        totals = (page["counts"]["matching_nodes"], page["counts"]["matching_edges"])
        node_ids.update(node["id"] for node in page["nodes"] if isinstance(node["id"], int))
        edge_ids.update(edge["id"] for edge in page["edges"])
        cursor = page["next_cursor"] or ""
        if not cursor:
            break
        assert pages < 100

    assert totals is not None
    assert len(node_ids) == totals[0] == stats.discovered
    assert len(edge_ids) == totals[1]
    assert pages > 1


def test_graph_filters_are_exact_and_cursors_are_bound(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    python = database.graph(
        stats.repository_id,
        query=GraphPageRequest(languages=("python",), node_limit=100, edge_limit=100),
    )
    assert python["counts"]["matching_nodes"] == 5
    assert all(node["language"] == "python" for node in python["nodes"])

    domain = database.graph(
        stats.repository_id,
        query=GraphPageRequest(areas=("domain",), node_limit=100, edge_limit=100),
    )
    assert {node["path"] for node in domain["nodes"]} == {
        "pkg/__init__.py",
        "pkg/consumer.py",
        "pkg/core.py",
        "pkg/util.py",
    }

    imports = database.graph(
        stats.repository_id,
        query=GraphPageRequest(relationship_types=("imports",), node_limit=2, edge_limit=1),
    )
    assert imports["next_cursor"]
    assert all(edge["type"] == "imports" for edge in imports["edges"])
    with pytest.raises(ValueError, match="does not match"):
        database.graph(
            stats.repository_id,
            query=GraphPageRequest(
                cursor=imports["next_cursor"],
                path="pkg",
                node_limit=2,
                edge_limit=1,
                relationship_types=("imports",),
            ),
        )


def test_graph_finding_path_and_payload_telemetry(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    finding = database.findings(stats.repository_id)[0]
    page = database.graph(
        stats.repository_id,
        query=GraphPageRequest(
            path="pkg",
            finding_types=(str(finding["finding_type"]),),
            node_limit=100,
            edge_limit=100,
        ),
    )

    assert page["counts"]["matching_nodes"] >= 1
    assert all("pkg" in node["path"] for node in page["nodes"])
    assert page["telemetry"]["duration_ms"] >= 0
    serialized = len(json.dumps(page, separators=(",", ":")).encode())
    assert page["telemetry"]["payload_bytes"] == serialized


def test_graph_contract_rejects_unsafe_limits_and_malformed_cursor():
    with pytest.raises(ValueError, match="node_limit"):
        GraphPageRequest(node_limit=MAX_NODE_LIMIT + 1)
    with pytest.raises(ValueError, match="edge_limit"):
        GraphPageRequest(edge_limit=MAX_EDGE_LIMIT + 1)
    with pytest.raises(ValueError, match="malformed"):
        from anaxigraph.graph_contract import GraphCursor

        GraphCursor.decode("not-a-cursor")


def test_graph_overview_returns_bounded_architecture_aggregates(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    overview = database.graph_overview(
        stats.repository_id,
        level="area",
        group_limit=2,
        edge_limit=1,
        include_external=True,
    )

    assert overview["contract_version"] == "graph-overview-v1"
    assert overview["counts"]["returned_groups"] == 2
    assert overview["counts"]["groups"] >= 2
    assert overview["counts"]["returned_aggregate_edges"] <= 1
    assert overview["counts"]["omitted_groups"] == overview["counts"]["groups"] - 2
    assert all(node["level"] == "area" for node in overview["nodes"])
    assert overview["telemetry"]["payload_bytes"] == len(
        json.dumps(overview, separators=(",", ":")).encode()
    )


def test_graph_neighborhood_expands_by_direction_and_bounded_depth(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    outgoing = database.graph_neighborhood(
        stats.repository_id,
        query=GraphNeighborhoodRequest(
            node="pkg/core.py",
            direction="outgoing",
            depth=1,
            node_limit=10,
            edge_limit=10,
        ),
    )
    incoming = database.graph_neighborhood(
        stats.repository_id,
        query=GraphNeighborhoodRequest(
            node="pkg/core.py",
            direction="incoming",
            depth=1,
            node_limit=10,
            edge_limit=10,
        ),
    )

    assert outgoing["contract_version"] == "graph-neighborhood-v1"
    assert {node["path"] for node in outgoing["nodes"]} == {
        "pkg/core.py",
        "pkg/util.py",
    }
    assert "pkg/consumer.py" in {node["path"] for node in incoming["nodes"]}
    assert next(node for node in outgoing["nodes"] if node["selected"])["path"] == "pkg/core.py"
    assert max(node["graph_depth"] for node in outgoing["nodes"]) <= 1


def test_graph_neighborhood_reports_truncation_and_missing_seed(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    bounded = database.graph_neighborhood(
        stats.repository_id,
        query=GraphNeighborhoodRequest(
            node="pkg/core.py",
            depth=2,
            node_limit=1,
            edge_limit=1,
        ),
    )

    assert bounded["counts"]["returned_internal_nodes"] == 1
    assert bounded["counts"]["omitted_nodes"] > 0
    with pytest.raises(ValueError, match="not present"):
        database.graph_neighborhood(
            stats.repository_id,
            query=GraphNeighborhoodRequest(node="missing.py"),
        )


@pytest.mark.anyio
async def test_rest_graph_routes_enforce_bounds_and_cursor_contract(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    app = create_app(database=database, repository=repository, enable_mcp=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        overview = await client.get(
            "/api/graph/overview", params={"group_limit": 2, "edge_limit": 1}
        )
        page = await client.get("/api/graph", params={"node_limit": 2, "edge_limit": 1})
        neighbors = await client.get(
            "/api/graph/neighbors", params={"node": "pkg/core.py", "depth": 1}
        )
        oversized = await client.get("/api/graph", params={"node_limit": MAX_NODE_LIMIT + 1})
        missing = await client.get("/api/graph/neighbors", params={"node": "missing.py"})
        mismatch = await client.get(
            "/api/graph",
            params={
                "cursor": page.json()["next_cursor"],
                "node_limit": 2,
                "edge_limit": 1,
                "path": "pkg",
            },
        )
        delta = await client.get("/api/graph/delta", params={"from_snapshot_id": stats.snapshot_id})

    assert overview.status_code == 200
    assert overview.json()["contract_version"] == "graph-overview-v1"
    assert page.status_code == 200
    assert page.json()["counts"]["page_internal_nodes"] == 2
    assert page.json()["quality"]["plain_language"]["version"] == ("graph-quality-explanation-v1")
    assert neighbors.status_code == 200
    assert neighbors.json()["contract_version"] == "graph-neighborhood-v1"
    assert oversized.status_code == 422
    assert missing.status_code == 400
    assert mismatch.status_code == 400
    assert delta.status_code == 200
    assert delta.json()["contract_version"] == "graph-delta-v1"


def test_graph_delta_reports_bounded_node_and_edge_changes(repository, database):
    first = RepositoryScanner(database).scan(repository)
    (repository / "pkg" / "util.py").write_text(
        '"""Changed arithmetic helpers."""\n\ndef double(value: int) -> int:\n    return value * 3\n',
        encoding="utf-8",
    )
    (repository / "pkg" / "new_service.py").write_text(
        "from pkg.core import Calculator\n\ndef create():\n    return Calculator()\n",
        encoding="utf-8",
    )
    second = RepositoryScanner(database).scan(repository)

    delta = database.graph_delta(
        first.repository_id,
        first.snapshot_id,
        second.snapshot_id,
        node_limit=100,
        edge_limit=100,
    )
    node_changes = {
        (item["change"], (item["after"] or item["before"])["path"])
        for item in delta["node_changes"]
    }

    assert delta["contract_version"] == "graph-delta-v1"
    assert ("changed", "pkg/util.py") in node_changes
    assert ("added", "pkg/new_service.py") in node_changes
    assert delta["counts"]["nodes"]["changed"] >= 1
    assert delta["counts"]["nodes"]["added"] >= 1
    assert delta["counts"]["edges"]["added"] >= 1
    assert any(item["source"] == "pkg/new_service.py" for item in delta["edge_changes"])
