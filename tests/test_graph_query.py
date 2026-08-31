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


def test_graph_map_layer_controls_placement_and_region_filters(repository, database):
    stats = RepositoryScanner(database).scan(repository)

    declared = database.graph(
        stats.repository_id,
        query=GraphPageRequest(
            map_layer="declared",
            areas=("unconfigured",),
            node_limit=100,
            edge_limit=100,
        ),
    )
    path = database.graph(
        stats.repository_id,
        query=GraphPageRequest(
            map_layer="path",
            areas=("application",),
            node_limit=100,
            edge_limit=100,
        ),
    )

    assert declared["architecture_frame"]["map_layer"] == "declared"
    assert declared["counts"]["matching_nodes"] > 0
    assert all(node["architecture_area"] == "unconfigured" for node in declared["nodes"])
    assert all(node["architecture_layer"] == "declared" for node in declared["nodes"])
    assert path["architecture_frame"]["map_layer"] == "path"
    assert {node["path"] for node in path["nodes"]} == {
        "pkg/__init__.py",
        "pkg/consumer.py",
        "pkg/core.py",
        "pkg/util.py",
        "web/App.tsx",
        "web/helper.ts",
    }
    assert all(node["architecture_layer"] == "path" for node in path["nodes"])


def test_graph_cursor_is_bound_to_the_selected_map_layer(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    page = database.graph(
        stats.repository_id,
        query=GraphPageRequest(map_layer="current", node_limit=2, edge_limit=1),
    )

    assert page["next_cursor"]
    with pytest.raises(ValueError, match="does not match"):
        database.graph(
            stats.repository_id,
            query=GraphPageRequest(
                cursor=page["next_cursor"],
                map_layer="path",
                node_limit=2,
                edge_limit=1,
            ),
        )


def test_historical_graph_uses_current_map_without_erasing_original_placement(repository, database):
    first = RepositoryScanner(database).scan(repository)
    (repository / ".anaxigraph.yml").write_text(
        """project:
  name: Sample Observatory
groups:
  application-core:
    level: subsystem
    parent: application
    paths: [pkg/**]
  web-frontend:
    level: subsystem
    parent: application
    paths: [web/**]
coverage:
  files: [coverage.xml]
ignore: [ignored/**]
""",
        encoding="utf-8",
    )
    (repository / "pkg" / "core.py").write_text(
        (repository / "pkg" / "core.py").read_text(encoding="utf-8") + "\nCURRENT = True\n",
        encoding="utf-8",
    )
    second = RepositoryScanner(database).scan(repository)

    historical = database.graph(
        first.repository_id,
        first.snapshot_id,
        query=GraphPageRequest(node_limit=100, edge_limit=100),
    )
    core = next(node for node in historical["nodes"] if node["path"] == "pkg/core.py")

    assert historical["architecture_frame"] == {
        "mode": "present_day",
        "reference_snapshot_id": second.snapshot_id,
        "historical_snapshot_id": first.snapshot_id,
        "reclassified": True,
        "map_layer": "current",
    }
    assert (core["architecture_area"], core["architecture_subsystem"]) == (
        "application",
        "application-core",
    )
    assert core["historical_architecture"]["subsystem"] == "domain"


def test_historical_graph_projects_directory_renames_through_current_map(repository, database):
    legacy = repository / "src" / "old_package"
    (legacy / "dashboard").mkdir(parents=True)
    (legacy / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    (legacy / "dashboard" / "app.js").write_text("export const app = true;\n", encoding="utf-8")
    (legacy / "dashboard" / "styles.css").write_text("body { color: black; }\n", encoding="utf-8")
    first = RepositoryScanner(database).scan(repository)

    current = repository / "src" / "new_package"
    legacy.rename(current)
    (repository / ".anaxigraph.yml").write_text(
        """project:
  name: Sample Observatory
groups:
  web-frontend:
    level: subsystem
    parent: application
    paths: [src/new_package/dashboard/**]
  backend-api:
    level: subsystem
    parent: application
    paths: [src/new_package/**]
coverage:
  files: [coverage.xml]
ignore: [ignored/**]
""",
        encoding="utf-8",
    )
    second = RepositoryScanner(database).scan(repository)

    historical = database.graph(
        first.repository_id,
        first.snapshot_id,
        query=GraphPageRequest(node_limit=100, edge_limit=100),
    )
    nodes = {node["path"]: node for node in historical["nodes"]}

    assert historical["architecture_frame"]["reference_snapshot_id"] == second.snapshot_id
    assert nodes["src/old_package/service.py"]["architecture_subsystem"] == "backend-api"
    assert nodes["src/old_package/dashboard/app.js"]["architecture_subsystem"] == "web-frontend"
    assert nodes["src/old_package/service.py"]["historical_architecture"]["subsystem"] == (
        "application-code"
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
    with pytest.raises(ValueError, match="map_layer"):
        GraphPageRequest(map_layer="invented")
    with pytest.raises(ValueError, match="malformed"):
        from anaxigraph.graph_contract import GraphCursor

        GraphCursor.decode("not-a-cursor")


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
        page = await client.get("/api/graph", params={"node_limit": 2, "edge_limit": 1})
        path_page = await client.get(
            "/api/graph",
            params={"map_layer": "path", "area": "application", "node_limit": 100},
        )
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

    assert page.status_code == 200
    assert page.json()["counts"]["page_internal_nodes"] == 2
    assert page.json()["quality"]["plain_language"]["version"] == ("graph-quality-explanation-v1")
    assert path_page.status_code == 200
    assert path_page.json()["architecture_frame"]["map_layer"] == "path"
    assert all(node["architecture_area"] == "application" for node in path_page.json()["nodes"])
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
