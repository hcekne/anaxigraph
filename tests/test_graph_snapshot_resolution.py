"""Explicit graph snapshot ids fail loud; only unscanned repositories answer empty."""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

import anaxigraph.git as git
from anaxigraph.api import create_app
from anaxigraph.bounded_export import bounded_export
from anaxigraph.config import load_config
from anaxigraph.graph_contract import (
    GRAPH_QUERY_VERSION,
    GraphNeighborhoodRequest,
    GraphPageRequest,
)
from anaxigraph.persistence.graph_delta_read import empty_graph_delta
from anaxigraph.scanner import RepositoryScanner

_UNKNOWN_SNAPSHOT_ID = 999_999


def _second_repository(repository: Path, tmp_path: Path) -> Path:
    root = tmp_path / "second"
    shutil.copytree(repository, root)
    return root


def test_graph_reads_reject_unknown_or_foreign_snapshot_ids(repository, database, tmp_path):
    first = RepositoryScanner(database).scan(repository)
    second = RepositoryScanner(database).scan(_second_repository(repository, tmp_path))

    for snapshot_id in (_UNKNOWN_SNAPSHOT_ID, second.snapshot_id):
        with pytest.raises(ValueError, match="does not belong to the repository"):
            database.graph(first.repository_id, snapshot_id, query=GraphPageRequest())
        with pytest.raises(ValueError, match="does not belong to the repository"):
            database.graph_neighborhood(
                first.repository_id,
                snapshot_id,
                query=GraphNeighborhoodRequest(node="pkg/core.py"),
            )
        with pytest.raises(ValueError, match="target graph snapshot does not belong"):
            database.graph_delta(
                first.repository_id,
                first.snapshot_id,
                snapshot_id,
                node_limit=100,
                edge_limit=100,
            )


def test_graph_delta_missing_target_matches_missing_baseline_behaviour(
    repository, database, tmp_path
):
    first = RepositoryScanner(database).scan(repository)
    second = RepositoryScanner(database).scan(_second_repository(repository, tmp_path))

    with pytest.raises(ValueError, match="baseline graph snapshot does not belong"):
        database.graph_delta(
            first.repository_id,
            second.snapshot_id,
            first.snapshot_id,
            node_limit=100,
            edge_limit=100,
        )
    with pytest.raises(ValueError, match="target graph snapshot does not belong"):
        database.graph_delta(
            first.repository_id,
            first.snapshot_id,
            second.snapshot_id,
            node_limit=100,
            edge_limit=100,
        )


@pytest.mark.anyio
async def test_graph_routes_return_400_for_unknown_and_foreign_snapshot_ids(
    repository, database, tmp_path
):
    first = RepositoryScanner(database).scan(repository)
    second = RepositoryScanner(database).scan(_second_repository(repository, tmp_path))
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        unknown_page = await client.get("/api/graph", params={"snapshot_id": _UNKNOWN_SNAPSHOT_ID})
        foreign_page = await client.get("/api/graph", params={"snapshot_id": second.snapshot_id})
        unknown_neighbors = await client.get(
            "/api/graph/neighbors",
            params={"node": "pkg/core.py", "snapshot_id": _UNKNOWN_SNAPSHOT_ID},
        )
        foreign_neighbors = await client.get(
            "/api/graph/neighbors",
            params={"node": "pkg/core.py", "snapshot_id": second.snapshot_id},
        )
        unknown_target = await client.get(
            "/api/graph/delta",
            params={
                "from_snapshot_id": first.snapshot_id,
                "to_snapshot_id": _UNKNOWN_SNAPSHOT_ID,
            },
        )
        foreign_target = await client.get(
            "/api/graph/delta",
            params={
                "from_snapshot_id": first.snapshot_id,
                "to_snapshot_id": second.snapshot_id,
            },
        )
        served_page = await client.get("/api/graph", params={"snapshot_id": first.snapshot_id})

    refusals = (
        unknown_page,
        foreign_page,
        unknown_neighbors,
        foreign_neighbors,
        unknown_target,
        foreign_target,
    )
    assert [response.status_code for response in refusals] == [400] * len(refusals)
    assert all(
        "does not belong to the repository" in response.json()["detail"] for response in refusals
    )
    assert served_page.status_code == 200
    assert served_page.json()["availability"] == "current"


@pytest.mark.anyio
async def test_graph_for_unscanned_repository_is_labelled_unscanned(repository, database):
    repository_id = database.ensure_repository(
        path=repository,
        name="Unscanned fixture",
        git=git.metadata(repository),
    )
    app = create_app(database=database, repository=repository, enable_mcp=False)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        page = await client.get("/api/graph")
        neighbors = await client.get("/api/graph/neighbors", params={"node": "pkg/core.py"})

    assert page.status_code == 200
    payload = page.json()
    assert payload["repository_id"] == repository_id
    assert payload["contract_version"] == GRAPH_QUERY_VERSION == "graph-query-v2"
    assert payload["snapshot"] is None
    assert payload["availability"] == "unscanned"
    assert payload["nodes"] == []
    assert payload["edges"] == []
    assert payload["counts"]["matching_nodes"] == 0
    assert neighbors.status_code == 200
    assert neighbors.json()["availability"] == "unscanned"
    assert neighbors.json()["snapshot"] is None


def test_scanned_graph_reads_are_labelled_current(repository, database):
    first = RepositoryScanner(database).scan(repository)
    second = RepositoryScanner(database).scan(repository, run_type="update")

    page = database.graph(first.repository_id, query=GraphPageRequest())
    neighborhood = database.graph_neighborhood(
        first.repository_id,
        query=GraphNeighborhoodRequest(node="pkg/core.py"),
    )
    delta = database.graph_delta(
        first.repository_id,
        first.snapshot_id,
        second.snapshot_id,
        node_limit=10,
        edge_limit=10,
    )

    assert page["contract_version"] == "graph-query-v2"
    assert page["availability"] == "current"
    assert neighborhood["availability"] == "current"
    assert delta["availability"] == "current"


def test_bounded_export_of_unscanned_repository_reports_unscanned_graph(repository, database):
    repository_id = database.ensure_repository(
        path=repository,
        name="Unscanned fixture",
        git=git.metadata(repository),
    )

    export = bounded_export(database, repository_id, load_config(repository))

    assert export["graph"]["snapshot"] is None
    assert export["graph"]["availability"] == "unscanned"
    assert export["overview"]["snapshot"] is None


def test_empty_graph_delta_payload_is_labelled_unscanned():
    payload = empty_graph_delta(7)

    assert payload["repository_id"] == 7
    assert payload["availability"] == "unscanned"
    assert payload["baseline_snapshot"] is None
    assert payload["target_snapshot"] is None
